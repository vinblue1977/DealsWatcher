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
# Stand-ins, so tests need neither a frontend build nor the built Lambda layer.
CDK_CONTEXT["siteDir"] = "tests/fixtures/site"
CDK_CONTEXT["layerDir"] = "tests/fixtures/layer"


def _stack(context: dict | None = None, account: str | None = "123456789012") -> DealsWatcherStack:
    app = cdk.App(context=CDK_CONTEXT | ({"githubRepo": REPO} if context is None else context))
    stack = DealsWatcherStack(app, "DealsWatcher", env=cdk.Environment(account=account, region="us-east-2"))
    cdk.Aspects.of(app).add(AwsSolutionsChecks())
    return stack


@functools.cache
def _build(context: str | None, account: str | None) -> tuple[DealsWatcherStack, Template]:
    stack = _stack(None if context is None else json.loads(context), account)
    return stack, Template.from_stack(stack)


def _synthesized(context: str | None = None, account: str | None = "123456789012") -> tuple[DealsWatcherStack, Template]:
    """A stack and its template, built once per context (as JSON) and account: synthesizing is the slow part of these tests.

    Callers go through here so that explicit and default arguments share one cache entry.
    """
    return _build(context, account)


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


def test_deploy_role_can_only_assume_the_cdk_bootstrap_roles_and_describe_the_table() -> None:
    policies = _template().find_resources("AWS::IAM::Policy")
    statements = [
        statement
        for policy in policies.values()
        if any(str(role.get("Ref", "")).startswith("GitHubDeployRole") for role in policy["Properties"]["Roles"])
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert statements, "no policy found for the deploy role"
    actions = {a for s in statements for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert actions == {"sts:AssumeRole", "dynamodb:DescribeTable"}
    assume = [s for s in statements if s["Action"] == "sts:AssumeRole"]
    assert assume and all(":role/cdk-hnb659fds-*-" in json.dumps(s["Resource"]) for s in assume)


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


TAGGABLE = {
    "AWS::DynamoDB::GlobalTable",
    "AWS::IAM::Role",
    "AWS::S3::Bucket",
    "AWS::Lambda::Function",
    "AWS::Logs::LogGroup",
    "AWS::CloudFront::Distribution",
    "AWS::Cognito::UserPool",
    "AWS::ApiGatewayV2::Api",
    "AWS::ApiGatewayV2::Stage",
}


def _has_project_tag(node: object) -> bool:
    """Tags appear as [{Key, Value}] lists, or as {project: ...} maps (API Gateway, Cognito)."""
    if isinstance(node, dict):
        for key in ("Tags", "UserPoolTags"):
            tags = node.get(key)
            if isinstance(tags, list) and {"Key": "project", "Value": "deals-watcher"} in tags:
                return True
            if isinstance(tags, dict) and tags.get("project") == "deals-watcher":
                return True
        return any(map(_has_project_tag, node.values()))
    if isinstance(node, list):
        return any(map(_has_project_tag, node))
    return False


def test_every_taggable_resource_has_the_project_tag() -> None:
    resources = _template({"githubRepo": REPO}).to_json()["Resources"]
    assert TAGGABLE <= {r["Type"] for r in resources.values()}, "extend TAGGABLE when the stack gains a resource type"
    untagged = [name for name, r in resources.items() if r["Type"] in TAGGABLE and not _has_project_tag(r["Properties"])]
    assert untagged == []


def test_refresh_tokens_rotate_so_each_renewal_extends_the_session() -> None:
    _template().has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "RefreshTokenRotation": {"Feature": "ENABLED", "RetryGracePeriodSeconds": 60},
            "RefreshTokenValidity": 365 * 24 * 60,
            "EnableTokenRevocation": True,
        },
    )


def test_the_web_push_public_key_is_configured_so_the_app_can_subscribe() -> None:
    key = json.loads(Path("cdk.json").read_text())["context"]["vapidPublicKey"]
    assert len(key) == 87 and key.startswith("B")  # an uncompressed P-256 point, base64url


@pytest.fixture(autouse=True)
def _no_alert_email_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALERT_EMAIL", raising=False)  # a developer's own setting must not change what these tests build


def test_one_crash_alarm_on_the_feed_checker_emails_through_one_topic() -> None:
    template = _template()
    template.resource_count_is("AWS::CloudWatch::Alarm", 1)  # the account's free allowance is 10 alarms: this stays inside it
    template.resource_count_is("AWS::SNS::Topic", 1)
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "AWS/Lambda",
            "MetricName": "Errors",
            "Statistic": "Sum",
            "Period": 1800,
            "EvaluationPeriods": 2,
            "DatapointsToAlarm": 2,  # two failed runs in a row, about an hour: a single blip is retried and stays quiet
            "Threshold": 1,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "TreatMissingData": "notBreaching",
            "AlarmActions": [Match.any_value()],
            "OKActions": Match.absent(),  # failure emails only: an "OK" email would also fire when the alarm is first created
        },
    )
    (alarm,) = template.find_resources("AWS::CloudWatch::Alarm").values()
    assert "FeedsChecker" in json.dumps(alarm["Properties"]["Dimensions"])  # it watches the feed checker, not another function


