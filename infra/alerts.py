"""Alerts for the owner: an SNS topic that emails them, and a crash alarm on the feed checker.

The address comes from the `ALERT_EMAIL` environment variable (a GitHub secret in CI) or the `alertEmail` CDK context. It is never
written to a file in this public repository, and error messages here never repeat it.
"""

import re

from aws_cdk import Duration
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from cdk_nag import NagPackSuppression, NagSuppressions
from constructs import Construct

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Alerts(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, checker: lambda_.IFunction, email: str | None) -> None:
        super().__init__(scope, construct_id)
        topic = sns.Topic(self, "Topic", display_name="DealsWatcher alerts", enforce_ssl=True)
        email = (email or "").strip()  # a secret pasted with a trailing newline must not break the deploy; blank means none
        if email:
            if not _EMAIL.fullmatch(email):
                raise ValueError("The alert email is not a valid address")  # never echo it: CI logs are public
            # AWS emails a confirmation link to this address; alerts start once it is clicked.
            topic.add_subscription(subscriptions.EmailSubscription(email))  # pyright: ignore[reportArgumentType]

        # The checker runs every 30 minutes and does not retry on its own (see Feeds), so each failed run is one error. Two failed
        # runs in a row (about an hour) is worth an email; a single blip is simply tried again at the next run.
        # It only sees runs that fail. A checker that stops being invoked at all is not caught (see the roadmap).
        alarm = cloudwatch.Alarm(
            self,
            "CheckerFailing",
            alarm_description="The DealsWatcher feed checker failed on two runs in a row. Look at its logs in CloudWatch.",
            metric=checker.metric_errors(period=Duration.minutes(30), statistic="Sum"),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        # Failure emails only: an "OK" email would also go out when the alarm is first created or replaced, for no incident.
        alarm.add_alarm_action(cw_actions.SnsAction(topic))  # pyright: ignore[reportArgumentType]

        NagSuppressions.add_resource_suppressions(
            topic,
            [
                NagPackSuppression(
                    id="AwsSolutions-SNS2",
                    reason="CloudWatch cannot publish to a topic encrypted with the AWS-managed key, and a customer key costs $1 "
                    "a month; the messages only name the alarm and carry no personal data",
                )
            ],
        )
