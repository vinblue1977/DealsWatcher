"""Small helpers shared by the API's route modules."""

import json
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from boto3.dynamodb.conditions import Key


def json_response(status: int, body: Any) -> dict[str, Any]:
    def default(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        raise TypeError(type(value).__name__)

    headers = {"Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=default)}


def view(item: dict[str, Any]) -> dict[str, Any]:
    """An item as the API shows it: without its DynamoDB keys, expiry and delivery flag."""
    return {k: v for k, v in item.items() if k not in ("PK", "SK", "ttl", "pushed")}


def parse_object(body: str | None) -> dict[str, Any] | None:
    """The request body as a JSON object, or None when it isn't one."""
    try:
        data = json.loads(body or "{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def price(value: Any) -> Decimal | None:
    """A positive dollar amount (at most two decimals, under $100,000) as a Decimal, else None."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():  # json.loads accepts NaN and Infinity
            return None
        amount = amount.quantize(Decimal("0.01"))
    except ArithmeticError, ValueError:
        return None
    return amount if Decimal("0") < amount < Decimal("100000") else None


def update_item(table: Any, key: dict[str, str], changes: dict[str, Any]) -> dict[str, Any] | None:
    """Set just these fields on an existing item (other writers' fields are left alone); None if it no longer exists."""
    names = {f"#f{i}": field for i, field in enumerate(changes)}
    values = {f":v{i}": value for i, value in enumerate(changes.values())}
    expression = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(changes)))
    try:
        return table.update_item(
            Key=key,
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def query_items(table: Any, user: str, prefix: str) -> list[dict[str, Any]]:
    """Every item of a user whose sort key starts with prefix (follows DynamoDB's 1 MB pages)."""
    found: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(f"USER#{user}") & Key("SK").begins_with(prefix)}
    while True:
        page = table.query(**kwargs)
        found += page["Items"]
        if "LastEvaluatedKey" not in page:
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def valid_zone(zone: Any) -> str | None:
    if not isinstance(zone, str) or len(zone) > 64:
        return None
    try:
        ZoneInfo(zone)
    except ZoneInfoNotFoundError, ValueError, OSError:  # OSError: names like "Europe" are directories, not zones
        return None
    return zone
