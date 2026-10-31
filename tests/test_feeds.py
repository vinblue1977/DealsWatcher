"""Feed checker: parsing the Dealnews feed, keyword matching, and saving and alerting once per deal."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

import boto3
import pytest
from moto import mock_aws

from feeds import dealnews
from feeds import handler as feeds
from feeds.matching import matches
from push import notify as push

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def item(
    n: str = "1",
    title: str = "LG C5 OLED TV for $1,099 + free shipping",
    price: str | None = "1099.00",
    minutes_ago: int = 30,
    **extra: str,
) -> str:
    fields = {
        "title": title,
        "link": f"https://www.dealnews.com/deal-{n}",
        "guid": f"https://www.dealnews.com/{n}.html?iref=rss",
        "pubDate": format_datetime(NOW - timedelta(minutes=minutes_ago)),
        "retailer": "Best Buy",
        "category": "TVs",
        **({"price": price} if price is not None else {}),
        **extra,
    }
    tags = {("dn:" + k if k in ("retailer", "category", "price") else k): v for k, v in fields.items()}  # the feed's own fields
    return "<item>" + "".join(f"<{k}>{escape(v)}</{k}>" for k, v in tags.items()) + "</item>"


def feed(*items: str) -> bytes:
    namespaces = 'xmlns:dn="https://www.dealnews.com/ns/rss/1.0.htm" xmlns:media="http://search.yahoo.com/mrss/"'
    return f'<?xml version="1.0"?><rss version="2.0" {namespaces}><channel>{"".join(items)}</channel></rss>'.encode()


class TestParse:
    def test_reads_deals(self) -> None:
        (deal,) = dealnews.parse(feed(item()))
        assert deal["title"].startswith("LG C5 OLED") and deal["price"] == Decimal("1099.00")
        assert deal["retailer"] == "Best Buy" and deal["category"] == "TVs" and deal["published"] == NOW - timedelta(minutes=30)
        assert len(deal["id"]) == 12 and deal["url"] == "https://www.dealnews.com/deal-1"

    def test_prices_are_optional_and_must_look_like_prices(self) -> None:
        deals = dealnews.parse(
            feed(
                item("1", price=None),
                item("2", price="free"),
                item("3", price="0"),
                item("4", price="-5"),
                item("5", price="199.2"),
            )
        )
        assert [d["price"] for d in deals] == [None, None, None, None, Decimal("199.2")]

    def test_skips_incomplete_items_and_links_to_other_sites(self) -> None:
        bad = [
            item("1", title=""),
            item("2", pubDate="not a date"),
            item("3", link="https://evil.example/deal"),
            item("4", link="http://www.dealnews.com/deal"),
            item("5", link=f"https://user:pw{'@'}www.dealnews.com/deal"),  # credentials in the link
            item("6", link="https://dealnews.com.evil.example/deal"),
            item("7", guid=""),
        ]
        assert dealnews.parse(feed(*bad, item("8"))) == dealnews.parse(feed(item("8")))
        assert len(dealnews.parse(feed(*bad, item("8")))) == 1

    def test_refuses_xml_with_entities(self) -> None:
        body = b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'  # noqa: E501
        with pytest.raises(ValueError, match="refuse"):
            dealnews.parse(body)

    def test_long_titles_are_cut_and_other_namespaces_cannot_overwrite_fields(self) -> None:
        extra = (
            '<media:title>Other</media:title><media:category>Other</media:category><media:content url="https://x.example/i.jpg"/>'
        )
        (deal,) = dealnews.parse(feed(item(title="x" * 500).replace("</item>", extra + "</item>")))
        assert len(deal["title"]) == 300 and deal["category"] == "TVs" and deal["url"] == "https://www.dealnews.com/deal-1"

    def test_refuses_utf16_so_a_hidden_doctype_cannot_slip_past(self) -> None:
        wide = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel/></rss>'.encode("utf-16")
        for body in (wide, b"\xff\xfe<rss/>", b"<rss>\x00</rss>"):
            with pytest.raises(ValueError, match="refuse"):
                dealnews.parse(body)

    def test_age_limit_drops_old_and_future_deals(self) -> None:
        deals = dealnews.parse(feed(item("1", minutes_ago=30), item("2", minutes_ago=60 * 7), item("3", minutes_ago=-10)))
        assert [d["url"][-1] for d in dealnews.age_limit(NOW, deals, 6)] == ["1"]


def xml_headers(content_type: str = "text/xml; charset=utf-8") -> Message:
    headers = Message()
    headers["Content-Type"] = content_type
    return headers


class TestFetch:
    def test_returns_the_body_and_identifies_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = {}

        class Response:
            headers = xml_headers()

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                return b"x" * min(limit, 10)

        def open_(request: Any, timeout: int) -> Response:
            seen["ua"], seen["url"], seen["timeout"] = request.get_header("User-agent"), request.full_url, timeout
            seen["accept"] = request.get_header("Accept")
            return Response()

        monkeypatch.setattr(dealnews._OPENER, "open", open_)  # noqa: SLF001
        for url in dealnews.FEEDS:
            assert dealnews.fetch(url) == b"x" * 10
            assert seen["ua"].startswith("DealsWatcher/1.0") and seen["url"] == url and seen["timeout"] == 10
            accept = [part.split(";")[0].strip() for part in seen["accept"].split(",")]
            assert accept[:2] == ["application/rss+xml", "application/xml"] and accept[-1] == "*/*"  # no */* and it answers 406
        assert dealnews.FEEDS == (
            "https://www.dealnews.com/?rss=1",
            "https://www.dealnews.com/f1676/Black-Friday/?rss=1",
            "https://www.dealnews.com/?rss=1&sort=hotness",
            "https://www.dealnews.com/f1682/Staff-Pick/?rss=1",
            "https://www.dealnews.com/c142/Electronics/?rss=1",
            "https://www.dealnews.com/c39/Computers/?rss=1",
            "https://www.dealnews.com/c202/Clothing-Accessories/?rss=1",
            "https://www.dealnews.com/c196/Home-Garden/?rss=1",
        )
        assert len(set(dealnews.FEEDS)) == len(dealnews.FEEDS)
        assert dealnews.REQUIRED == (dealnews.MAIN_FEED,)  # the seven extras may fail without turning the checker red

    def test_only_the_listed_feeds_can_be_fetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dealnews._OPENER, "open", lambda *a, **k: pytest.fail("must not make a request"))  # noqa: SLF001
        for url in ("https://evil.example/feed", "http://www.dealnews.com/?rss=1", "https://www.dealnews.com/?rss=2", ""):
            with pytest.raises(ValueError, match="not a known feed"):
                dealnews.fetch(url)

    def test_refuses_a_page_that_is_not_xml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Page:
            headers = xml_headers("text/html; charset=UTF-8")

            def __enter__(self) -> Page:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                pytest.fail("the body of a non-XML answer must not be read")

        monkeypatch.setattr(dealnews._OPENER, "open", lambda *a, **k: Page())  # noqa: SLF001
        with pytest.raises(ValueError, match="not XML"):
            dealnews.fetch(dealnews.MAIN_FEED)

    def test_refuses_an_oversized_feed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Big:
            headers = xml_headers()

            def __enter__(self) -> Big:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                return b"x" * limit

        monkeypatch.setattr(dealnews._OPENER, "open", lambda *a, **k: Big())  # noqa: SLF001
        with pytest.raises(ValueError, match="larger"):
            dealnews.fetch(dealnews.FEEDS[0])

    def test_redirects_are_not_followed(self) -> None:
        assert dealnews._NoRedirects().redirect_request() is None  # noqa: SLF001


DEAL = {"title": "Apple AirPods Pro 3 for $199", "price": Decimal("199"), "retailer": "Amazon", "category": "Headphones"}


def rule(**over: Any) -> dict[str, Any]:
    return {"keyword": "AirPods", "maxPrice": None, "sources": ["dealnews"], "enabled": True, **over}


class TestMatching:
    @pytest.mark.parametrize(
        ("keyword", "expected"),
        [
            ("airpods", True),
            ("AirPods Pro", True),
            ("pro 3", True),
            ("amazon", True),
            ("headphone", True),
            ("pod", False),
            ("TV", False),
            ("Pro 33", False),
        ],
    )
    def test_whole_words_in_title_store_or_category(self, keyword: str, expected: bool) -> None:
        assert matches(rule(keyword=keyword), DEAL, "dealnews") is expected

    def test_es_plurals_match_too(self) -> None:
        assert matches(rule(keyword="box"), {**DEAL, "title": "Storage Boxes for $20"}, "dealnews")
        assert not matches(rule(keyword="box"), {**DEAL, "title": "Boxer shorts"}, "dealnews")

    def test_keywords_with_symbols_are_taken_literally(self) -> None:
        assert not matches(rule(keyword="A.*"), DEAL, "dealnews")
        assert matches(rule(keyword="$199"), {**DEAL, "title": "Sale $199 today"}, "dealnews")

    def test_price_ceiling_needs_a_known_price(self) -> None:
        assert matches(rule(maxPrice=Decimal("200")), DEAL, "dealnews")
        assert matches(rule(maxPrice=Decimal("199")), DEAL, "dealnews")
        assert not matches(rule(maxPrice=Decimal("150")), DEAL, "dealnews")
        assert not matches(rule(maxPrice=Decimal("200")), {**DEAL, "price": None}, "dealnews")
        assert matches(rule(), {**DEAL, "price": None}, "dealnews")

    def test_rule_must_be_on_and_listen_to_the_source(self) -> None:
        assert not matches(rule(enabled=False), DEAL, "dealnews")
        assert not matches(rule(sources=["reddit"]), DEAL, "dealnews")


USER, OTHER = "user-1", "user-2"


class FakeClock:
    """Stands in for the handler's `time` module only (not the real one): pauses are recorded, not slept, and each pause
    moves the clock on."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(feeds, "time", fake)
    return fake


