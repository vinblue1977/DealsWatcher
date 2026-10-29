"""API Lambda: watches, keyword rules, deals feed and push devices, against a moto DynamoDB table."""

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from api import handler as api
from api import watches

USER = "user-1"
OTHER = "user-2"
GOOD_URL = "https://www.bestbuy.com/site/lg-c5-55-oled-tv/6584567.p"
OTHER_URL = "https://www.target.com/p/apple-airpods-pro-3/-/A-12345"
ENDPOINT = "https://web.push.apple.com/abc123"
SUBSCRIPTION = {"endpoint": ENDPOINT, "keys": {"p256dh": "key", "auth": "auth"}, "timeZone": "America/Chicago"}


@pytest.fixture(autouse=True)
def table(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        db = boto3.resource("dynamodb")
        db.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield db.Table("test-table")


def call(route: str, body: Any = None, user: str | None = USER, item_id: str = "", query: dict | None = None) -> tuple[int, Any]:
    event: dict[str, Any] = {"routeKey": route, "body": json.dumps(body) if body is not None else None}
    if user:
        event["requestContext"] = {"authorizer": {"jwt": {"claims": {"sub": user}}}}
    if item_id:
        event["pathParameters"] = {"id": item_id}
    if query:
        event["queryStringParameters"] = query
    response = api.handler(event, None)
    assert response["headers"]["Cache-Control"] == "no-store"
    return response["statusCode"], json.loads(response["body"])


def add_watch(**overrides: Any) -> dict[str, Any]:
    status, body = call("POST /me/watches", {"url": GOOD_URL, "targetPrice": 1100, **overrides})
    assert status == 201
    return body


def test_requires_a_signed_in_user_and_ignores_unknown_routes() -> None:
    assert call("GET /me/watches", user=None)[0] == 401
    assert call("GET /me/nothing") == (404, {"error": "not found"})


def test_create_and_list_watches() -> None:
    watch = add_watch(alertOnDrop=False)
    assert watch["retailer"] == "Best Buy" and watch["title"] == "Lg c5 55 oled tv" and watch["status"] == "pending"
    assert watch["targetPrice"] == 1100 and watch["alertOnDrop"] is False and watch["paused"] is False
    assert "PK" not in watch and len(watch["urlHash"]) == 32
    second = add_watch(url=OTHER_URL, title="  TV in the den  ")
    assert second["title"] == "TV in the den"
    status, body = call("GET /me/watches")
    assert status == 200 and [w["id"] for w in body["watches"]] == [second["id"], watch["id"]]  # newest first
    assert call("GET /me/watches", user=OTHER)[1] == {"watches": []}  # watches belong to their user


@pytest.mark.parametrize(
    "body",
    [
        {"url": "http://www.bestbuy.com/x", "targetPrice": 10},  # not https
        {"url": "https://evilbestbuy.com/x", "targetPrice": 10},  # look-alike host
        {"url": "https://user:pw" + "@" + "www.bestbuy.com/x", "targetPrice": 10},  # credentials in the link
        {"url": "https://www.newegg.com/x", "targetPrice": 10},  # not a supported store
        {"url": 5, "targetPrice": 10},
        {"url": GOOD_URL, "targetPrice": 0},
        {"url": GOOD_URL, "targetPrice": -5},
        {"url": GOOD_URL, "targetPrice": "abc"},
        {"url": GOOD_URL, "targetPrice": True},
        {"url": GOOD_URL, "targetPrice": 1e9},
        {"url": GOOD_URL, "targetPrice": 10, "title": ""},
        {"url": GOOD_URL, "targetPrice": 10, "title": 7},
    ],
)
def test_create_rejects_bad_input(body: dict) -> None:
    assert call("POST /me/watches", body)[0] == 400


def test_create_rejects_non_object_body_and_too_many_watches(monkeypatch: pytest.MonkeyPatch) -> None:
    assert call("POST /me/watches", [1])[0] == 400
    monkeypatch.setattr(watches, "MAX_WATCHES", 1)
    add_watch()
    assert call("POST /me/watches", {"url": OTHER_URL, "targetPrice": 5}) == (400, {"error": "up to 1 watches"})


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://www.target.com/p/apple-airpods-pro-3/-/A-94909922", "Apple airpods pro 3"),
        ("https://www.bestbuy.com/site/lg-c5-55-oled-tv/6578912.p?skuId=6578912", "Lg c5 55 oled tv"),
        ("https://www.walmart.com/ip/Nintendo-Switch-2-Bundle/123456789", "Nintendo Switch 2 Bundle"),
        ("https://www.costco.com/lg-c5-oled-tv.product.100123456.html", "Lg c5 oled tv"),
        ("https://www.target.com/p/-/A-94909922", "Product"),
    ],
)
def test_title_guess_skips_ids_and_file_endings(url: str, title: str) -> None:
    assert watches._title_from(url) == title  # noqa: SLF001


