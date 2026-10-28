"""Infrastructure tests: the stack synthesizes, passes cdk-nag, and its table and deploy role are locked down."""

import functools
import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks

from infra.stack import DealsWatcherStack

REPO = "test-owner@1/test-repo@2"
# The same feature flags as a real synth, so tests render the template the way a deploy does.
CDK_CONTEXT = {k: v for k, v in json.loads(Path("cdk.json").read_text())["context"].items() if k.startswith("@")}


def _stack(context: dict | None = None, account: str | None = "123456789012") -> DealsWatcherStack:
    app = cdk.App(context=CDK_CONTEXT | ({"githubRepo": REPO} if context is None else context))
    stack = DealsWatcherStack(app, "DealsWatcher", env=cdk.Environment(account=account, region="us-east-2"))
    cdk.Aspects.of(app).add(AwsSolutionsChecks())
    return stack


@functools.cache
def _synthesized(context: str | None = None, account: str | None = "123456789012") -> tuple[DealsWatcherStack, Template]:
    """A stack and its template, built once per context (as JSON) and account: synthesizing is the slow part of these tests."""
    stack = _stack(None if context is None else json.loads(context), account)
    return stack, Template.from_stack(stack)


def _template(context: dict | None = None) -> Template:
    return _synthesized(None if context is None else json.dumps(context, sort_keys=True))[1]


def test_synthesizes_in_us_east_2() -> None:
    assert _synthesized()[0].region == "us-east-2"


@pytest.mark.parametrize("account", ["123456789012", None])  # None: CI synth without AWS credentials
def test_no_cdk_nag_findings(account: str | None) -> None:
    stack, _ = _synthesized(account=account)  # synthesizing runs the aspects
    annotations = Annotations.from_stack(stack)
    assert annotations.find_error("*", Match.string_like_regexp("AwsSolutions-.*")) == []
    assert annotations.find_warning("*", Match.string_like_regexp("AwsSolutions-.*")) == []


def test_table_is_protected_on_demand_and_expires_old_items() -> None:
    template = _template()
    template.has_resource(
        "AWS::DynamoDB::GlobalTable",
        {
            "DeletionPolicy": "Retain",
            "Properties": Match.object_like(
                {
                    "BillingMode": "PAY_PER_REQUEST",
                    "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
                    "Replicas": [
                        Match.object_like(
                            {
                                "DeletionProtectionEnabled": True,
                                "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
                            }
                        )
                    ],
                }
            ),
        },
    )


def test_deploy_role_trusts_only_this_repo_production_environment() -> None:
    template = _template()
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": Match.object_like(
                {
                    "Statement": [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRoleWithWebIdentity",
                                "Condition": {
                                    "StringEquals": {
                                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                        "token.actions.githubusercontent.com:sub": f"repo:{REPO}:environment:production",
                                    }
                                },
                            }
                        )
                    ]
                }
            )
        },
    )
    # The provider is shared with other stacks in the account, so this stack must not create one.
    template.resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 0)
    template.resource_count_is("AWS::IAM::OIDCProvider", 0)


def test_no_deploy_role_without_repo() -> None:
    web_identity = {
        "AssumeRolePolicyDocument": Match.object_like(
            {"Statement": [Match.object_like({"Action": "sts:AssumeRoleWithWebIdentity"})]}
        )
    }
    _template({}).resource_properties_count_is("AWS::IAM::Role", web_identity, 0)


def test_rejects_malformed_repo() -> None:
    with pytest.raises(ValueError, match="githubRepo"):
        _stack({"githubRepo": "not a repo"})
