"""Product watches: a product link plus a target price. A checker fills in prices later (see ROADMAP.md)."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from api.http import json_response, parse_object, price, query_items, update_item, view

MAX_WATCHES = 100
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
_ENDING = re.compile(r"(\.product\.\d+)?\.(html?|aspx?|p)$", re.IGNORECASE)
_ROUTE_WORDS = {"p", "ip", "dp", "site", "product", "products", "pdp", "-"}
_ID_LIKE = re.compile(r"^[a-z]?[-_]?[\d.]+[a-z]?$", re.IGNORECASE)


def _title_from(url: str) -> str:
    """A readable name from the link's last name-like path segment, until the checker reads the real product title."""
    names = []
    for segment in unquote(urlsplit(url).path).split("/"):
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
        return json_response(200, view(item))
    if route == "DELETE /me/watches/{id}":
        table.delete_item(Key=key)
        return json_response(200, {"deleted": watch_id})
    if route == "PUT /me/watches/{id}":
        return _update(table, key, body)
    return json_response(404, {"error": "not found"})


def _create(table: Any, user: str, body: str | None) -> dict[str, Any]:
    data = parse_object(body)
    if data is None:
        return json_response(400, {"error": "body must be a JSON object"})
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


def _update(table: Any, key: dict[str, str], body: str | None) -> dict[str, Any]:
    data = parse_object(body)
    if data is None:
        return json_response(400, {"error": "body must be a JSON object"})
    changes: dict[str, Any] = {}
    if "targetPrice" in data:
        target = price(data["targetPrice"])
        if target is None:
            return json_response(400, {"error": "targetPrice must be a positive dollar amount"})
        changes["targetPrice"] = target
    for flag in ("alertOnDrop", "paused"):
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