def test_title_falls_back_when_the_link_has_no_words() -> None:
    assert add_watch(url="https://www.target.com/")["title"] == "Product"
    assert watches.retailer_for("https://" + "a" * 1001 + ".bestbuy.com") is None


def test_get_update_and_delete_a_watch() -> None:
    watch = add_watch()
    wid = watch["id"]
    assert call("GET /me/watches/{id}", item_id=wid)[1]["url"] == GOOD_URL
    status, body = call(
        "PUT /me/watches/{id}", {"targetPrice": "999.50", "paused": True, "alertOnDrop": False, "title": "TV"}, item_id=wid
    )
    assert status == 200 and body["targetPrice"] == 999.5 and body["paused"] is True and body["title"] == "TV"
    assert call("GET /me/watches/{id}", item_id=wid)[1]["targetPrice"] == 999.5
    for bad in ({}, {"targetPrice": 0}, {"paused": "yes"}, {"title": ""}):
        assert call("PUT /me/watches/{id}", bad, item_id=wid)[0] == 400
    assert call("PUT /me/watches/{id}", [], item_id=wid)[0] == 400
    assert call("DELETE /me/watches/{id}", item_id=wid, user=OTHER)[0] == 404  # not theirs
    assert call("DELETE /me/watches/{id}", item_id=wid) == (200, {"deleted": wid})
    assert call("GET /me/watches/{id}", item_id=wid)[0] == 404


def test_unknown_or_malformed_watch_ids_are_404() -> None:
    assert call("GET /me/watches/{id}", item_id="../../x")[0] == 404
    assert call("GET /me/watches/{id}", item_id="0123456789ab")[0] == 404
    add_watch()
    assert call("PATCH /me/watches/{id}", item_id=call("GET /me/watches")[1]["watches"][0]["id"]) == (404, {"error": "not found"})


def test_keyword_rules_crud() -> None:
    status, rule = call("POST /me/rules", {"keyword": " OLED ", "maxPrice": 1200, "sources": ["reddit", "slickdeals", "reddit"]})
    assert (
        status == 201 and rule["keyword"] == "OLED" and rule["maxPrice"] == 1200 and rule["sources"] == ["reddit", "slickdeals"]
    )
    default = call("POST /me/rules", {"keyword": "Dyson"})[1]
    assert (
        default["maxPrice"] is None and default["enabled"] is True and default["sources"] == ["dealnews", "reddit", "slickdeals"]
    )
    assert [r["keyword"] for r in call("GET /me/rules")[1]["rules"]] == ["Dyson", "OLED"]
    status, body = call("PUT /me/rules/{id}", {"enabled": False, "maxPrice": None}, item_id=rule["id"])
    assert status == 200 and body["enabled"] is False and body["maxPrice"] is None and body["keyword"] == "OLED"
    assert call("PUT /me/rules/{id}", {"keyword": "TV"}, item_id=rule["id"])[1]["keyword"] == "TV"
    assert call("DELETE /me/rules/{id}", item_id=rule["id"], user=OTHER)[0] == 404
    assert call("DELETE /me/rules/{id}", item_id=rule["id"]) == (200, {"deleted": rule["id"]})
    assert call("PATCH /me/rules/{id}", item_id=default["id"]) == (404, {"error": "not found"})
    assert call("GET /me/rules/{id}", item_id="nope")[0] == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"keyword": ""},
        {"keyword": "x" * 61},
        {"keyword": 5},
        {"keyword": "ok", "maxPrice": -1},
        {"keyword": "ok", "sources": []},
        {"keyword": "ok", "sources": ["amazon"]},
        {"keyword": "ok", "enabled": "yes"},
    ],
)
def test_rules_reject_bad_input(body: dict) -> None:
    assert call("POST /me/rules", body)[0] == 400


