"""Feed checker Lambda: every 30 minutes, reads the Dealnews feeds and alerts users whose keyword rules match new deals."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Attr, Key

from feeds import dealnews
from feeds.matching import matches
from push.notify import notify

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)  # Lambda's logger starts at WARNING, which would hide the one-line run summary

SOURCE = "dealnews"
MAX_AGE_HOURS = 6  # a first run, or a long outage, must not alert on old deals
KEEP_DAYS = 30
MAX_WORKERS = 3  # feeds read at the same time
START_GAP_SECONDS = 0.5  # between the starts of two requests: a few small requests, spaced out, every 30 minutes
READ_BUDGET_SECONDS = 40  # past this, the extra feeds that have not started are skipped so a slow host cannot eat the whole run
MAX_PUSHES = 5  # per user per run; deals over the cap stay unsent and go out on the next run
MAX_HELD_HOURS = 24  # an alert held back (quiet hours, the cap, a failed push) is dropped once its deal is this old


def _read_feeds() -> tuple[list[dict[str, Any]], list[str]]:
    """Deals from every feed, newest first, each deal once (one in several feeds counts once), and the required feeds that failed.

    The feeds are read a few at a time (MAX_WORKERS), and each request starts at least START_GAP_SECONDS after the one before,
    so Dealnews sees a few small requests, not a burst. One feed being down must not hide the others' deals. If every feed
    fails, the first error (in FEEDS order) is raised. A failing extra feed (Black Friday, popular, editors', categories) is
    only logged, so it cannot keep the checker permanently red. Once the read budget is spent the extras that have not started
    are skipped (logged), so a slow host cannot use up the run.
    """
    started = time.monotonic()
    gate = threading.Lock()  # one request starts at a time
    last_start: float | None = None

    def read(number: int, url: str) -> list[dict[str, Any]] | None:
        """The feed's deals, or None when the budget is spent before it could start."""
        nonlocal last_start
        with gate:
            if number and time.monotonic() - started > READ_BUDGET_SECONDS:
                return None
            if last_start is not None and (wait := last_start + START_GAP_SECONDS - time.monotonic()) > 0:
                time.sleep(wait)
            last_start = time.monotonic()
        return dealnews.parse(dealnews.fetch(url))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = [pool.submit(read, number, url) for number, url in enumerate(dealnews.FEEDS)]
    deals: dict[str, dict[str, Any]] = {}
    down: list[str] = []
    read_count = skipped = 0
    first_error: Exception | None = None
    for url, result in zip(dealnews.FEEDS, results, strict=True):  # in FEEDS order, so the merge below never depends on timing
        try:
            found = result.result()
        except Exception as e:
            log.error("feed could not be read: %s", url, exc_info=e)
            first_error = first_error or e
            down.append(url)
            continue
        if found is None:
            log.warning("read budget spent, skipping feed: %s", url)
            skipped += 1
            continue
        for deal in found:
            kept = deals.setdefault(deal["id"], deal)
            for field in ("price", "retailer", "category"):  # a copy without a price must not hide a priced one
                if kept[field] is None and deal[field] is not None:
                    kept[field] = deal[field]
        read_count += 1
    log.info(
        "feeds: %d read, %d failed, %d skipped", read_count, len(down), skipped
    )  # counts only: no keywords, titles or addresses
    if len(down) == len(dealnews.FEEDS) and first_error is not None:
        raise first_error
    return sorted(deals.values(), key=lambda d: d["published"], reverse=True), [u for u in down if u in dealnews.REQUIRED]


def _rules_by_user(table: Any) -> dict[str, list[dict[str, Any]]]:
    """Every usable enabled keyword rule, grouped by user, oldest first (so which rule names a deal never changes).

    A scan: fine for a table this small. Rules that are malformed (hand-edited, say) are skipped.
    """
    found: dict[str, list[dict[str, Any]]] = {}
    kwargs: dict[str, Any] = {"FilterExpression": Attr("SK").begins_with("RULE#") & Attr("enabled").eq(True)}
    while True:
        page = table.scan(**kwargs)
        for item in page["Items"]:
            if isinstance(item.get("keyword"), str) and item["keyword"].strip() and isinstance(item.get("sources"), list):
                found.setdefault(item["PK"].removeprefix("USER#"), []).append(item)
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    for rules in found.values():
        rules.sort(key=lambda r: (str(r.get("createdAt", "")), r["keyword"].casefold()))
    return found


def _is_quiet(table: Any, user: str, now: datetime) -> bool:
    """True while it is inside the user's quiet hours in their time zone (a window like 22 to 7 crosses midnight).

    Not quiet when no window or zone is set. A profile that cannot be read is logged and treated as not quiet, so an alert
    is never lost to a read failure.
    """
    try:
        profile = table.get_item(Key={"PK": f"USER#{user}", "SK": "PROFILE"}).get("Item") or {}
        if profile.get("quietStart") is None or profile.get("quietEnd") is None or not profile.get("timeZone"):
            return False
        start, end = int(profile["quietStart"]), int(profile["quietEnd"])
        hour = now.astimezone(ZoneInfo(profile["timeZone"])).hour
    except Exception:
        log.exception("quiet hours could not be read")
        return False
    return start <= hour < end if start < end else hour >= start or hour < end


def _held(table: Any, user: str, now: datetime, skip: set[str], limit: int, keywords: set[str]) -> list[dict[str, Any]]:
    """This user's stored deals whose alert has not gone out, newest first (at most `limit`), except those in `skip` and those
    whose keyword the user has since deleted or turned off (`keywords`: the enabled ones, case-folded)."""
    if limit <= 0:
        return []
    found: list[dict[str, Any]] = []
    oldest = (now - timedelta(hours=MAX_HELD_HOURS)).isoformat()
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(f"USER#{user}") & Key("SK").begins_with("DEAL#"),
        "FilterExpression": Attr("pushed").eq(False) & Attr("publishedAt").gte(oldest),
        "ConsistentRead": True,  # a deal marked sent a moment ago must not come back as unsent
    }
    while True:
        page = table.query(**kwargs)
        found += [i for i in page["Items"] if i["SK"] not in skip and str(i.get("keyword", "")).casefold() in keywords]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(found, key=lambda i: i["publishedAt"], reverse=True)[:limit]


