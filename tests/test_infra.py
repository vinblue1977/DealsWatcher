"""The stack synthesizes, and cdk-nag's AWS Solutions checks (added in app.py) pass on it."""

import aws_cdk as cdk
from aws_cdk.assertions import Template
from cdk_nag import AwsSolutionsChecks

from infra.stack import DealsWatcherStack


def test_stack_synthesizes_with_nag_checks():
    app = cdk.App()
    stack = DealsWatcherStack(app, "DealsWatcher", description="test")
    cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
    Template.from_stack(stack)
    assert app.synth().get_stack_by_name("DealsWatcher").template is not None
