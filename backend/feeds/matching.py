"""Does a keyword rule match a deal?"""

import re
from typing import Any


def matches(rule: dict[str, Any], deal: dict[str, Any], source: str) -> bool:
    """The rule is on, listens to this source, the price (if the rule has a ceiling) fits, and the keyword is in the title,
    store or category as a whole word (a plural "s" or "es" is fine: "headphone" matches "headphones", "box" matches "boxes").
    """
    if not rule.get("enabled", True) or source not in rule.get("sources", []):
        return False
    ceiling = rule.get("maxPrice")
    if ceiling is not None and (deal["price"] is None or deal["price"] > ceiling):
        return False
    text = " ".join(part for part in (deal["title"], deal.get("retailer"), deal.get("category")) if part).casefold()
    return re.search(rf"(?<!\w){re.escape(rule['keyword'].casefold())}(?:e?s)?(?!\w)", text) is not None
