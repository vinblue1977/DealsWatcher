"""The Dealnews feeds: public RSS, polled every 30 minutes. Its robots.txt allows it and its RSS page says they are free to use.

Each feed lists only its latest ~50 deals, so the main feed alone misses deals that scroll off it: the category, popular and
editors' feeds add deals the main one no longer shows. The links in the feeds are used unchanged.
"""

import hashlib
import re
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree  # noqa: S405 - bodies with a DOCTYPE or ENTITY are refused before parsing

MAIN_FEED = "https://www.dealnews.com/?rss=1"  # the latest deals
BLACK_FRIDAY_FEED = "https://www.dealnews.com/f1676/Black-Friday/?rss=1"  # store-wide sales, mostly without a price
MOST_POPULAR_FEED = "https://www.dealnews.com/?rss=1&sort=hotness"
STAFF_PICK_FEED = "https://www.dealnews.com/f1682/Staff-Pick/?rss=1"  # the editors' choice
ELECTRONICS_FEED = "https://www.dealnews.com/c142/Electronics/?rss=1"
COMPUTERS_FEED = "https://www.dealnews.com/c39/Computers/?rss=1"
CLOTHING_FEED = "https://www.dealnews.com/c202/Clothing-Accessories/?rss=1"
HOME_GARDEN_FEED = "https://www.dealnews.com/c196/Home-Garden/?rss=1"
FEEDS = (
    MAIN_FEED,
    BLACK_FRIDAY_FEED,
    MOST_POPULAR_FEED,
    STAFF_PICK_FEED,
    ELECTRONICS_FEED,
    COMPUTERS_FEED,
    CLOTHING_FEED,
    HOME_GARDEN_FEED,
)
REQUIRED = (MAIN_FEED,)  # the others are extras (Black Friday is seasonal): if one fails, that is logged, not an error
USER_AGENT = "DealsWatcher/1.0 (personal deal alerts; +https://github.com/vinblue1977/DealsWatcher)"
MAX_BYTES = 2_000_000
_PRICE = re.compile(r"\d{1,5}(\.\d{1,2})?")
# A dollar amount in a title: "$199", "$1,099.99". Used only when the feed gives no price (see _title_price). Anything that
# makes it look like something else ("$1.99k", "$5%", "$2 million") is not an amount we trust.
_DOLLARS = re.compile(r"\$(\d{1,3}(?:,\d{3})+|\d{1,5})(\.\d{2})?(?![\w%]|\.\d|,\d)")
# Amounts that are not the price of the thing. Right after the amount: "$35+", "$5/mo", "$20 off", "$5.99 shipping". Within the
# next few words: "$100 Best Buy gift card", "$10 Kohl's Cash", "$25 in rewards". Right before it: "save $20", "orders over $50".
_AFTER_TOUCHING = re.compile(r"[+/]")
_AFTER_NEXT = re.compile(
    r"\s*(off(?![\w-])|shipping|delivery|tax|fees?|per\b|a month|monthly|purchase|orders?|spend|discounts?|less\b|more\b)", re.I
)
_AFTER_NEARBY = re.compile(r"\b(gift|e-?gift|credit|credits|cash|rewards?|coupons?|rebates?|bonus(es)?|points|promo)\b", re.I)
_BEFORE_WORDS = "save|saves|saved|saving|over|under|up to|spend|minimum|min\\.?|orders?|above|below|with|extra|earn|win"
_NOT_A_PRICE_BEFORE = re.compile(rf"\b({_BEFORE_WORDS})\s*$", re.I)
_UNSAFE_XML = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
# The feed's own fields (price, retailer, category) live in this namespace; title, link, guid and pubDate are plain RSS.
_NS = "{https://www.dealnews.com/ns/rss/1.0.htm}"


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is treated as an error: each feed has one fixed address."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def fetch(url: str) -> bytes:
    """One of FEEDS. Anything else is refused, so this can only ever reach the addresses listed above."""
    if url not in FEEDS:
        raise ValueError("not a known feed")
    # The Accept list ends with */*: on 2026-10-30 the Black Friday feed answered 406 Not Acceptable to a list of only RSS and XML
    # types (same User-Agent; with */* added it answered 200). The body is still checked to be XML below.
    request = urllib.request.Request(  # noqa: S310 - only the fixed https addresses in FEEDS
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.1"}
    )
    with _OPENER.open(request, timeout=10) as response:
        if not response.headers.get_content_type().endswith("xml"):  # an HTML 200 (a challenge or consent page) is not a feed
            raise ValueError("feed is not XML")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("feed is larger than expected")
    return body