def _claim(table: Any, user: str, deal: dict[str, Any], rule: dict[str, Any], now: datetime) -> tuple[dict[str, str], str]:
    """Stores the deal for the user. Returns its key and "new" (just stored), "retry" (stored earlier but its alert never went
    out) or "done" (stored and alerted).
    """
    key = {
        "PK": f"USER#{user}",
        "SK": f"DEAL#{deal['id']}",
    }  # the feed's id alone: a deal whose publish time changes is still the same deal
    item: dict[str, Any] = {
        **key,
        "title": deal["title"],
        "url": deal["url"],
        "source": SOURCE,
        "keyword": rule["keyword"],
        "publishedAt": deal["published"].isoformat(),
        "pushed": False,  # becomes True once the alert has been sent
        "ttl": int((now + timedelta(days=KEEP_DAYS)).timestamp()),
    }
    if deal["price"] is not None:
        item["price"] = deal["price"]
    if deal["retailer"]:
        item["retailer"] = deal["retailer"]
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        existing = table.get_item(Key=key).get("Item")
        return key, "retry" if existing and existing.get("pushed") is False else "done"
    return key, "new"


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])  # pyright: ignore[reportAttributeAccessIssue]
    now = datetime.now(UTC)
    found, feeds_down = _read_feeds()
    deals = dealnews.age_limit(now, found, MAX_AGE_HOURS)
    saved = pushed = failed = matched = already_sent = 0
    for user, rules in _rules_by_user(table).items():
        attempts = 0
        sent_keys: set[str] = set()
        quiet = _is_quiet(table, user, now)  # quiet: deals are still saved, their alerts wait for the window to end
        for deal in deals:
            rule = next((r for r in rules if matches(r, deal, SOURCE)), None)
            if rule is None:
                continue
            matched += 1
            try:  # one deal or user failing must not stop the others
                key, state = _claim(table, user, deal, rule, now)
                saved += state == "new"
                already_sent += state == "done"
                if state == "done" or quiet or attempts >= MAX_PUSHES:
                    continue  # quiet or over the cap: stays unsent, goes out on a later run
                attempts += 1  # counted even if it fails, so a broken push path can't bypass the cap
                sent_keys.add(key["SK"])
                pushed += notify(table, user, f"New deal: {rule['keyword']}", deal["title"], "/#/deals", strict=True)
                table.update_item(Key=key, UpdateExpression="SET pushed = :yes", ExpressionAttributeValues={":yes": True})
            except Exception:
                log.exception("deal alert failed")
                failed += 1
        if quiet:
            continue
        try:  # alerts held back earlier (quiet hours ended, or the deal has since left the feed) go out now, newest first
            held = _held(table, user, now, sent_keys, MAX_PUSHES - attempts, {r["keyword"].casefold() for r in rules})
        except Exception:
            log.exception("held alerts could not be read")
            failed += 1
            continue
        for old in held:
            try:
                pushed += notify(table, user, f"New deal: {old['keyword']}", old["title"], "/#/deals", strict=True)
                held_key = {"PK": old["PK"], "SK": old["SK"]}
                table.update_item(Key=held_key, UpdateExpression="SET pushed = :yes", ExpressionAttributeValues={":yes": True})
            except Exception:
                log.exception("held deal alert failed")
                failed += 1
    log.info(
        "deals: %d read, %d recent, %d matched (%d new, %d already sent), %d pushed, %d failed",
        len(found),
        len(deals),
        matched,
        saved,
        already_sent,
        pushed,
        failed,
    )
    if failed or feeds_down:  # shows as a Lambda error; unsent alerts are retried next run
        raise RuntimeError(f"{failed} deal alerts failed; feeds down: {', '.join(feeds_down) or 'none'}")
    return {"deals": len(deals), "saved": saved, "pushed": pushed}
