"""The feed checker: a Lambda that reads the Dealnews feeds every 30 minutes and alerts users whose keywords match."""

from aws_cdk import Duration
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from cdk_nag import NagPackSuppression, NagSuppressions, RegexAppliesTo
from constructs import Construct

from infra.push import grant_vapid


class Feeds(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITableV2,
        layer: lambda_.ILayerVersion,
        push_env: dict[str, str],
    ) -> None:
        super().__init__(scope, construct_id)
        self.checker = fn = lambda_.Function(
            self,
            "Checker",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            handler="feeds.handler.handler",
            code=lambda_.Code.from_asset("backend", exclude=["**/__pycache__"]),
            memory_size=256,
            timeout=Duration.seconds(90),  # no new feed starts after 40 s; the rest is the scan and pushes
            retry_attempts=0,  # the next scheduled run is 30 minutes away: no automatic retries, so one failed run is one error
            environment={"TABLE_NAME": table.table_name, **push_env},
            layers=[layer],
            log_group=logs.LogGroup(self, "Logs", retention=logs.RetentionDays.TWO_WEEKS),
        )
        # Only what it does: scan for everyone's keyword rules, save deals and mark them sent,
        # and (via the push sender) read and prune devices.
        table.grant(
            fn,
            "dynamodb:Scan",
            "dynamodb:Query",
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
        )
        grant_vapid(fn)
        # Overlapping runs are harmless: each deal is saved with a condition, so it is saved and alerted once.
        events.Rule(
            self,
            "Every30Minutes",
            schedule=events.Schedule.rate(Duration.minutes(30)),
            targets=[targets.LambdaFunction(fn, retry_attempts=1)],  # pyright: ignore[reportArgumentType]
        )
        NagSuppressions.add_resource_suppressions(
            fn,
            [
                NagPackSuppression(
                    id="AwsSolutions-IAM4",
                    reason="Basic execution role only writes this function's logs",
                    applies_to=["Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"],
                ),
                NagPackSuppression(
                    id="AwsSolutions-IAM5",
                    reason="CDK's table grant includes its indexes",
                    applies_to=[RegexAppliesTo(regex=r"/^Resource::<Table.+\.Arn>\/index\/\*$/g")],
                ),
            ],
            apply_to_children=True,
        )