@pytest.fixture
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


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str]]:
    sent: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        feeds, "notify", lambda table, user, title, body, url="/", **kw: sent.append((user, title, body, url)) or 1
    )
    return sent


def add_rule(table: Any, user: str = USER, rid: str = "r1", **over: Any) -> None:
    table.put_item(
        Item={"PK": f"USER#{user}", "SK": f"RULE#{rid}", "id": rid, "createdAt": f"2026-10-01T00:00:{rid[-1]}Z", **rule(**over)}
    )


def run(
    monkeypatch: pytest.MonkeyPatch,
    *items: str,
    black_friday: tuple[str, ...] = (),
    extra: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, int]:
    """One checker run. `extra` gives the items of other feeds by address; every feed not given is empty."""
    bodies = {url: feed() for url in dealnews.FEEDS}
    bodies |= {dealnews.MAIN_FEED: feed(*items), dealnews.BLACK_FRIDAY_FEED: feed(*black_friday)}
    bodies |= {url: feed(*listed) for url, listed in (extra or {}).items()}
    monkeypatch.setattr(feeds.dealnews, "fetch", lambda url: bodies[url])
    monkeypatch.setattr(feeds, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))
    return feeds.handler({}, None)


def deals_of(table: Any, user: str = USER) -> list[dict[str, Any]]:
    return [i for i in table.scan()["Items"] if i["PK"] == f"USER#{user}" and i["SK"].startswith("DEAL#")]


