#!/usr/bin/env python3
"""Remove someone: delete their account and every item of theirs in the table (watches, keywords, deals, devices).

Usage: scripts/remove_user.py friend@example.com              show what would be removed (nothing is changed)
       scripts/remove_user.py friend@example.com --yes        really remove it
       scripts/remove_user.py friend@example.com --disable    block sign-in and turn their keyword alerts off; keep the data
       scripts/remove_user.py <user id> --yes                 clean up leftovers of an already removed account (see below)

Needs AWS credentials (`aws login`). Removing cannot be undone.

Access tokens that were already issued stay valid for up to 1 hour, and nothing can recall them. So someone who is signed in
can still change their own data for up to an hour after a removal. Anything they create then is left behind under their user id
(the script prints it); run the last form above an hour later to clear it.
"""

import argparse
import collections
import os
import re
import sys
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

REGION = os.environ.get("AWS_REGION", "us-east-2")
STACK = "DealsWatcher"
USER_ID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def user_items(table: Any, sub: str) -> list[dict[str, Any]]:
    """Every item that belongs to this user (all their sort keys), read consistently, following DynamoDB's 1 MB pages."""
    found: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(f"USER#{sub}"), "ConsistentRead": True}
    while True:
        page = table.query(**kwargs)
        found += page["Items"]
        if "LastEvaluatedKey" not in page:
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def summary(items: list[dict[str, Any]]) -> dict[str, int]:
    """Item counts by kind (WATCH, RULE, DEAL, PUSH, ...)."""
    return dict(collections.Counter(item["SK"].partition("#")[0] for item in items))


def purge(table: Any, items: list[dict[str, Any]]) -> int:
    """Deletes these items. They come from `user_items`, so only one user's partition is ever touched."""
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
    return len(items)


def turn_off_alerts(table: Any, items: list[dict[str, Any]]) -> int:
    """Switches the user's keyword rules off, so the feed checker stops matching (and alerting) for them."""
    rules = [i for i in items if i["SK"].startswith("RULE#")]
    for rule in rules:
        table.update_item(
            Key={"PK": rule["PK"], "SK": rule["SK"]},
            UpdateExpression="SET enabled = :off",
            ExpressionAttributeValues={":off": False},
        )
    return len(rules)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("who", help="their email address (or, for leftovers, their user id)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", action="store_true", help="really remove the account and its data")
    mode.add_argument("--disable", action="store_true", help="block sign-in and turn keyword alerts off; keep the data")
    args = parser.parse_args()

    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]
    }
    pool, table_name = outputs["UserPoolId"], outputs["TableName"]
    cognito = boto3.client("cognito-idp", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(table_name)

    if USER_ID.match(args.who):  # leftovers of an account that is already gone
        try:
            cognito.admin_get_user(UserPoolId=pool, Username=args.who)
        except cognito.exceptions.UserNotFoundException:
            pass
        else:
            print("That account still exists: use its email address instead.", file=sys.stderr)
            return 1
        items = user_items(table, args.who)
        print(f"Leftovers of {args.who}: {len(items)} items {summary(items)}")
        if args.yes:
            purge(table, items)
            print("Deleted.")
        else:
            print("Nothing was changed. Run again with --yes to delete them.")
        return 0

    try:
        user = cognito.admin_get_user(UserPoolId=pool, Username=args.who)
    except cognito.exceptions.UserNotFoundException:
        print(f"No account for {args.who}.", file=sys.stderr)
        return 1
    sub = next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")
    items = user_items(table, sub)
    print(f"{args.who} (user id {sub}): {len(items)} items {summary(items)}")

    if args.disable:
        cognito.admin_disable_user(UserPoolId=pool, Username=args.who)
        cognito.admin_user_global_sign_out(UserPoolId=pool, Username=args.who)  # revokes their refresh tokens
        print(f"Keyword alerts turned off for {turn_off_alerts(table, items)} keywords. Their data is kept.")
        print("They cannot sign in or renew a session. A session that is open right now can still work for up to 1 hour.")
        return 0
    if not args.yes:
        print("Nothing was changed. Run again with --yes to remove the account and these items.")
        return 0

    # Cut off sign-in first, then clear the data, then remove the account.
    cognito.admin_disable_user(UserPoolId=pool, Username=args.who)
    cognito.admin_user_global_sign_out(UserPoolId=pool, Username=args.who)
    purge(table, items)
    left = user_items(table, sub)
    purge(table, left)  # anything created while this ran
    cognito.admin_delete_user(UserPoolId=pool, Username=args.who)
    print(f"Removed the account and {len(items) + len(left)} items.")
    print("A session that was open can still change data for up to 1 hour, and anything it creates is left behind.")
    print(f"To be sure, run this again in an hour:  scripts/remove_user.py {sub} --yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