def _own_link(link: str) -> bool:
    parts = urlsplit(link)
    host = parts.hostname or ""
    ours = host == "dealnews.com" or host.endswith(".dealnews.com")
    return parts.scheme == "https" and not parts.username and not parts.password and ours


def _deal_id(guid: str) -> str:
    """The same deal has the same id in every feed: feeds tag its guid differently (?iref=rss, ?iref=rss-f1676)."""
    parts = urlsplit(guid)
    return hashlib.sha256(f"{parts.netloc}{parts.path}".encode()).hexdigest()[:12]


def _price(text: str | None) -> Decimal | None:
    if text is None or not _PRICE.fullmatch(text):
        return None
    amount = Decimal(text)
    return amount if amount > 0 else None


def _title_price(title: str) -> Decimal | None:
    """The price named in a title, only when it is clear: exactly one dollar amount is left once amounts that are not the
    price (discounts, gift cards, shipping, spending thresholds, monthly payments) are set aside. "was $299, now $199" or
    "from $299 to $199" have two, so no price is guessed. A harmless "$0 shipping" is not counted.
    """
    amounts = set()
    for match in _DOLLARS.finditer(title):
        after = title[match.end() :]
        nearby = " ".join(after.split()[:3])  # the next three words
        if (
            _AFTER_TOUCHING.match(after)
            or _AFTER_NEXT.match(after)
            or _AFTER_NEARBY.search(nearby)
            or _NOT_A_PRICE_BEFORE.search(title[: match.start()])
        ):
            continue
        if amount := _price(match.group(1).replace(",", "") + (match.group(2) or "")):
            amounts.add(amount)
    return amounts.pop() if len(amounts) == 1 else None


def parse(body: bytes) -> list[dict[str, Any]]:
    """Deals as plain dicts, in feed order (newest first). Items that are incomplete or link elsewhere are skipped."""
    # NUL bytes or a byte-order mark mean UTF-16/32, where the check below would not see a DOCTYPE; the feed is plain UTF-8.
    if b"\x00" in body or body.startswith((b"\xfe\xff", b"\xff\xfe")) or _UNSAFE_XML.search(body):
        raise ValueError("feed uses XML features we refuse to parse")
    deals = []
    for item in ElementTree.fromstring(body).iter("item"):  # noqa: S314 - see the import
        field = {child.tag: (child.text or "").strip() for child in item}  # keyed by full name: another namespace can't overwrite
        title, link, guid = field.get("title", ""), field.get("link", ""), field.get("guid", "")
        feed_price = _price(field.get(_NS + "price"))
        try:
            published = parsedate_to_datetime(field.get("pubDate", "")).astimezone(UTC)
        except TypeError, ValueError:
            continue
        if not (title and guid and _own_link(link)):
            continue
        deals.append(
            {
                "id": _deal_id(guid),
                "title": title[:300],
                "url": link,
                "price": feed_price or _title_price(title),  # the feed's own price wins
                "price_from_title": feed_price is None,  # a guess: a later feed's own price replaces it (see the checker)
                "retailer": field.get(_NS + "retailer", "")[:60] or None,
                "category": field.get(_NS + "category", "")[:60] or None,
                "published": published,
            }
        )
    return deals


def age_limit(now: datetime, deals: list[dict[str, Any]], hours: int) -> list[dict[str, Any]]:
    """Deals published within the last `hours` (and not in the future)."""
    return [d for d in deals if 0 <= (now - d["published"]).total_seconds() <= hours * 3600]
