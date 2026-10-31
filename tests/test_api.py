"""API Lambda: watches, keyword rules, deals feed and push devices, against a moto DynamoDB table."""

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from api import handler as api
from api import watches
from push.notify import device_key

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
        (
            "https://www.tennis-warehouse.com/Babolat_Pure_Drive_Tennis_Racquet/descpageRCBAB-BPD.html",
            "Babolat Pure Drive Tennis Racquet",
        ),
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
    status, rule = call("POST /me/rules", {"keyword": " OLED ", "maxPrice": 1200, "sources": ["dealnews", "dealnews"]})
    assert status == 201 and rule["keyword"] == "OLED" and rule["maxPrice"] == 1200 and rule["sources"] == ["dealnews"]
    default = call("POST /me/rules", {"keyword": "Dyson"})[1]
    assert default["maxPrice"] is None and default["enabled"] is True and default["sources"] == ["dealnews"]
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
        {"keyword": "ok", "sources": ["reddit"]},  # not read by the checker: refused instead of silently never firing
        {"keyword": "ok", "enabled": "yes"},
        {"keyword": "-mount"},  # only exclusions: nothing to look for
        {"keyword": '"Pro Max'},  # a quote never closed
        {"keyword": '""'},
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
    # newest by publish time, whatever their keys look like
    for sk, published in (("DEAL#zzz", "2026-10-28T01:00:00+00:00"), ("DEAL#aaa", "2026-10-28T09:00:00+00:00"), ("DEAL#mmm", "")):
        table.put_item(Item={"PK": f"USER#{USER}", "SK": sk, "title": sk, "publishedAt": published})
    table.put_item(Item={"PK": f"USER#{OTHER}", "SK": "DEAL#ccc", "title": "other", "publishedAt": "2026-10-28T10:00:00+00:00"})
    assert [d["title"] for d in call("GET /me/deals")[1]["deals"]] == ["DEAL#aaa", "DEAL#zzz", "DEAL#mmm"]
    assert call("GET /me/deals")[1]["deals"][0]["id"] == "DEAL#aaa"  # the app keys its cards on this


def test_push_device_lifecycle(monkeypatch: pytest.MonkeyPatch, table: Any) -> None:
    sent: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(api, "notify", lambda t, user, title, body, url="/", only=None: sent.append((user, title, only)) or 1)
    assert call("POST /me/push/status", {"endpoint": ENDPOINT})[1] == {"devices": 0, "thisDevice": False}
    assert call("POST /me/push/test", {"endpoint": ENDPOINT})[0] == 404  # not turned on yet
    assert call("PUT /me/push", SUBSCRIPTION)[1] == {"devices": 1}
    assert table.get_item(Key={"PK": f"USER#{USER}", "SK": "PROFILE"})["Item"]["timeZone"] == "America/Chicago"
    assert call("POST /me/push/status", {"endpoint": ENDPOINT})[1] == {"devices": 1, "thisDevice": True}
    assert call("POST /me/push/test", {"endpoint": ENDPOINT})[1] == {"sent": 1} and sent == [
        (USER, "DealsWatcher", device_key(ENDPOINT))
    ]
    assert call("POST /me/push/status", {"endpoint": ENDPOINT}, user=OTHER)[1] == {"devices": 0, "thisDevice": False}
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
        table.put_item(
            Item={
                "PK": f"USER#{USER}",
                "SK": f"DEAL#{i:04d}",
                "title": str(i),
                "publishedAt": f"2026-10-28T10:{i // 60:02d}:{i % 60:02d}+00:00",
            }
        )
    deals = call("GET /me/deals")[1]["deals"]
    assert len(deals) == 100 and deals[0] == {"title": "104", "id": "DEAL#0104", "publishedAt": "2026-10-28T10:01:44+00:00"}


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


def test_a_keyword_can_only_be_added_once_ignoring_case() -> None:
    assert call("POST /me/rules", {"keyword": "OLED"})[0] == 201
    assert call("POST /me/rules", {"keyword": " oled "}) == (400, {"error": "you already have this keyword"})
    assert call("POST /me/rules", {"keyword": "AirPods"})[0] == 201