def test_rule_update_validation_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import rules

    rule = call("POST /me/rules", {"keyword": "OLED"})[1]
    assert call("PUT /me/rules/{id}", {}, item_id=rule["id"])[0] == 400
    assert call("PUT /me/rules/{id}", {"sources": ["nope"]}, item_id=rule["id"])[0] == 400
    assert call("PUT /me/rules/{id}", [], item_id=rule["id"])[0] == 400
    assert call("POST /me/rules", [1])[0] == 400
    monkeypatch.setattr(rules, "MAX_RULES", 1)
    assert call("POST /me/rules", {"keyword": "two"}) == (400, {"error": "up to 1 keywords"})


def test_deals_feed_lists_the_users_deals_newest_first(table: Any) -> None:
    for sk in ("DEAL#2026-10-28T01#a", "DEAL#2026-10-28T09#b"):
        table.put_item(Item={"PK": f"USER#{USER}", "SK": sk, "title": sk})
    table.put_item(Item={"PK": f"USER#{OTHER}", "SK": "DEAL#2026-10-28T10#c", "title": "other"})
    assert [d["title"] for d in call("GET /me/deals")[1]["deals"]] == ["DEAL#2026-10-28T09#b", "DEAL#2026-10-28T01#a"]


def test_push_device_lifecycle(monkeypatch: pytest.MonkeyPatch, table: Any) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(api, "notify", lambda t, user, title, body, url="/": sent.append((user, title)) or 1)
    assert call("GET /me/push", query={"endpoint": ENDPOINT})[1] == {"devices": 0, "thisDevice": False}
    assert call("POST /me/push/test", {"endpoint": ENDPOINT})[0] == 404  # not turned on yet
    assert call("PUT /me/push", SUBSCRIPTION)[1] == {"devices": 1}
    assert table.get_item(Key={"PK": f"USER#{USER}", "SK": "PROFILE"})["Item"]["timeZone"] == "America/Chicago"
    assert call("GET /me/push", query={"endpoint": ENDPOINT})[1] == {"devices": 1, "thisDevice": True}
    assert call("POST /me/push/test", {"endpoint": ENDPOINT})[1] == {"sent": 1} and sent == [(USER, "DealsWatcher")]
    assert call("GET /me/push", user=OTHER, query={"endpoint": ENDPOINT})[1] == {"devices": 0, "thisDevice": False}
    assert call("DELETE /me/push", {"endpoint": ENDPOINT})[1] == {"devices": 0}


def test_push_rejects_bad_subscriptions() -> None:
    assert call("PUT /me/push", [1])[0] == 400
    assert call("PUT /me/push", {"endpoint": "https://evil.example/x", "keys": {"p256dh": "a", "auth": "b"}})[0] == 400
    assert call("PUT /me/push", {"endpoint": ENDPOINT})[0] == 400  # no keys
    assert call("PUT /me/push", {"endpoint": ENDPOINT, "keys": {"p256dh": "a", "auth": ""}})[0] == 400


def test_push_ignores_a_bad_time_zone(table: Any) -> None:
    assert call("PUT /me/push", {**SUBSCRIPTION, "timeZone": "Mars/Base"})[1] == {"devices": 1}
    assert "Item" not in table.get_item(Key={"PK": f"USER#{USER}", "SK": "PROFILE"})


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_prices_are_rejected_not_crashes(bad: str) -> None:
    raw = f'{{"url": "{GOOD_URL}", "targetPrice": {bad}}}'
    event = {"routeKey": "POST /me/watches", "body": raw, "requestContext": {"authorizer": {"jwt": {"claims": {"sub": USER}}}}}
    assert api.handler(event, None)["statusCode"] == 400
    watch = add_watch()
    assert call("PUT /me/watches/{id}", {"targetPrice": "NaN"}, item_id=watch["id"])[0] == 400


def test_updates_keep_fields_written_by_the_checker_and_cannot_resurrect_a_deleted_item(table: Any) -> None:
    watch = add_watch()
    key = {"PK": f"USER#{USER}", "SK": f"WATCH#{watch['id']}"}
    table.update_item(Key=key, UpdateExpression="SET lastPrice = :p", ExpressionAttributeValues={":p": 1234})
    body = call("PUT /me/watches/{id}", {"paused": True}, item_id=watch["id"])[1]
    assert body["paused"] is True and body["lastPrice"] == 1234
    table.delete_item(Key=key)
    from api.http import update_item

    assert update_item(table, key, {"paused": False}) is None
    assert "Item" not in table.get_item(Key=key)


