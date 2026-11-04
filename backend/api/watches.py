"""Watches. Two kinds: a tracked product (a `name`, like a keyword, and an optional price; the feed checker records its sightings
and the lowest price seen, see feeds/products.py) and the older product link with a target price (no checker reads those)."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from api.http import json_response, parse_object, price, query_items, update_item, view
from feeds.matching import label, parse_keyword, same_keyword

MAX_WATCHES = 100
MAX_SIGHTINGS = 100  # shown on a product's screen
WATCH_ID = re.compile(r"^[0-9a-f]{12}$")
# Stores we know how to read. Others are refused up front instead of failing silently later.
RETAILERS = {
    "bestbuy.com": "Best Buy",
    "target.com": "Target",
    "walmart.com": "Walmart",
    "costco.com": "Costco",
    "tennis-warehouse.com": "Tennis Warehouse",
}


def retailer_for(url: str) -> str | None:
    if len(url) > 1000:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password:
        return None
    return next((name for domain, name in RETAILERS.items() if host == domain or host.endswith("." + domain)), None)


# Parts of a store link that are not the product's name: file endings, route words and product ids ("A-94909922", "6578912.p").
# A plain ".html" segment is an opaque page code (Tennis Warehouse), but Costco's "<name>.product.<id>.html" carries the name.
_COSTCO = re.compile(r"\.product\.\d+\.html$", re.IGNORECASE)
_ENDING = re.compile(r"\.p$", re.IGNORECASE)
_PAGE_FILE = re.compile(r"\.(html?|aspx?)$", re.IGNORECASE)
_ROUTE_WORDS = {"p", "ip", "dp", "site", "product", "products", "pdp", "-"}
_ID_LIKE = re.compile(r"^[a-z]?[-_]?[\d.]+[a-z]?$", re.IGNORECASE)


def _title_from(url: str) -> str:
    """A readable name from the link's last name-like path segment, until the checker reads the real product title."""
    names = []
    for segment in unquote(urlsplit(url).path).split("/"):
        segment = _COSTCO.sub("", segment)
        if _PAGE_FILE.search(segment):
            continue
        segment = _ENDING.sub("", segment)
        if segment and segment.lower() not in _ROUTE_WORDS and not _ID_LIKE.fullmatch(segment):
            names.append(segment)
    words = re.sub(r"[-_+]+", " ", names[-1] if names else "").strip()
    return (words[:1].upper() + words[1:])[:120] if words else "Product"


def route(table: Any, user: str, route: str, watch_id: str, body: str | None) -> dict[str, Any]:
    pk = f"USER#{user}"
    if route == "GET /me/watches":
        found = query_items(table, user, "WATCH#")
        return json_response(200, {"watches": [view(i) for i in sorted(found, key=lambda i: i["createdAt"], reverse=True)]})
    if route == "POST /me/watches":
        return _create(table, user, body)
    if not WATCH_ID.fullmatch(watch_id):
        return json_response(404, {"error": "no such watch"})
    key = {"PK": pk, "SK": f"WATCH#{watch_id}"}
    item = table.get_item(Key=key).get("Item")
    if not item:
        return json_response(404, {"error": "no such watch"})
    if route == "GET /me/watches/{id}":
        if "name" not in item:
            return json_response(200, view(item))
        return json_response(200, {**view(item), "sightings": _sightings(table, user, watch_id)})
    if route == "DELETE /me/watches/{id}":
        table.delete_item(Key=key)
        for sighting in query_items(table, user, f"SIGHT#{watch_id}#"):
            table.delete_item(Key={"PK": sighting["PK"], "SK": sighting["SK"]})
        return json_response(200, {"deleted": watch_id})
    if route == "PUT /me/watches/{id}":
        return _update(table, key, body, product="name" in item)
    return json_response(404, {"error": "not found"})


def _sightings(table: Any, user: str, watch_id: str) -> list[dict[str, Any]]:
    """A product's recorded prices, newest first (the id is the deal's, a stable key for the app)."""
    found = query_items(table, user, f"SIGHT#{watch_id}#")
    found.sort(key=lambda i: str(i.get("publishedAt", "")), reverse=True)
    return [
        {**{k: v for k, v in view(i).items() if not k.startswith("alert")}, "id": i["SK"].rpartition("#")[2]}
        for i in found[:MAX_SIGHTINGS]
    ]