def test_renaming_a_keyword_cannot_duplicate_another_but_can_change_its_own_case() -> None:
    oled = call("POST /me/rules", {"keyword": "OLED"})[1]
    pods = call("POST /me/rules", {"keyword": "AirPods"})[1]
    assert call("PUT /me/rules/{id}", {"keyword": "oled"}, item_id=pods["id"]) == (
        400,
        {"error": "you already have this keyword"},
    )
    assert call("PUT /me/rules/{id}", {"keyword": "Oled"}, item_id=oled["id"])[0] == 200


def test_the_size_cap_counts_bytes_and_survives_odd_unicode() -> None:
    auth = {"authorizer": {"jwt": {"claims": {"sub": USER}}}}
    four_byte = {"routeKey": "POST /me/rules", "body": "\U0001f600" * 3000, "requestContext": auth}  # 12 KB, only 3000 characters
    assert api.handler(four_byte, None)["statusCode"] == 413
    lone_surrogate = {"routeKey": "POST /me/rules", "body": "\ud800", "requestContext": auth}
    assert api.handler(lone_surrogate, None)["statusCode"] == 400  # reaches the route instead of crashing


def test_push_status_needs_a_known_push_service_endpoint_and_stays_out_of_urls() -> None:
    assert call("POST /me/push/status", {"endpoint": "https://evil.example/x"})[0] == 400
    assert call("POST /me/push/status", [1])[0] == 400
    assert call("GET /me/push", query={"endpoint": ENDPOINT})[0] == 404  # the old URL-based route is gone


def test_deals_hide_the_expiry_and_delivery_flag(table: Any) -> None:
    table.put_item(
        Item={"PK": f"USER#{USER}", "SK": "DEAL#2026-10-29T10:00:00Z#abc", "title": "t", "ttl": 1800000000, "pushed": True}
    )
    (deal,) = call("GET /me/deals")[1]["deals"]
    assert deal == {"title": "t", "id": "DEAL#2026-10-29T10:00:00Z#abc"}


def test_a_second_user_cannot_see_or_change_anything_of_the_first(table: Any) -> None:
    watch = add_watch()
    rule = call("POST /me/rules", {"keyword": "OLED"})[1]
    assert call("PUT /me/push", SUBSCRIPTION)[0] == 200
    table.put_item(Item={"PK": f"USER#{USER}", "SK": "DEAL#abc", "title": "mine", "publishedAt": "2026-10-28T10:00:00+00:00"})

    # lists
    assert call("GET /me/watches", user=OTHER)[1] == {"watches": []}
    assert call("GET /me/rules", user=OTHER)[1] == {"rules": []}
    assert call("GET /me/deals", user=OTHER)[1] == {"deals": []}
    assert call("POST /me/push/status", {"endpoint": ENDPOINT}, user=OTHER)[1] == {"devices": 0, "thisDevice": False}

    # by id: every way of reaching the first user's items answers "not found"
    for method, body in (("GET", None), ("PUT", {"title": "hijacked"}), ("DELETE", None)):
        assert call(f"{method} /me/watches/{{id}}", body, item_id=watch["id"], user=OTHER)[0] == 404
    for method, body in (("PUT", {"keyword": "hijacked"}), ("DELETE", None)):
        assert call(f"{method} /me/rules/{{id}}", body, item_id=rule["id"], user=OTHER)[0] == 404
    assert call("POST /me/push/test", {"endpoint": ENDPOINT}, user=OTHER)[0] == 404  # not theirs to alert
    call("DELETE /me/push", {"endpoint": ENDPOINT}, user=OTHER)  # removes nothing of the first user's

    # a request cannot name another account: extra fields are ignored, the token decides
    status, mine = call("POST /me/watches", {"url": OTHER_URL, "targetPrice": 5, "PK": f"USER#{USER}", "user": USER}, user=OTHER)
    assert status == 201 and [w["id"] for w in call("GET /me/watches", user=OTHER)[1]["watches"]] == [mine["id"]]

    # and the first user's data is exactly as it was
    assert [w["title"] for w in call("GET /me/watches")[1]["watches"]] == [watch["title"]]
    assert [r["keyword"] for r in call("GET /me/rules")[1]["rules"]] == ["OLED"]
    assert [d["title"] for d in call("GET /me/deals")[1]["deals"]] == ["mine"]
    assert call("POST /me/push/status", {"endpoint": ENDPOINT})[1] == {"devices": 1, "thisDevice": True}