def test_rule_update_of_a_vanished_rule_is_404(table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import rules

    rule = call("POST /me/rules", {"keyword": "OLED"})[1]
    monkeypatch.setattr(rules, "update_item", lambda *args: None)
    assert call("PUT /me/rules/{id}", {"enabled": False}, item_id=rule["id"]) == (404, {"error": "no such keyword"})
    monkeypatch.setattr(watches, "update_item", lambda *args: None)
    watch = add_watch()
    assert call("PUT /me/watches/{id}", {"paused": True}, item_id=watch["id"]) == (404, {"error": "no such watch"})


def test_ids_with_a_trailing_newline_are_not_valid() -> None:
    watch = add_watch()
    assert call("GET /me/watches/{id}", item_id=watch["id"] + "\n")[0] == 404


def test_deals_hide_internal_keys_and_return_at_most_100(table: Any) -> None:
    for i in range(105):
        table.put_item(Item={"PK": f"USER#{USER}", "SK": f"DEAL#{i:04d}", "title": str(i)})
    deals = call("GET /me/deals")[1]["deals"]
    assert len(deals) == 100 and deals[0] == {"title": "104"} and "PK" not in deals[0]


@pytest.mark.parametrize("zone", ["Europe", "../etc", "x" * 65, 5])  # a directory, a path, too long, not a string
def test_odd_time_zones_are_ignored_not_errors(zone: Any, table: Any) -> None:
    assert call("PUT /me/push", {**SUBSCRIPTION, "timeZone": zone})[1] == {"devices": 1}
    assert "Item" not in table.get_item(Key={"PK": f"USER#{USER}", "SK": "PROFILE"})


def test_a_user_can_turn_on_a_limited_number_of_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "MAX_DEVICES", 1)
    assert call("PUT /me/push", SUBSCRIPTION)[1] == {"devices": 1}
    assert call("PUT /me/push", SUBSCRIPTION)[1] == {"devices": 1}  # the same phone again is fine
    other = {**SUBSCRIPTION, "endpoint": "https://web.push.apple.com/another"}
    assert call("PUT /me/push", other) == (400, {"error": "up to 1 devices"})


def test_query_items_follows_pages() -> None:
    from api.http import query_items

    class Paged:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def query(self, **kwargs: Any) -> dict:
            self.calls.append(kwargs)
            if "ExclusiveStartKey" not in kwargs:
                return {"Items": [{"n": 1}], "LastEvaluatedKey": {"PK": "x", "SK": "y"}}
            return {"Items": [{"n": 2}]}

    table = Paged()
    assert query_items(table, USER, "WATCH#") == [{"n": 1}, {"n": 2}]
    assert table.calls[1]["ExclusiveStartKey"] == {"PK": "x", "SK": "y"}


@pytest.mark.parametrize("value", ["false", 0, None, "no"])
def test_alert_on_drop_must_be_a_real_boolean(value: Any) -> None:
    assert call("POST /me/watches", {"url": GOOD_URL, "targetPrice": 10, "alertOnDrop": value})[0] == 400


def test_the_same_link_cannot_be_watched_twice_but_another_user_can() -> None:
    add_watch()
    assert call("POST /me/watches", {"url": GOOD_URL, "targetPrice": 5}) == (400, {"error": "you are already watching this link"})
    assert call("POST /me/watches", {"url": GOOD_URL, "targetPrice": 5}, user=OTHER)[0] == 201


def test_devices_follow_pages() -> None:
    from push.notify import devices

    class Paged:
        def query(self, **kwargs: Any) -> dict:
            if "ExclusiveStartKey" not in kwargs:
                return {"Items": [{"SK": "PUSH#a"}], "LastEvaluatedKey": {"PK": "x", "SK": "y"}}
            return {"Items": [{"SK": "PUSH#b"}]}

    assert [d["SK"] for d in devices(Paged(), USER)] == ["PUSH#a", "PUSH#b"]


def test_oversized_bodies_are_refused_before_any_route_runs() -> None:
    event = {
        "routeKey": "POST /me/rules",
        "body": json.dumps({"keyword": "x" * 9000}),
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": USER}}}},
    }
    response = api.handler(event, None)
    assert response["statusCode"] == 413
    assert call("GET /me/rules") == (200, {"rules": []})
