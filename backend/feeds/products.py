"""Tracked products: every deal that matches a product's name is recorded as a "sighting" (store, price, time), the lowest
price seen is kept on the product, and a new low (or reaching the user's price) makes an alert.

Prices come only from the deals the feeds list, not from store pages, so a store with no deal simply has no sighting.
Sightings are stored as `SIGHT#<product id>#<deal id>` items next to the product (`WATCH#<id>`, a watch with a `name`).
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from feeds.matching import label, matches

log = logging.getLogger(__name__)

SIGHTING_DAYS = 90  # sightings are kept this long; the lowest price stays on the product


def products_by_user(table: Any) -> dict[str, list[dict[str, Any]]]:
    """Every product (a watch with a `name`) that is not paused, grouped by user. A scan, like the keyword rules."""
    found: dict[str, list[dict[str, Any]]] = {}
    kwargs: dict[str, Any] = {
        "FilterExpression": Attr("SK").begins_with("WATCH#") & Attr("name").exists() & Attr("paused").eq(False)
    }
    while True:
        page = table.scan(**kwargs)
        for item in page["Items"]:
            if isinstance(item.get("name"), str) and item["name"].strip():
                found.setdefault(item["PK"].removeprefix("USER#"), []).append(item)
        if "LastEvaluatedKey" not in page:
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _alert(product: dict[str, Any], deal: dict[str, Any], low: bool, reached: bool) -> tuple[str, str]:
    """The push for a sighting: a new low (maybe also within the user's price), or just reaching their price."""
    name = label(product["name"])
    where = f" at {deal['retailer']}" if deal["retailer"] else ""
    body = f"{_money(deal['price'])}{where}"
    within = f" · within your {_money(product['targetPrice'])} price" if reached else ""
    return (f"New low: {name}" if low else f"Your price: {name}"), body + within


def record(table: Any, user: str, products: list[dict[str, Any]], deals: list[dict[str, Any]], now: datetime, source: str) -> int:
    """Records the new sightings of this user's products (`deals` newest first) and returns how many were new.

    A sighting is stored once per deal (a conditional write), so overlapping runs and repeated feed items do nothing twice.
    The first sighting only sets the price to beat; a later, lower price is a new low; reaching the user's price from above
    is its own alert. Alerts wait on the sighting (`pushed` False) until the checker has sent them.
    """
    new = 0
    for product in products:
        rule = {"keyword": product["name"], "sources": [source], "enabled": True}
        lowest: Decimal | None = product.get("lowestPrice")
        target: Decimal | None = product.get("targetPrice")
        changes: dict[str, Any] = {}
        for deal in reversed(deals):  # oldest first, so a run that finds two lower prices alerts on each step down
            if deal["price"] is None or not matches(rule, deal, source):
                continue
            price: Decimal = deal["price"]
            first = lowest is None
            low = first or price < lowest  # type: ignore[operator]
            reached = target is not None and price <= target and (first or lowest > target)  # type: ignore[operator]
            drop = low and not first and product.get("alertOnLow", True)  # the first sighting only sets the price to beat
            alert = bool(drop or (reached and product.get("alertOnDrop", True)))
            item: dict[str, Any] = {
                "PK": f"USER#{user}",
                "SK": f"SIGHT#{product['id']}#{deal['id']}",
                "price": price,
                "title": deal["title"],
                "url": deal["url"],
                "publishedAt": deal["published"].isoformat(),
                "newLow": low,
                "pushed": not alert,
                "ttl": int((now + timedelta(days=SIGHTING_DAYS)).timestamp()),
            }
            if deal["retailer"]:
                item["retailer"] = deal["retailer"]
            if alert:
                item["alertTitle"], item["alertBody"] = _alert(product, deal, bool(drop), reached)
            try:
                table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                continue  # seen on an earlier run: it already counted
            new += 1
            changes["lastPrice"], changes["lastSeenAt"] = price, item["publishedAt"]
            if low:
                lowest = price
                changes.update(lowestPrice=price, lowestAt=item["publishedAt"], lowestUrl=deal["url"])
                changes["lowestRetailer"] = deal["retailer"]
        if changes:
            _save(table, user, product["id"], changes)
    return new


def _save(table: Any, user: str, product_id: str, changes: dict[str, Any]) -> None:
    names = {f"#f{i}": field for i, field in enumerate(changes)}
    values = {f":v{i}": value for i, value in enumerate(changes.values())}
    try:
        table.update_item(
            Key={"PK": f"USER#{user}", "SK": f"WATCH#{product_id}"},
            UpdateExpression="SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(changes))),
            ConditionExpression="attribute_exists(PK)",  # the product may have been deleted while the checker ran
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        log.info("product was deleted during the run")


def pending(table: Any, user: str, now: datetime, hold_hours: int) -> list[dict[str, Any]]:
    """This user's price alerts that have not gone out yet (new ones, ones held back by quiet hours, ones whose push failed),
    newest first. Alerts older than `hold_hours` are left out."""
    oldest = (now - timedelta(hours=hold_hours)).isoformat()
    found: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(f"USER#{user}") & Key("SK").begins_with("SIGHT#"),
        "FilterExpression": Attr("pushed").eq(False) & Attr("publishedAt").gte(oldest),
        "ConsistentRead": True,
    }
    while True:
        page = table.query(**kwargs)
        found += page["Items"]
        if "LastEvaluatedKey" not in page:
            return sorted(found, key=lambda i: i["publishedAt"], reverse=True)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
