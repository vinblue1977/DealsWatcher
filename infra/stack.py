"""The DealsWatcher stack: data table, sign-in, API, hosting and the GitHub deploy role."""

import re
from pathlib import Path

from aws_cdk import CfnOutput, CfnResource, DefaultStackSynthesizer, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from cdk_nag import NagPackSuppression, NagSuppressions, RegexAppliesTo
from constructs import Construct

from infra.feeds import Feeds
from infra.push import VAPID_PARAM
from infra.web import Web

GITHUB = "token.actions.githubusercontent.com"


class DealsWatcherStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add("project", "deals-watcher")  # on every taggable resource (also the account's cost allocation tag)

        # One table for everything, keyed by user (PK) and item type (SK): USER#<id> / WATCH#<id>, RULE#<id>, PUSH#<hash>...
        # Shared product records use PK PRODUCT#<url-hash>, so each URL is fetched once however many users watch it.
        self.table = dynamodb.TableV2(
            self,
            "Table",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            time_to_live_attribute="ttl",  # price history and seen-deal markers expire on their own
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        CfnOutput(self, "TableName", value=self.table.table_name)

        # Locked runtime dependencies (layer/requirements.txt), built by `make layer`.
        layer_dir = self.node.try_get_context("layerDir") or "build/layer"
        if not Path(layer_dir).is_dir():
            raise FileNotFoundError(f"Lambda layer not found at {layer_dir}; run `make layer` first")
        layer = lambda_.LayerVersion(
            self,
            "Deps",
            code=lambda_.Code.from_asset(layer_dir),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_14],
            compatible_architectures=[lambda_.Architecture.ARM_64],
            description="Locked runtime dependencies (layer/requirements.txt)",
        )
        push_env = {"VAPID_KEY_PARAM": VAPID_PARAM, "VAPID_SUBJECT": "https://github.com/vinblue1977/DealsWatcher"}
        site_dir = self.node.try_get_context("siteDir") or "frontend/dist"
        Web(
            self,
            "Web",
            table=self.table,
            site_dir=site_dir,
            layer=layer,
            push_env=push_env,
        )
        Feeds(self, "Feeds", table=self.table, layer=layer, push_env=push_env)

        github_repo: str = self.node.try_get_context("githubRepo") or ""
        if github_repo:
            self._github_deploy_role(github_repo)
        self._tag_helper_resources()

    def _tag_helper_resources(self) -> None:
        """CDK's own helper roles and functions (bucket auto-delete) are raw CloudFormation, which Tags.of skips.

        They have no other tags to lose, so setting the whole property is safe.
        """
        for node in self.node.find_all():
            if type(node) is CfnResource and node.cfn_resource_type in ("AWS::IAM::Role", "AWS::Lambda::Function"):
                node.add_property_override("Tags", [{"Key": "project", "Value": "deals-watcher"}])

    def _github_deploy_role(self, github_repo: str) -> None:
        """Role for GitHub Actions in this repo's production environment. Reuses the account's OIDC provider."""
        if not re.fullmatch(r"[\w.-]+(@\d+)?/[\w.-]+(@\d+)?", github_repo):
            raise ValueError("githubRepo must be owner/repo or owner@id/repo@id")
        synthesizer = self.synthesizer
        qualifier = (
            synthesizer.bootstrap_qualifier if isinstance(synthesizer, DefaultStackSynthesizer) else None
        ) or DefaultStackSynthesizer.DEFAULT_QUALIFIER
        provider_arn = f"arn:{self.partition}:iam::{self.account}:oidc-provider/{GITHUB}"
        role = iam.Role(
            self,
            "GitHubDeployRole",
            description=f"GitHub Actions deploys from {github_repo} (production environment only)",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(  # pyright: ignore[reportArgumentType]
                provider_arn,
                conditions={
                    "StringEquals": {
                        f"{GITHUB}:aud": "sts.amazonaws.com",
                        f"{GITHUB}:sub": f"repo:{github_repo}:environment:production",
                    }
                },
            ),
        )
        # Deploys go through the CDK bootstrap roles.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:{self.partition}:iam::{self.account}:role/cdk-{qualifier}-*-{self.account}-{self.region}"],
            )
        )
        self.table.grant(role, "dynamodb:DescribeTable")  # smoke test
        NagSuppressions.add_resource_suppressions(
            role,
            [
                NagPackSuppression(
                    id="AwsSolutions-IAM5",
                    reason="Only sts:AssumeRole on this account's CDK bootstrap roles",
                    # Partition and account render as literals or tokens depending on flags and credentials.
                    applies_to=[RegexAppliesTo(regex=rf"/^Resource::arn:.+:iam::.+:role\/cdk-{qualifier}-\*-.+$/g")],
                )
            ],
            apply_to_children=True,
        )
        CfnOutput(self, "GitHubDeployRoleArn", value=role.role_arn)
