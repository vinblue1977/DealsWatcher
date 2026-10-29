"""Sending to a user's devices: expired subscriptions are removed, one failure doesn't stop the rest."""

from typing import Any

import boto3
import pytest
from moto import mock_aws

from push import notify as push


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("VAPID_SUBJECT", "https://example.com")
    with mock_aws():
        db = boto3.resource("dynamodb")
        db.create_table(
            TableName="t",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield db.Table("t")


def test_notify_sends_removes_gone_devices_and_survives_failures(monkeypatch: pytest.MonkeyPatch, table: Any) -> None:
    for name in ("ok", "gone", "broken"):
        table.put_item(Item={"PK": "USER#u", "SK": push.device_key(name), "subscription": {"endpoint": name}})
    delivered: list[str] = []

    def fake_send(subscription: dict, message: dict, key: str, subject: str) -> None:
        if subscription["endpoint"] == "gone":
            raise push.Gone
        if subscription["endpoint"] == "broken":
            raise RuntimeError("push service down")
        delivered.append(message["title"])

    monkeypatch.setattr(push, "send", fake_send)
    monkeypatch.setattr(push, "_private_key", lambda: "key")
    assert push.notify(table, "u", "Hi", "Body") == 1
    assert delivered == ["Hi"]
    assert {d["subscription"]["endpoint"] for d in push.devices(table, "u")} == {"ok", "broken"}


def test_private_key_is_read_once_from_ssm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("VAPID_KEY_PARAM", "/test/vapid")
    push._private_key.cache_clear()
    with mock_aws():
        boto3.client("ssm").put_parameter(Name="/test/vapid", Value="secret", Type="SecureString")
        assert push._private_key() == "secret"
    push._private_key.cache_clear()


def test_a_missing_signing_key_is_an_error_not_a_silent_zero(monkeypatch: pytest.MonkeyPatch, table: Any) -> None:
    def no_key() -> str:
        raise RuntimeError("parameter not found")

    monkeypatch.setattr(push, "_private_key", no_key)
    assert push.notify(table, "nobody", "Hi", "Body") == 0  # no devices: nothing to sign, so the key isn't read
    table.put_item(Item={"PK": "USER#u", "SK": push.device_key("a"), "subscription": {"endpoint": "a"}})
    with pytest.raises(RuntimeError, match="parameter not found"):
        push.notify(table, "u", "Hi", "Body")


def test_notify_can_target_one_device(table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(push, "send", lambda subscription, *a, **k: sent.append(subscription["endpoint"]))
    monkeypatch.setattr(push, "_private_key", lambda: "key")
    for name in ("a", "b"):
        endpoint = f"https://web.push.apple.com/{name}"
        table.put_item(
            Item={
                "PK": "USER#u",
                "SK": push.device_key(endpoint),
                "subscription": {"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}},
            }
        )
    assert push.notify(table, "u", "Hi", "Body", only=push.device_key("https://web.push.apple.com/b")) == 1
    assert sent == ["https://web.push.apple.com/b"]


def test_notify_only_reaches_nobody_when_that_device_is_gone(table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(push, "_private_key", lambda: "key")
    assert push.notify(table, "u", "Hi", "Body", only=push.device_key("https://web.push.apple.com/none")) == 0
