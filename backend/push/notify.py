"""Sends a notification to every device a user turned notifications on for (PUSH# items)."""

import functools
import hashlib
import logging
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from push.webpush import Gone, send

log = logging.getLogger(__name__)


def device_key(endpoint: str) -> str:
    return "PUSH#" + hashlib.sha256(endpoint.encode()).hexdigest()[:32]


@functools.cache
def _private_key() -> str:
    param = boto3.client("ssm").get_parameter(Name=os.environ["VAPID_KEY_PARAM"], WithDecryption=True)
    return param["Parameter"]["Value"]


def devices(table: Any, user: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(f"USER#{user}") & Key("SK").begins_with("PUSH#")}
    while True:
        page = table.query(**kwargs)
        found += page["Items"]
        if "LastEvaluatedKey" not in page:
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def notify(table: Any, user: str, title: str, body: str, url: str = "/", only: str | None = None) -> int:
    """Returns how many devices it reached; expired subscriptions are removed. `only`: one device's sort key (PUSH#...)."""
    sent = 0
    if only is None:
        mine = devices(table, user)
    else:  # one exact row, not a query over all devices
        row = table.get_item(Key={"PK": f"USER#{user}", "SK": only}).get("Item")
        mine = [row] if row else []
    if not mine:
        return 0
    key = _private_key()  # outside the loop: a missing or unreadable signing key must fail loudly, not look like "sent 0"
    for device in mine:
        try:
            send(device["subscription"], {"title": title, "body": body, "url": url}, key, os.environ["VAPID_SUBJECT"])
            sent += 1
        except Gone:
            table.delete_item(Key={"PK": device["PK"], "SK": device["SK"]})
        except Exception:  # one bad device must not stop the others
            log.exception("push failed")
    return sent