class TestHandler:
    def test_logs_a_summary_of_counts_and_nothing_identifying(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert feeds.log.level == logging.INFO  # Lambda's logger starts at WARNING: without this the summary never shows
        add_rule(table, keyword="OLED")
        run(monkeypatch, item("1"), item("2", title="A toaster for $20"), black_friday=(item("3", minutes_ago=60 * 24),))
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="feeds.handler"):
            run(monkeypatch, item("1"), item("2", title="A toaster for $20"), black_friday=(item("3", minutes_ago=60 * 24),))
        lines = [r.getMessage() for r in caplog.records]
        assert f"feeds: {len(dealnews.FEEDS)} read, 0 failed, 0 skipped" in lines
        assert (
            "deals: 3 read, 2 recent, 1 matched (0 new, 1 already sent), 0 pushed, 0 failed" in lines
        )  # the second run: all sent
        text = " ".join(lines).lower()
        assert not any(word in text for word in ("oled", "toaster", "dealnews", "http", USER, "best buy"))

    def test_feeds_skipped_for_time_are_counted_as_skipped_not_read(
        self, table: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, clock: FakeClock
    ) -> None:
        def slow(url: str) -> bytes:
            clock.now += feeds.READ_BUDGET_SECONDS
            return feed()

        monkeypatch.setattr(feeds.dealnews, "fetch", slow)
        monkeypatch.setattr(feeds, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))
        with caplog.at_level(logging.INFO, logger="feeds.handler"):
            feeds.handler({}, None)
        assert f"feeds: 2 read, 0 failed, {len(dealnews.FEEDS) - 2} skipped" in [r.getMessage() for r in caplog.records]

    def test_saves_a_matching_deal_and_alerts_once(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="OLED")
        assert run(monkeypatch, item("1"), item("2", title="Dyson Vacuum for $300")) == {"deals": 2, "saved": 1, "pushed": 1}
        (saved,) = deals_of(table)
        assert saved["title"].startswith("LG C5") and saved["keyword"] == "OLED" and saved["source"] == "dealnews"
        assert (
            saved["price"] == Decimal("1099.00")
            and saved["retailer"] == "Best Buy"
            and saved["SK"].startswith("DEAL#")
            and len(saved["SK"]) == len("DEAL#") + 12
        )
        assert saved["ttl"] > int(NOW.timestamp()) and saved["url"] == "https://www.dealnews.com/deal-1"
        assert saved["pushed"] is True and saved["publishedAt"] == "2026-10-29T11:30:00+00:00" and "seenAt" not in saved
        assert pushes == [(USER, "New deal: OLED", saved["title"], "/#/deals")]

    def test_running_again_does_not_repeat_the_alert(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="OLED")
        run(monkeypatch, item("1"))
        assert run(monkeypatch, item("1"))["saved"] == 0
        assert len(pushes) == 1 and len(deals_of(table)) == 1

    def test_each_user_gets_only_their_own_matches(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, USER, keyword="OLED")
        add_rule(table, OTHER, keyword="vacuum", maxPrice=Decimal("100"))
        run(monkeypatch, item("1"), item("2", title="Dyson vacuum for $300", price="300"))
        assert len(deals_of(table, USER)) == 1 and deals_of(table, OTHER) == []
        assert [p[0] for p in pushes] == [USER]

    def test_one_deal_matching_two_rules_is_saved_once(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, rid="r2", keyword="LG")
        add_rule(table, rid="r1", keyword="OLED")  # older: always the one that names the deal
        assert run(monkeypatch, item("1"))["saved"] == 1 and len(pushes) == 1
        assert deals_of(table)[0]["keyword"] == "OLED" and pushes[0][1] == "New deal: OLED"

    def test_turned_off_rules_other_sources_and_old_deals_are_ignored(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, rid="off", keyword="OLED", enabled=False)
        add_rule(table, rid="reddit", keyword="OLED", sources=["reddit"])
        add_rule(table, rid="on", keyword="Dyson")
        assert run(monkeypatch, item("1"), item("2", title="Dyson Vacuum", minutes_ago=60 * 8))["saved"] == 0
        assert pushes == [] and deals_of(table) == []

    def test_a_deal_without_a_price_is_saved_without_one(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="sale")
        run(monkeypatch, item("1", title="Jomashop Pre-Holiday Sale: Up to 75% off", price=None))
        (saved,) = deals_of(table)
        assert "price" not in saved

    def test_pushes_are_capped_per_run_and_the_rest_go_out_on_the_next_run(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="TV")
        monkeypatch.setattr(feeds, "MAX_PUSHES", 2)
        items = [item(str(i), title=f"TV number {i}", minutes_ago=i + 1) for i in range(4)]
        assert run(monkeypatch, *items)["saved"] == 4 and len(pushes) == 2
        assert run(monkeypatch, *items) == {"deals": 4, "saved": 0, "pushed": 2}  # the two left over, none repeated
        assert len(pushes) == 4 and len({p[2] for p in pushes}) == 4
        assert run(monkeypatch, *items)["pushed"] == 0

    def test_a_failed_push_is_reported_retried_and_does_not_stop_others(
        self, table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, USER, keyword="OLED")
        add_rule(table, OTHER, keyword="OLED")
        calls: list[str] = []
        down = {"on": True}

        def flaky(table: Any, user: str, title: str, body: str, url: str = "/", **kw: Any) -> int:
            calls.append(user)
            if user == USER and down["on"]:
                raise RuntimeError("push service down")
            return 1

        monkeypatch.setattr(feeds, "notify", flaky)
        with pytest.raises(RuntimeError, match="1 deal alerts failed; feeds down: none"):
            run(monkeypatch, item("1"))
        assert sorted(calls) == [USER, OTHER] and len(deals_of(table, USER)) == 1
        assert deals_of(table, USER)[0]["pushed"] is False and deals_of(table, OTHER)[0]["pushed"] is True
        down["on"] = False
        assert run(monkeypatch, item("1")) == {"deals": 1, "saved": 0, "pushed": 1}  # the missed alert goes out now
        assert deals_of(table, USER)[0]["pushed"] is True
        assert run(monkeypatch, item("1"))["pushed"] == 0

    def test_a_failing_push_still_counts_toward_the_cap(self, table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="TV")
        monkeypatch.setattr(feeds, "MAX_PUSHES", 2)
        calls: list[str] = []
        monkeypatch.setattr(feeds, "notify", lambda *a, **k: calls.append("x") or (_ for _ in ()).throw(RuntimeError("down")))
        with pytest.raises(RuntimeError, match="2 deal alerts failed; feeds down: none"):
            run(monkeypatch, *(item(str(i), title=f"TV number {i}", minutes_ago=i + 1) for i in range(5)))
        assert len(calls) == 2

    def test_a_broken_rule_does_not_stop_the_run(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        table.put_item(Item={"PK": f"USER#{USER}", "SK": "RULE#bad1", "enabled": True, "sources": ["dealnews"]})  # no keyword
        table.put_item(Item={"PK": f"USER#{USER}", "SK": "RULE#bad2", "enabled": True, "keyword": " ", "sources": ["dealnews"]})
        table.put_item(Item={"PK": f"USER#{USER}", "SK": "RULE#bad3", "enabled": True, "keyword": "OLED", "sources": "dealnews"})
        add_rule(table, OTHER, keyword="OLED")
        assert run(monkeypatch, item("1"))["saved"] == 1 and [p[0] for p in pushes] == [OTHER]

    def test_finds_rules_across_scan_pages(self, table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        for n in range(3):
            add_rule(table, rid=f"r{n}", keyword=f"k{n}")
        real = table.scan
        pages = []

        def paged(**kwargs: Any) -> dict[str, Any]:
            kwargs["Limit"] = 1  # a tiny page size forces following LastEvaluatedKey
            pages.append(1)
            return real(**kwargs)

        monkeypatch.setattr(table, "scan", paged)
        rules = feeds._rules_by_user(table)  # noqa: SLF001
        assert sorted(r["keyword"] for r in rules[USER]) == ["k0", "k1", "k2"] and len(pages) > 1

    def test_a_feed_failure_is_an_error_not_a_silent_success(self, table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        def down(url: str) -> bytes:
            raise OSError("feed down")

        monkeypatch.setattr(feeds.dealnews, "fetch", down)
        with pytest.raises(OSError, match="feed down"):
            feeds.handler({}, None)


class TestDelivery:
    def test_a_deal_whose_publish_time_changes_is_still_the_same_deal(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        run(monkeypatch, item("1", minutes_ago=30))
        assert run(monkeypatch, item("1", minutes_ago=5))["saved"] == 0  # same guid, newer pubDate
        assert len(pushes) == 1 and len(deals_of(table)) == 1


class TestNotifyStrict:
    @pytest.fixture
    def devices(self, table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAPID_SUBJECT", "https://example.com")
        monkeypatch.setattr(push, "_private_key", lambda: "key")
        for name in ("a", "b"):
            endpoint = f"https://web.push.apple.com/{name}"
            sub = {"endpoint": endpoint}
            table.put_item(Item={"PK": f"USER#{USER}", "SK": push.device_key(endpoint), "subscription": sub})

    def test_raises_when_every_device_send_fails_so_the_alert_can_be_retried(
        self, table: Any, devices: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def down(*args: Any, **kwargs: Any) -> None:
            raise OSError("push service down")

        monkeypatch.setattr(push, "send", down)
        assert push.notify(table, USER, "t", "b") == 0  # the default stays quiet
        with pytest.raises(RuntimeError, match="every device"):
            push.notify(table, USER, "t", "b", strict=True)

    def test_one_working_device_or_only_expired_ones_is_not_a_failure(
        self, table: Any, devices: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def one_works(subscription: dict, *args: Any, **kwargs: Any) -> None:
            if subscription["endpoint"].endswith("/a"):
                raise OSError("down")

        monkeypatch.setattr(push, "send", one_works)
        assert push.notify(table, USER, "t", "b", strict=True) == 1

        def gone(*args: Any, **kwargs: Any) -> None:
            raise push.Gone

        monkeypatch.setattr(push, "send", gone)
        assert push.notify(table, USER, "t", "b", strict=True) == 0  # expired devices were just removed: nothing to retry


class TestBlackFridayFeed:
    @staticmethod
    def sale(n: str = "9", title: str = "Carhartt Black Friday Deals: Up to 50% off + free shipping", **extra: str) -> str:
        return item(n, title=title, price=None, retailer="Carhartt", category="Clothing & Accessories", **extra)

    def test_a_store_sale_matches_a_store_keyword_and_is_saved_without_a_price(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="Carhartt")
        assert run(monkeypatch, black_friday=(self.sale(),)) == {"deals": 1, "saved": 1, "pushed": 1}
        (saved,) = deals_of(table)
        assert "price" not in saved and saved["retailer"] == "Carhartt" and saved["keyword"] == "Carhartt"
        assert pushes[0][1] == "New deal: Carhartt" and "Black Friday" in pushes[0][2]

    def test_a_black_friday_keyword_catches_every_sale_and_a_price_ceiling_catches_none(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, USER, keyword="Black Friday")
        add_rule(table, OTHER, keyword="Black Friday", maxPrice=Decimal("100"))  # sales have no price to compare
        run(monkeypatch, black_friday=(self.sale("1"), self.sale("2", title="Best Buy Black Friday Sale")))
        assert len(deals_of(table, USER)) == 2 and deals_of(table, OTHER) == []

    def test_a_deal_in_both_feeds_counts_once(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="OLED")
        assert run(monkeypatch, item("1"), black_friday=(item("1"), item("2", title="OLED sale")))["saved"] == 2
        assert len(pushes) == 2 and len(deals_of(table)) == 2

    @staticmethod
    def one_feed_down(monkeypatch: pytest.MonkeyPatch, down: str) -> None:
        def fetch(url: str) -> bytes:
            if url == down:
                raise OSError("feed down")
            return feed(item("1"))

        monkeypatch.setattr(feeds.dealnews, "fetch", fetch)
        monkeypatch.setattr(feeds, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))

    def test_the_seasonal_feed_going_away_is_not_an_error(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        self.one_feed_down(monkeypatch, dealnews.BLACK_FRIDAY_FEED)
        assert feeds.handler({}, None) == {"deals": 1, "saved": 1, "pushed": 1}  # after the season the feed may 404: stay green

    def test_a_deal_only_an_extra_feed_lists_is_alerted(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="OLED")
        extra = {dealnews.COMPUTERS_FEED: (item("7", title="OLED monitor"),)}
        assert run(monkeypatch, extra=extra) == {"deals": 1, "saved": 1, "pushed": 1}

    def test_a_copy_without_a_price_does_not_hide_the_priced_one(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED", maxPrice=Decimal(1200))
        sale = item("1", price=None)  # the Black Friday feed lists it with no price...
        priced = item("1", price="999.00")  # ...the Electronics feed with one, under the limit
        assert run(monkeypatch, black_friday=(sale,), extra={dealnews.ELECTRONICS_FEED: (priced,)})["saved"] == 1
        assert len(pushes) == 1

    def test_every_extra_feed_going_away_is_not_an_error(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="OLED")
        for extra in dealnews.FEEDS[1:]:
            self.one_feed_down(monkeypatch, extra)
            assert feeds.handler({}, None)["deals"] == 1  # none of them turns the checker red

    def test_requests_are_spaced_out(self, table: Any, monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
        run(monkeypatch)
        assert clock.sleeps == [feeds.PAUSE_SECONDS] * (len(dealnews.FEEDS) - 1)  # a pause between feeds, none before the first

    def test_a_slow_host_cannot_use_up_the_run(self, table: Any, monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
        asked: list[str] = []

        def slow(url: str) -> bytes:
            asked.append(url)
            clock.now += feeds.READ_BUDGET_SECONDS  # every feed takes the whole budget
            return feed()

        monkeypatch.setattr(feeds.dealnews, "fetch", slow)
        monkeypatch.setattr(feeds, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))
        feeds.handler({}, None)
        assert asked == list(dealnews.FEEDS[:2])  # the main feed, then one more; the rest are skipped, and that is not an error

    def test_the_main_feed_down_still_alerts_from_the_other_and_is_reported(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        self.one_feed_down(monkeypatch, dealnews.MAIN_FEED)
        with pytest.raises(RuntimeError, match=r"0 deal alerts failed; feeds down: https://www.dealnews.com/\?rss=1"):
            feeds.handler({}, None)
        assert len(pushes) == 1 and len(deals_of(table)) == 1  # the working feed was still processed

    def test_every_feed_down_raises_the_first_error(self, table: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        errors = iter([OSError("main down"), *(OSError("an extra feed down") for _ in dealnews.FEEDS[1:])])

        def fetch(url: str) -> bytes:
            raise next(errors)

        monkeypatch.setattr(feeds.dealnews, "fetch", fetch)
        with pytest.raises(OSError, match="main down"):
            feeds.handler({}, None)

    def test_the_same_deal_tagged_differently_by_each_feed_counts_once(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        main = item("1")  # guid ...?iref=rss
        black_friday = main.replace("iref=rss", "iref=rss-f1676")  # what the real Black Friday feed does
        assert main != black_friday and run(monkeypatch, main, black_friday=(black_friday,))["saved"] == 1
        assert len(pushes) == 1 and len(deals_of(table)) == 1

    def test_old_sales_do_not_alert(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="Carhartt")
        assert run(monkeypatch, black_friday=(self.sale(minutes_ago=60 * 24 * 7),))["saved"] == 0  # posted a week ago
        assert pushes == []


class TestQuietHours:
    """NOW is 07:00 in Chicago (daylight time, UTC-5) and 12:00 UTC."""

    def profile(self, table: Any, start: int | None, end: int | None, zone: str | None = "America/Chicago") -> None:
        values = {"quietStart": start, "quietEnd": end, "timeZone": zone}
        table.put_item(Item={"PK": f"USER#{USER}", "SK": "PROFILE", **{k: v for k, v in values.items() if v is not None}})

    @pytest.mark.parametrize(
        ("start", "end", "zone", "quiet"),
        [
            (22, 8, "America/Chicago", True),  # 07:00 is inside 22:00-08:00 (crosses midnight)
            (22, 7, "America/Chicago", False),  # the window ends at 07:00 sharp
            (6, 8, "America/Chicago", True),  # a window inside one day
            (8, 22, "America/Chicago", False),
            (22, 8, "UTC", False),  # 12:00 UTC: the user's own zone decides
            (22, 8, None, False),  # no zone known: never hold alerts
            (None, None, "America/Chicago", False),
        ],
    )
    def test_the_window_is_read_in_the_users_time_zone(
        self, table: Any, start: int | None, end: int | None, zone: str | None, quiet: bool
    ) -> None:
        self.profile(table, start, end, zone)
        assert feeds._is_quiet(table, USER, NOW) is quiet

    def test_alerts_wait_for_the_window_to_end_even_past_the_six_hour_limit(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        self.profile(table, 22, 8)
        assert run(monkeypatch, item("1"))["pushed"] == 0 and pushes == []
        assert len(deals_of(table)) == 1 and deals_of(table)[0]["pushed"] is False  # saved, so the Deals list still shows it
        assert run(monkeypatch, item("1"))["pushed"] == 0  # still quiet
        self.profile(table, 22, 7)  # the window has ended
        assert run(monkeypatch)["pushed"] == 1 and len(pushes) == 1  # the deal has left the feed: it still goes out
        assert run(monkeypatch)["pushed"] == 0

    def test_held_alerts_share_the_per_run_cap(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, keyword="TV")
        monkeypatch.setattr(feeds, "MAX_PUSHES", 2)
        self.profile(table, 22, 8)
        run(monkeypatch, *(item(str(i), title=f"TV number {i}", minutes_ago=i + 1) for i in range(4)))
        self.profile(table, 22, 7)
        assert run(monkeypatch)["pushed"] == 2 and run(monkeypatch)["pushed"] == 2 and run(monkeypatch)["pushed"] == 0
        assert len({p[2] for p in pushes}) == 4

    def test_a_deal_held_more_than_a_day_is_dropped(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        table.put_item(
            Item={
                "PK": f"USER#{USER}",
                "SK": "DEAL#old",
                "title": "Old TV",
                "keyword": "TV",
                "pushed": False,
                "publishedAt": (NOW - timedelta(hours=25)).isoformat(),
            }
        )
        add_rule(table, keyword="OLED")
        assert run(monkeypatch)["pushed"] == 0 and pushes == []

    def test_only_the_user_in_quiet_hours_is_held(self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch) -> None:
        add_rule(table, USER, keyword="OLED")
        add_rule(table, OTHER, keyword="OLED")
        self.profile(table, 22, 8)
        run(monkeypatch, item("1"))
        assert [p[0] for p in pushes] == [OTHER]

    def test_a_held_alert_is_dropped_if_its_keyword_was_deleted_or_turned_off(
        self, table: Any, pushes: list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_rule(table, keyword="OLED")
        self.profile(table, 22, 8)
        run(monkeypatch, item("1"))
        table.update_item(
            Key={"PK": f"USER#{USER}", "SK": "RULE#r1"},
            UpdateExpression="SET enabled = :no",
            ExpressionAttributeValues={":no": False},
        )
        self.profile(table, 22, 7)
        assert run(monkeypatch)["pushed"] == 0 and pushes == []