def test_every_route_refuses_a_request_without_a_signed_in_user() -> None:
    for route in (
        "GET /me/watches",
        "POST /me/watches",
        "GET /me/rules",
        "GET /me/deals",
        "POST /me/push/status",
        "PUT /me/push",
    ):
        assert call(route, {}, user=None)[0] == 401


def test_quiet_hours_are_saved_read_and_cleared(table: Any) -> None:
    assert call("GET /me/settings")[1] == {"quietHours": None, "timeZone": None}
    status, body = call("PUT /me/settings", {"quietHours": {"start": 22, "end": 7}, "timeZone": "America/Chicago"})
    assert (status, body) == (200, {"quietHours": {"start": 22, "end": 7}, "timeZone": "America/Chicago"})
    assert call("GET /me/settings")[1] == body
    assert call("GET /me/settings", user=OTHER)[1] == {"quietHours": None, "timeZone": None}  # each user has their own
    assert call("PUT /me/settings", {"quietHours": None})[1] == {"quietHours": None, "timeZone": "America/Chicago"}
    item = table.get_item(Key={"PK": f"USER#{USER}", "SK": "PROFILE"})["Item"]
    assert "quietStart" not in item and "quietEnd" not in item


def test_quiet_hours_can_be_set_without_a_zone_and_a_bad_zone_is_ignored() -> None:
    assert call("PUT /me/settings", {"quietHours": {"start": 0, "end": 23}, "timeZone": "Mars/Base"})[1] == {
        "quietHours": {"start": 0, "end": 23},
        "timeZone": None,
    }


BAD_QUIET_HOURS = [
    {},
    {"quietHours": 5},
    {"quietHours": {"start": 22}},
    {"quietHours": {"start": 7, "end": 7}},
    {"quietHours": {"start": 24, "end": 1}},
    {"quietHours": {"start": -1, "end": 1}},
    {"quietHours": {"start": "22", "end": 7}},
    {"quietHours": {"start": True, "end": 7}},
    {"quietHours": {"start": 22.5, "end": 7}},
    [1],
]


@pytest.mark.parametrize("bad", BAD_QUIET_HOURS)
def test_bad_quiet_hours_are_rejected(bad: Any) -> None:
    assert call("PUT /me/settings", bad)[0] == 400
    assert call("GET /me/settings")[1]["quietHours"] is None


def test_settings_need_a_signed_in_user() -> None:
    assert call("GET /me/settings", user=None)[0] == 401


def test_keywords_may_use_exclusions_and_quoted_phrases() -> None:
    status, rule = call("POST /me/rules", {"keyword": ' TV -mount -"wall mount" '})
    assert status == 201 and rule["keyword"] == 'TV -mount -"wall mount"'
    assert call("PUT /me/rules/{id}", {"keyword": '"Pro Max" -case'}, item_id=rule["id"])[0] == 200
    assert call("PUT /me/rules/{id}", {"keyword": "-case"}, item_id=rule["id"])[0] == 400


def test_inch_marks_are_fine_and_a_reworded_duplicate_is_caught() -> None:
    assert call("POST /me/rules", {"keyword": '55" OLED'})[0] == 201
    assert call("POST /me/rules", {"keyword": "TV -mount"})[0] == 201
    assert call("POST /me/rules", {"keyword": "tv  -MOUNT"}) == (400, {"error": "you already have this keyword"})


def test_status_shows_when_the_checker_last_ran(table: Any) -> None:
    assert call("GET /me/status")[1] == {"checkedAt": None}
    table.put_item(
        Item={
            "PK": "CHECKER",
            "SK": "STATUS",
            "checkedAt": "2026-10-30T12:00:00+00:00",
            "feedsRead": 8,
            "feedsFailed": 0,
            "feedsSkipped": 0,
        }
    )
    assert call("GET /me/status")[1] == {
        "checkedAt": "2026-10-30T12:00:00+00:00",
        "feedsRead": 8,
        "feedsFailed": 0,
        "feedsSkipped": 0,
    }
    assert call("GET /me/status", user=OTHER)[1]["feedsRead"] == 8  # the same for everyone: it is about the checker, not a user
    assert call("GET /me/status", user=None)[0] == 401
