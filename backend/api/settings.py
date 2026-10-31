"""The signed-in user's settings: quiet hours (no push alerts overnight; they arrive when the window ends)."""

from typing import Any

from api.http import json_response, parse_object, valid_zone


def _hour(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23 else None


def _view(profile: dict[str, Any]) -> dict[str, Any]:
    start, end = profile.get("quietStart"), profile.get("quietEnd")
    quiet = {"start": int(start), "end": int(end)} if start is not None and end is not None else None
    return {"quietHours": quiet, "timeZone": profile.get("timeZone")}


def route(table: Any, user: str, route: str, body: str | None) -> dict[str, Any]:
    key = {"PK": f"USER#{user}", "SK": "PROFILE"}
    if route == "GET /me/settings":
        return json_response(200, _view(table.get_item(Key=key).get("Item") or {}))
    if route != "PUT /me/settings":
        return json_response(404, {"error": "not found"})
    data = parse_object(body)
    if data is None or "quietHours" not in data:
        return json_response(400, {"error": "body must be a JSON object with quietHours"})
    quiet = data["quietHours"]
    names = {"#tz": "timeZone"}  # timeZone is a DynamoDB reserved word
    values: dict[str, Any] = {}
    sets: list[str] = []
    if quiet is None:
        remove = "REMOVE quietStart, quietEnd"
    else:
        start, end = (_hour(quiet.get(k)) for k in ("start", "end")) if isinstance(quiet, dict) else (None, None)
        if start is None or end is None or start == end:
            return json_response(400, {"error": "quietHours needs a start and an end hour (0-23) that differ"})
        remove = ""
        sets += ["quietStart = :s", "quietEnd = :e"]
        values |= {":s": start, ":e": end}
    zone = valid_zone(data.get("timeZone"))  # the device sends its zone again, so travelling moves the window with it
    if zone:
        sets.append("#tz = :z")
        values[":z"] = zone
    expression = " ".join(part for part in (f"SET {', '.join(sets)}" if sets else "", remove) if part)
    kwargs: dict[str, Any] = {"Key": key, "UpdateExpression": expression, "ReturnValues": "ALL_NEW"}
    if values:
        kwargs["ExpressionAttributeValues"] = values
    if zone:
        kwargs["ExpressionAttributeNames"] = names
    return json_response(200, _view(table.update_item(**kwargs)["Attributes"]))
