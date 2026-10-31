"""Feed checker Lambda: every 30 minutes, reads the Dealnews feeds and alerts users whose keyword rules match new deals."""

import logging
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Attr, Key

from feeds import dealnews, status
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
DIGEST_OVER = 3  # more alerts than this waiting for one user go out as one summary push, not one push each
MAX_HELD_HOURS = 24  # an alert held back (quiet hours, a failed push) is dropped once its deal is this old


def _read_feeds() -> tuple[list[dict[str, Any]], list[str], tuple[int, int, int]]:
    """Deals from every feed, newest first, each deal once (one in several feeds counts once), the required feeds that failed, and
    how many feeds were read, failed and skipped.

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
            if kept["price_from_title"] and not deal["price_from_title"]:  # a feed's own price beats a guess from a title
                kept["price"], kept["price_from_title"] = deal["price"], False
        read_count += 1
    log.info(
        "feeds: %d read, %d failed, %d skipped", read_count, len(down), skipped
    )  # counts only: no keywords, titles or addresses
    if len(down) == len(dealnews.FEEDS) and first_error is not None:
        raise first_error
    required_down = [u for u in down if u in dealnews.REQUIRED]
    return sorted(deals.values(), key=lambda d: d["published"], reverse=True), required_down, (read_count, len(down), skipped)


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


def _record_status(table: Any, now: datetime, counts: tuple[int, int, int]) -> None:
    """Remembers when the feeds were last read, for the app's "Checked 12 min ago" line. One shared item (not a user's data).

    Best effort: failing to write it must never stop the alerts.
    """
    read, failed, skipped = counts
    try:
        table.put_item(
            Item={
                **status.KEY,
                "checkedAt": now.isoformat(),
                "feedsRead": read,
                "feedsFailed": failed,
                "feedsSkipped": skipped,
            }
        )
    except Exception:
        log.exception("checker status could not be saved")


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


def _unsent(table: Any, user: str, now: datetime, keywords: set[str]) -> list[dict[str, Any]]:
    """This user's stored deals whose alert has not gone out, newest first: new ones, ones held back (quiet hours) and ones
    whose push failed. Deals older than MAX_HELD_HOURS, and those whose keyword the user has since deleted or turned off
    (`keywords`: the enabled ones, case-folded), are left out.
    """
    found: list[dict[str, Any]] = []
    oldest = (now - timedelta(hours=MAX_HELD_HOURS)).isoformat()
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(f"USER#{user}") & Key("SK").begins_with("DEAL#"),
        "FilterExpression": Attr("pushed").eq(False) & Attr("publishedAt").gte(oldest),
        "ConsistentRead": True,  # a deal marked sent a moment ago must not come back as unsent
    }
    while True:
        page = table.query(**kwargs)
        found += [i for i in page["Items"] if str(i.get("keyword", "")).casefold() in keywords]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(found, key=lambda i: i["publishedAt"], reverse=True)


_EXCLUSION = re.compile(r'-"[^"]*"|(?<!\S)-[^\W\d_]\S*')


def _label(keyword: str) -> str:
    """A keyword as the summary shows it: without its `-exclusions` and quote marks (`TV -mount "Pro Max"` reads `TV Pro Max`)."""
    return " ".join(_EXCLUSION.sub("", keyword).replace('"', "").split()) or keyword


def _digest(unsent: list[dict[str, Any]]) -> tuple[str, str]:
    """One summary push for many deals: "12 new deals", then the keywords with the most ("TV (5), OLED (4) and 2 more").
    Keywords that differ only in case count together.
    """
    shown: dict[str, str] = {}
    per_keyword: Counter[str] = Counter()
    for item in unsent:  # newest first, so ties keep the newest keyword first
        label = _label(item["keyword"])
        shown.setdefault(label.casefold(), label)
        per_keyword[label.casefold()] += 1
    top = ", ".join(f"{shown[key]} ({count})" for key, count in per_keyword.most_common(3))
    more = len(per_keyword) - 3
    return f"{len(unsent)} new deals", f"{top} and {more} more" if more > 0 else top


def _mark_sent(table: Any, item: dict[str, Any]) -> None:
    table.update_item(
        Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression="SET pushed = :yes", ExpressionAttributeValues={":yes": True}
    )


def _claim(table: Any, user: str, deal: dict[str, Any], rule: dict[str, Any], now: datetime) -> str:
    """Stores the deal for the user. Returns "new" (just stored), "retry" (stored earlier but its alert never went out) or
    "done" (stored and alerted).
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
        return "retry" if existing and existing.get("pushed") is False else "done"
    return "new"


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])  # pyright: ignore[reportAttributeAccessIssue]
    now = datetime.now(UTC)
    found, feeds_down, counts = _read_feeds()
    if not feeds_down:  # with the main feed down the line must go stale, not say "checked"
        _record_status(table, datetime.now(UTC), counts)  # the time the feeds were read, even if an alert fails later
    deals = dealnews.age_limit(now, found, MAX_AGE_HOURS)
    saved = pushed = failed = matched = already_sent = 0
    for user, rules in _rules_by_user(table).items():
        quiet = _is_quiet(table, user, now)  # quiet: deals are still saved, their alerts wait for the window to end
        for deal in deals:
            rule = next((r for r in rules if matches(r, deal, SOURCE)), None)
            if rule is None:
                continue
            matched += 1
            try:  # one deal failing to save must not stop the others
                state = _claim(table, user, deal, rule, now)
                saved += state == "new"
                already_sent += state == "done"
            except Exception:
                log.exception("deal could not be saved")
                failed += 1
        if quiet:
            continue
        try:  # everything waiting for this user: new deals, ones held back, ones whose push failed earlier
            unsent = _unsent(table, user, now, {r["keyword"].casefold() for r in rules})
            if len(unsent) > DIGEST_OVER:  # a flood (Black Friday, or a quiet window just ended): one push, not dozens
                title, body = _digest(unsent)
                pushed += notify(table, user, title, body, "/#/deals", strict=True)
                for waiting in unsent:  # the push is out: one write failing must not leave the rest to be sent again
                    try:
                        _mark_sent(table, waiting)
                    except Exception:
                        log.exception("deal could not be marked sent")
                        failed += 1
            else:
                for waiting in unsent:  # one deal failing must not stop the others
                    try:
                        pushed += notify(
                            table, user, f"New deal: {waiting['keyword']}", waiting["title"], "/#/deals", strict=True
                        )
                        _mark_sent(table, waiting)
                    except Exception:
                        log.exception("deal alert failed")
                        failed += 1
        except Exception:
            log.exception("deal alerts failed")
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
