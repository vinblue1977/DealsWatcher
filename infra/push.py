"""Web Push signing key access, shared by the stack and the web construct."""

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_

VAPID_PARAM = "/deals-watcher/vapid-private-key"  # SecureString, created once outside CloudFormation


def grant_vapid(fn: lambda_.Function) -> None:
    """Read-only access to the Web Push signing key (SSM SecureString, AWS-managed key)."""
    stack = Stack.of(fn)
    fn.add_to_role_policy(
        iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[f"arn:{stack.partition}:ssm:{stack.region}:{stack.account}:parameter{VAPID_PARAM}"],
        )
    )
