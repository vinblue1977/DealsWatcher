"""Feed checker Lambda: every 30 minutes, reads the Dealnews feeds and alerts users whose keyword rules match new deals."""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr

from feeds import dealnews
from feeds.matching import matches
from push.notify import notify

log = logging.getLogger(__name__)

SOURCE = "dealnews"
MAX_AGE_HOURS = 6  # a first run, or a long outage, must not alert on old deals
KEEP_DAYS = 30
PAUSE_SECONDS = 1  # between feed requests: a few small requests, spaced out, every 30 minutes
READ_BUDGET_SECONDS = 40  # past this, the remaining extra feeds are skipped so a slow host cannot eat the whole run
MAX_PUSHES = 5  # per user per run; deals over the cap stay unsent and go out on the next run


def _read_feeds() -> tuple[list[dict[str, Any]], list[str]]:
    """Deals from every feed, newest first, each deal once (one in several feeds counts once), and the required feeds that failed.

    One feed being down must not hide the others' deals. If every feed fails, the first error is raised. A failing extra feed
    (Black Friday, popular, editors', categories) is only logged, so it cannot keep the checker permanently red. Once the read
    budget is spent the remaining extras are skipped (logged), so a slow host cannot use up the run.
    """
    deals: dict[str, dict[str, Any]] = {}
    down: list[str] = []
    first_error: Exception | None = None
    started = time.monotonic()
    for number, url in enumerate(dealnews.FEEDS):
        if number:
            if time.monotonic() - started > READ_BUDGET_SECONDS:
                log.warning("read budget spent, skipping feed: %s", url)
                continue
            time.sleep(PAUSE_SECONDS)
        try:
            for deal in dealnews.parse(dealnews.fetch(url)):
                kept = deals.setdefault(deal["id"], deal)
                for field in ("price", "retailer", "category"):  # a copy without a price must not hide a priced one
                    if kept[field] is None and deal[field] is not None:
                        kept[field] = deal[field]
        except Exception as e:
            log.exception("feed could not be read: %s", url)
            first_error = first_error or e
            down.append(url)
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
    saved = pushed = failed = 0
    for user, rules in _rules_by_user(table).items():
        attempts = 0
        for deal in deals:
            rule = next((r for r in rules if matches(r, deal, SOURCE)), None)
            if rule is None:
                continue
            try:  # one deal or user failing must not stop the others
                key, state = _claim(table, user, deal, rule, now)
                saved += state == "new"
                if state == "done" or attempts >= MAX_PUSHES:
                    continue  # over the cap: stays unsent, goes out on a later run
                attempts += 1  # counted even if it fails, so a broken push path can't bypass the cap
                pushed += notify(table, user, f"New deal: {rule['keyword']}", deal["title"], "/#/deals", strict=True)
                table.update_item(Key=key, UpdateExpression="SET pushed = :yes", ExpressionAttributeValues={":yes": True})
            except Exception:
                log.exception("deal alert failed")
                failed += 1
    if failed or feeds_down:  # shows as a Lambda error; unsent alerts are retried next run
        raise RuntimeError(f"{failed} deal alerts failed; feeds down: {', '.join(feeds_down) or 'none'}")
    return {"deals": len(deals), "saved": saved, "pushed": pushed}
