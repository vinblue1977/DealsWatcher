"""The Dealnews deals feed: public RSS at dealnews.com/?rss=1 (its robots.txt allows it; polled every 30 minutes)."""

import hashlib
import re
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree  # noqa: S405 - bodies with a DOCTYPE or ENTITY are refused before parsing

FEED_URL = "https://www.dealnews.com/?rss=1"
USER_AGENT = "DealsWatcher/1.0 (personal deal alerts; +https://github.com/vinblue1977/DealsWatcher)"
MAX_BYTES = 2_000_000
_PRICE = re.compile(r"\d{1,5}(\.\d{1,2})?")
_UNSAFE_XML = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
# The feed's own fields (price, retailer, category) live in this namespace; title, link, guid and pubDate are plain RSS.
_NS = "{https://www.dealnews.com/ns/rss/1.0.htm}"


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is treated as an error: the feed has one fixed address."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def fetch() -> bytes:
    request = urllib.request.Request(  # noqa: S310 - one fixed https address
        FEED_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"}
    )
    with _OPENER.open(request, timeout=10) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("feed is larger than expected")
    return body


def _own_link(link: str) -> bool:
    parts = urlsplit(link)
    host = parts.hostname or ""
    ours = host == "dealnews.com" or host.endswith(".dealnews.com")
    return parts.scheme == "https" and not parts.username and not parts.password and ours


def _price(text: str | None) -> Decimal | None:
    if text is None or not _PRICE.fullmatch(text):
        return None
    amount = Decimal(text)
    return amount if amount > 0 else None


def parse(body: bytes) -> list[dict[str, Any]]:
    """Deals as plain dicts, in feed order (newest first). Items that are incomplete or link elsewhere are skipped."""
    # NUL bytes or a byte-order mark mean UTF-16/32, where the check below would not see a DOCTYPE; the feed is plain UTF-8.
    if b"\x00" in body or body.startswith((b"\xfe\xff", b"\xff\xfe")) or _UNSAFE_XML.search(body):
        raise ValueError("feed uses XML features we refuse to parse")
    deals = []
    for item in ElementTree.fromstring(body).iter("item"):  # noqa: S314 - see the import
        field = {child.tag: (child.text or "").strip() for child in item}  # keyed by full name: another namespace can't overwrite
        title, link, guid = field.get("title", ""), field.get("link", ""), field.get("guid", "")
        try:
            published = parsedate_to_datetime(field.get("pubDate", "")).astimezone(UTC)
        except TypeError, ValueError:
            continue
        if not (title and guid and _own_link(link)):
            continue
        deals.append(
            {
                "id": hashlib.sha256(guid.encode()).hexdigest()[:12],
                "title": title[:300],
                "url": link,
                "price": _price(field.get(_NS + "price")),
                "retailer": field.get(_NS + "retailer", "")[:60] or None,
                "category": field.get(_NS + "category", "")[:60] or None,
                "published": published,
            }
        )
    return deals


def age_limit(now: datetime, deals: list[dict[str, Any]], hours: int) -> list[dict[str, Any]]:
    """Deals published within the last `hours` (and not in the future)."""
    return [d for d in deals if 0 <= (now - d["published"]).total_seconds() <= hours * 3600]
