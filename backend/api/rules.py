"""Keyword rules: alert when a deal feed item mentions a keyword (optionally under a maximum price)."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from api.http import json_response, parse_object, price, query_items, update_item, view
from feeds.matching import parse_keyword, same_keyword

MAX_RULES = 50
RULE_ID = re.compile(r"^[0-9a-f]{12}$")
SOURCES = ("dealnews",)  # the feeds the checker reads; Slickdeals and Reddit disallow automated access (robots.txt)


def _fields(data: dict[str, Any], partial: bool) -> tuple[dict[str, Any], str | None]:
    """Validated rule fields from a request body, or an error message."""
    out: dict[str, Any] = {}
    if "keyword" in data or not partial:
        keyword = data.get("keyword")
        if not isinstance(keyword, str) or not 0 < len(keyword.strip()) <= 60:
            return {}, "keyword must be 1-60 characters"
        if parse_keyword(keyword) is None:
            return {}, 'keyword needs a word to look for (a word after - is skipped, e.g. TV -mount) and any "phrase" closed'
        out["keyword"] = keyword.strip()
    if "maxPrice" in data:
        if data["maxPrice"] is None:
            out["maxPrice"] = None
        else:
            amount = price(data["maxPrice"])
            if amount is None:
                return {}, "maxPrice must be a positive dollar amount or null"
            out["maxPrice"] = amount
    if "sources" in data:
        sources = data["sources"]
        if not (isinstance(sources, list) and sources and all(s in SOURCES for s in sources)):
            return {}, f"sources must be a non-empty list of: {', '.join(SOURCES)}"
        out["sources"] = sorted(set(sources))
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            return {}, "enabled must be true or false"
        out["enabled"] = data["enabled"]
    return out, None


def _has_keyword(rules: list[dict[str, Any]], keyword: str, except_id: str = "") -> bool:
    return any(r["id"] != except_id and same_keyword(r["keyword"], keyword) for r in rules)


def route(table: Any, user: str, route: str, rule_id: str, body: str | None) -> dict[str, Any]:
    pk = f"USER#{user}"
    if route == "GET /me/rules":
        found = query_items(table, user, "RULE#")
        return json_response(200, {"rules": [view(i) for i in sorted(found, key=lambda i: i["createdAt"], reverse=True)]})
    if route == "POST /me/rules":
        data = parse_object(body)
        if data is None:
            return json_response(400, {"error": "body must be a JSON object"})
        fields, error = _fields(data, partial=False)
        if error:
            return json_response(400, {"error": error})
        existing = query_items(table, user, "RULE#")
        if _has_keyword(existing, fields["keyword"]):  # a soft check, like the cap: two simultaneous adds could slip past it
            return json_response(400, {"error": "you already have this keyword"})
        if len(existing) >= MAX_RULES:  # a soft cap: two simultaneous adds could slip past it
            return json_response(400, {"error": f"up to {MAX_RULES} keywords"})
        new_id = uuid.uuid4().hex[:12]
        item = {
            "PK": pk,
            "SK": f"RULE#{new_id}",
            "id": new_id,
            "maxPrice": None,
            "sources": list(SOURCES),
            "enabled": True,
            "createdAt": datetime.now(UTC).isoformat(),
            **fields,
        }
        table.put_item(Item=item)
        return json_response(201, view(item))
    key = {"PK": pk, "SK": f"RULE#{rule_id}"}
    item = table.get_item(Key=key).get("Item") if RULE_ID.fullmatch(rule_id) else None
    if not item:
        return json_response(404, {"error": "no such keyword"})
    if route == "DELETE /me/rules/{id}":
        table.delete_item(Key=key)
        return json_response(200, {"deleted": rule_id})
    if route == "PUT /me/rules/{id}":
        data = parse_object(body)
        if data is None:
            return json_response(400, {"error": "body must be a JSON object"})
        fields, error = _fields(data, partial=True)
        if error or not fields:
            return json_response(400, {"error": error or "nothing to change"})
        if "keyword" in fields and _has_keyword(query_items(table, user, "RULE#"), fields["keyword"], except_id=rule_id):
            return json_response(400, {"error": "you already have this keyword"})
        updated = update_item(table, key, fields)
        return json_response(200, view(updated)) if updated else json_response(404, {"error": "no such keyword"})
    return json_response(404, {"error": "not found"})