def test_the_alert_topic_only_accepts_encrypted_connections() -> None:
    template = _template()
    template.has_resource_properties(
        "AWS::SNS::TopicPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Effect": "Deny", "Condition": {"Bool": {"aws:SecureTransport": "false"}}})]
                )
            }
        },
    )


def test_there_is_no_email_subscription_unless_an_address_is_supplied() -> None:
    _template().resource_count_is("AWS::SNS::Subscription", 0)


def test_the_alert_address_comes_from_context_or_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _template({"alertEmail": "owner@example.com"}).has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "owner@example.com"}
    )
    monkeypatch.setenv("ALERT_EMAIL", "from-env@example.com")
    _template({"fromEnvironment": "yes"}).has_resource_properties("AWS::SNS::Subscription", {"Endpoint": "from-env@example.com"})


def test_the_alert_address_is_not_part_of_any_resource_name() -> None:
    """Resource names show in the public deploy logs; the address itself is only ever a property value."""
    template = _template({"alertEmail": "owner@example.com"})
    assert "owner" not in json.dumps(list(template.find_resources("AWS::SNS::Subscription")))
    assert "owner" not in json.dumps(list(template.to_json()["Resources"]))


def test_a_malformed_alert_address_is_refused_without_repeating_it() -> None:
    with pytest.raises(ValueError, match="not a valid address") as error:
        _template({"alertEmail": "not-an-email"})
    assert "not-an-email" not in str(error.value)  # CI logs are public


def test_api_function_can_only_use_the_table_operations_it_needs() -> None:
    policies = _template().find_resources("AWS::IAM::Policy")
    actions = {
        action
        for policy in policies.values()
        if any(str(role.get("Ref", "")).startswith("WebApi") for role in policy["Properties"]["Roles"])
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "dynamodb:GetItem" in statement["Action"]
        for action in statement["Action"]
    }
    assert actions == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"}


def _feed_function(template: Template) -> dict:
    (function,) = [
        f
        for f in template.find_resources("AWS::Lambda::Function").values()
        if f["Properties"].get("Handler") == "feeds.handler.handler"
    ]
    return function["Properties"]


def test_feed_checker_has_room_for_all_its_feeds_in_its_timeout() -> None:
    assert _feed_function(_template())["Timeout"] == 90  # feed reading stops starting feeds after 40 s


def test_every_log_group_is_kept_for_three_days() -> None:
    groups = _template().find_resources("AWS::Logs::LogGroup")
    assert len(groups) >= 3  # the checker, the API and the API access log
    assert {g["Properties"].get("RetentionInDays") for g in groups.values()} == {3}


def test_feed_checker_runs_on_the_hour_and_half_hour() -> None:
    template = _template()
    (checker_id,) = [
        name
        for name, f in template.find_resources("AWS::Lambda::Function").items()
        if f["Properties"].get("Handler") == "feeds.handler.handler"
    ]
    (rule,) = [r["Properties"] for r in template.find_resources("AWS::Events::Rule").values()]
    assert rule["ScheduleExpression"] == "cron(0,30 * * * ? *)" and rule["State"] == "ENABLED"  # :00 and :30, 30 minutes apart
    (target,) = rule["Targets"]
    assert target["Arn"] == {"Fn::GetAtt": [checker_id, "Arn"]}  # and it starts the checker, not something else


def test_feed_checker_can_only_use_the_table_operations_it_needs() -> None:
    policies = _template().find_resources("AWS::IAM::Policy")
    actions = {
        action
        for policy in policies.values()
        if any(str(role.get("Ref", "")).startswith("FeedsChecker") for role in policy["Properties"]["Roles"])
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "dynamodb:Scan" in statement["Action"]
        for action in statement["Action"]
    }
    assert actions == {
        "dynamodb:Scan",
        "dynamodb:Query",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
    }


def test_the_checker_does_not_retry_by_itself_so_one_failed_run_is_one_error() -> None:
    template = _template()
    template.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_a_blank_or_padded_alert_address_is_tolerated() -> None:
    _template({"alertEmail": "  "}).resource_count_is("AWS::SNS::Subscription", 0)  # blank means none, not an error
    _template({"alertEmail": " owner@example.com\n"}).has_resource_properties(
        "AWS::SNS::Subscription", {"Endpoint": "owner@example.com"}
    )