def _create_product(table: Any, user: str, data: dict[str, Any]) -> dict[str, Any]:
    name = data.get("name")
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 60:
        return json_response(400, {"error": "name must be 1-60 characters"})
    if parse_keyword(name) is None:
        return json_response(
            400, {"error": 'name needs a word to look for (a word after - is skipped, e.g. XM5 -XM4) and any "phrase" closed'}
        )
    target = None
    if data.get("targetPrice") is not None:  # the price is optional
        target = price(data["targetPrice"])
        if target is None:
            return json_response(400, {"error": "targetPrice must be a positive dollar amount or left out"})
    flags = {}
    for flag in ("alertOnLow", "alertOnDrop"):
        flags[flag] = data.get(flag, True)
        if not isinstance(flags[flag], bool):
            return json_response(400, {"error": f"{flag} must be true or false"})
    existing = query_items(table, user, "WATCH#")
    if any("name" in w and same_keyword(w["name"], name) for w in existing):
        return json_response(400, {"error": "you are already tracking this product"})
    if len(existing) >= MAX_WATCHES:  # a soft cap: two simultaneous adds could slip past it
        return json_response(400, {"error": f"up to {MAX_WATCHES} watches"})
    watch_id = uuid.uuid4().hex[:12]
    item = {
        "PK": f"USER#{user}",
        "SK": f"WATCH#{watch_id}",
        "id": watch_id,
        "name": name.strip(),
        "title": label(name.strip()),
        "targetPrice": target,
        **flags,
        "paused": False,
        "status": "ok",
        "createdAt": datetime.now(UTC).isoformat(),
    }
    table.put_item(Item=item)
    return json_response(201, view(item))


def _create(table: Any, user: str, body: str | None) -> dict[str, Any]:
    data = parse_object(body)
    if data is None:
        return json_response(400, {"error": "body must be a JSON object"})
    if "name" in data and "url" not in data:
        return _create_product(table, user, data)
    url = data.get("url")
    retailer = retailer_for(url) if isinstance(url, str) else None
    if not retailer or not isinstance(url, str):
        return json_response(400, {"error": f"url must be an https link from: {', '.join(RETAILERS.values())}"})
    target = price(data.get("targetPrice"))
    if target is None:
        return json_response(400, {"error": "targetPrice must be a positive dollar amount"})
    title = data.get("title")
    if title is not None and not (isinstance(title, str) and 0 < len(title.strip()) <= 120):
        return json_response(400, {"error": "title must be 1-120 characters"})
    alert_on_drop = data.get("alertOnDrop", True)
    if not isinstance(alert_on_drop, bool):
        return json_response(400, {"error": "alertOnDrop must be true or false"})
    existing = query_items(table, user, "WATCH#")
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
    if any(w.get("urlHash") == url_hash for w in existing):
        return json_response(400, {"error": "you are already watching this link"})
    if len(existing) >= MAX_WATCHES:  # a soft cap: two simultaneous adds could slip past it
        return json_response(400, {"error": f"up to {MAX_WATCHES} watches"})
    watch_id = uuid.uuid4().hex[:12]
    item = {
        "PK": f"USER#{user}",
        "SK": f"WATCH#{watch_id}",
        "id": watch_id,
        "url": url,
        "urlHash": url_hash,  # one shared product record per link, whoever watches it
        "retailer": retailer,
        "title": title.strip() if isinstance(title, str) else _title_from(url),
        "targetPrice": target,
        "alertOnDrop": alert_on_drop,
        "paused": False,
        "status": "pending",  # becomes ok / blocked once the checker has looked
        "createdAt": datetime.now(UTC).isoformat(),
    }
    table.put_item(Item=item)
    return json_response(201, view(item))


def _update(table: Any, key: dict[str, str], body: str | None, product: bool = False) -> dict[str, Any]:
    data = parse_object(body)
    if data is None:
        return json_response(400, {"error": "body must be a JSON object"})
    changes: dict[str, Any] = {}
    if "targetPrice" in data:
        target = price(data["targetPrice"])
        if target is None and not (product and data["targetPrice"] is None):  # a product's price may be cleared
            return json_response(400, {"error": "targetPrice must be a positive dollar amount"})
        changes["targetPrice"] = target
    for flag in ("alertOnDrop", "paused", *(("alertOnLow",) if product else ())):
        if flag in data:
            if not isinstance(data[flag], bool):
                return json_response(400, {"error": f"{flag} must be true or false"})
            changes[flag] = data[flag]
    if "title" in data:
        if not (isinstance(data["title"], str) and 0 < len(data["title"].strip()) <= 120):
            return json_response(400, {"error": "title must be 1-120 characters"})
        changes["title"] = data["title"].strip()
    if not changes:
        return json_response(400, {"error": "nothing to change"})
    updated = update_item(table, key, changes)
    return json_response(200, view(updated)) if updated else json_response(404, {"error": "no such watch"})
