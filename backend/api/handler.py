"""HTTP API Lambda: the signed-in user's watches, keyword rules, deals feed and push devices."""

import os
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from boto3.dynamodb.conditions import Key

from api import rules, watches
from api.http import json_response, parse_object, view
from push.notify import device_key, devices, notify
from push.webpush import allowed_endpoint

MAX_DEVICES = 10
MAX_BODY = 8_192  # bytes; the largest real request (a push subscription) is under 1 KB


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])  # pyright: ignore[reportAttributeAccessIssue]
    try:
        user = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]  # the user comes from the token, never the request
    except KeyError:
        return json_response(401, {"error": "unauthorized"})
    if len((event.get("body") or "").encode()) > MAX_BODY:
        return json_response(413, {"error": "request too large"})
    route = event.get("routeKey", "")
    item_id = (event.get("pathParameters") or {}).get("id", "")
    if route.partition(" ")[2].startswith("/me/watches"):
        return watches.route(table, user, route, item_id, event.get("body"))
    if route.partition(" ")[2].startswith("/me/rules"):
        return rules.route(table, user, route, item_id, event.get("body"))
    if route == "GET /me/deals":
        found = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user}") & Key("SK").begins_with("DEAL#"),
            ScanIndexForward=False,
            Limit=100,
        )["Items"]
        return json_response(200, {"deals": [view(d) for d in found]})
    if route in ("GET /me/push", "PUT /me/push", "DELETE /me/push", "POST /me/push/test"):
        return _push(table, user, route, event)
    return json_response(404, {"error": "not found"})


def _valid_zone(zone: Any) -> str | None:
    if not isinstance(zone, str) or len(zone) > 64:
        return None
    try:
        ZoneInfo(zone)
    except ZoneInfoNotFoundError, ValueError, OSError:  # OSError: names like "Europe" are directories, not zones
        return None
    return zone


def _push(table: Any, user: str, route: str, event: dict[str, Any]) -> dict[str, Any]:
    """Notifications on this device: status (GET), turn on (PUT), turn off (DELETE), test (POST)."""
    if route == "GET /me/push":
        endpoint = (event.get("queryStringParameters") or {}).get("endpoint", "")
        mine = devices(table, user)
        return json_response(200, {"devices": len(mine), "thisDevice": any(d["SK"] == device_key(endpoint) for d in mine)})
    data = parse_object(event.get("body"))
    if data is None:
        return json_response(400, {"error": "body must be a JSON object"})
    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 1000 or not allowed_endpoint(endpoint):
        return json_response(400, {"error": "not a known push service"})
    key = {"PK": f"USER#{user}", "SK": device_key(endpoint)}
    if route == "DELETE /me/push":
        table.delete_item(Key=key)
        return json_response(200, {"devices": len(devices(table, user))})
    if route == "POST /me/push/test":
        if "Item" not in table.get_item(Key=key):
            return json_response(404, {"error": "notifications are not on for this device"})
        return json_response(200, {"sent": notify(table, user, "DealsWatcher", "Notifications work on this device.", "/")})
    keys = data.get("keys")
    if not (isinstance(keys, dict) and all(isinstance(keys.get(k), str) and 0 < len(keys[k]) <= 200 for k in ("p256dh", "auth"))):
        return json_response(400, {"error": "subscription keys missing"})
    zone = _valid_zone(data.get("timeZone"))
    if len(devices(table, user)) >= MAX_DEVICES and "Item" not in table.get_item(Key=key):
        return json_response(400, {"error": f"up to {MAX_DEVICES} devices"})
    table.put_item(Item={**key, "subscription": {"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}})
    if zone:
        table.update_item(
            Key={"PK": f"USER#{user}", "SK": "PROFILE"},
            UpdateExpression="SET #tz = :z",  # timeZone is a DynamoDB reserved word
            ExpressionAttributeNames={"#tz": "timeZone"},
            ExpressionAttributeValues={":z": zone},
        )
    return json_response(200, {"devices": len(devices(table, user))})
