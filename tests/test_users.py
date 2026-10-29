"""Adding and removing people: the remove script only touches one user's data, and the pool stays invite-only."""

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from test_infra import _template  # noqa: PLC2701 - reuse the synthesized template (tests/ is on the import path)

spec = importlib.util.spec_from_file_location(
    "remove_user", Path(__file__).resolve().parent.parent / "scripts" / "remove_user.py"
)
assert spec and spec.loader
remove_user = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remove_user)


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        db = boto3.resource("dynamodb")
        db.create_table(
            TableName="t",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield db.Table("t")


def fill(table: Any, sub: str, count: int = 1) -> None:
    for kind in ("WATCH", "RULE", "DEAL", "PUSH"):
        for n in range(count):
            table.put_item(Item={"PK": f"USER#{sub}", "SK": f"{kind}#{n}", "title": f"{sub} {kind}"})
    table.put_item(Item={"PK": f"USER#{sub}", "SK": "PROFILE", "timeZone": "America/Chicago"})


def test_removing_a_user_deletes_all_of_their_items_and_nobody_elses(table: Any) -> None:
    fill(table, "alice", count=2)
    fill(table, "bob")
    fill(table, "alice-2")  # a user id that merely starts with the same letters must be untouched
    table.put_item(Item={"PK": "SHARED#x", "SK": "ITEM"})
    items = remove_user.user_items(table, "alice")
    assert remove_user.summary(items) == {"WATCH": 2, "RULE": 2, "DEAL": 2, "PUSH": 2, "PROFILE": 1}
    assert remove_user.purge(table, items) == 9
    assert remove_user.user_items(table, "alice") == []
    assert len(remove_user.user_items(table, "bob")) == 5 and len(remove_user.user_items(table, "alice-2")) == 5
    assert table.get_item(Key={"PK": "SHARED#x", "SK": "ITEM"}).get("Item")


def test_finding_a_users_items_follows_every_page_and_reads_consistently(table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fill(table, "alice", count=3)
    real = table.query
    calls: list[dict[str, Any]] = []

    def small_pages(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return real(Limit=2, **kwargs)

    monkeypatch.setattr(table, "query", small_pages)
    assert len(remove_user.user_items(table, "alice")) == 13 and len(calls) > 2
    assert all(call["ConsistentRead"] is True for call in calls)  # a just-written item must not be missed


def test_purging_a_user_with_no_data_is_fine(table: Any) -> None:
    assert remove_user.purge(table, remove_user.user_items(table, "nobody")) == 0


def test_disabling_turns_keyword_alerts_off_but_keeps_everything(table: Any) -> None:
    fill(table, "alice", count=2)
    table.update_item(
        Key={"PK": "USER#alice", "SK": "RULE#0"}, UpdateExpression="SET enabled = :on", ExpressionAttributeValues={":on": True}
    )
    table.put_item(Item={"PK": "USER#bob", "SK": "RULE#0", "enabled": True})
    assert remove_user.turn_off_alerts(table, remove_user.user_items(table, "alice")) == 2
    rules = [i for i in remove_user.user_items(table, "alice") if i["SK"].startswith("RULE#")]
    assert [r["enabled"] for r in rules] == [False, False] and len(remove_user.user_items(table, "alice")) == 9
    assert table.get_item(Key={"PK": "USER#bob", "SK": "RULE#0"})["Item"]["enabled"] is True


def test_a_user_id_is_recognised_for_cleaning_up_leftovers() -> None:
    assert remove_user.USER_ID.match("d10b3520-d0c1-70e2-009e-187a2db38e39")
    assert not remove_user.USER_ID.match("friend@example.com")


def test_the_pool_is_invite_only() -> None:
    pools = _template().find_resources("AWS::Cognito::UserPool")
    (pool,) = pools.values()
    assert pool["Properties"]["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True  # no self sign-up


def test_the_invitation_email_tells_a_new_person_what_to_do() -> None:
    (pool,) = _template().find_resources("AWS::Cognito::UserPool").values()
    invite = pool["Properties"]["AdminCreateUserConfig"]["InviteMessageTemplate"]
    text = json.dumps(invite["EmailMessage"])
    assert "{####}" in text and "{username}" in text  # Cognito fills in the temporary password and the email address
    assert (
        "Add to Home Screen" in text and "passkey" in text and "notifications" in text and "Fn::GetAtt" in text
    )  # the site address
    assert "invited" in invite["EmailSubject"]
