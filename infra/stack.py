"""The DealsWatcher stack. Resources are added phase by phase (see ROADMAP.md); this skeleton only proves CI and synth."""

from aws_cdk import Stack
from constructs import Construct


class DealsWatcherStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
