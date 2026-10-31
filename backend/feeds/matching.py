"""Does a keyword rule match a deal?

Keyword syntax (a plain keyword, with none of the marks below, is one phrase, as it always was):
- `OLED TV`: the words next to each other, in that order.
- `"Pro Max" -case`: quoted phrases must each appear anywhere in the deal; `-word` or `-"two words"` must not appear.
- `TV -mount -"wall mount"`: the plain words (`TV`) are one phrase, the exclusions rule deals out. A `-` only marks an
  exclusion before a letter (`-15` and `-5%` are plain text), and a quote only opens a phrase at the start of a word
  (`55" OLED` is plain text). The plain words are always one phrase, even when a quoted phrase sits between them.
"""

import functools
import re
from typing import Any, NamedTuple

_TOKEN = re.compile(r'(?<!\S)(-?)"([^"]*)"|(\S+)')  # a quoted phrase starts a word; any other word is taken as it is
_EXCLUDING = re.compile(r"-[^\W\d_]")
_CURLY_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"'})  # a phone's "smart" quotes


class Terms(NamedTuple):
    wanted: tuple[str, ...]  # phrases that must all appear (case-folded)
    unwanted: tuple[str, ...]  # phrases that must not appear


@functools.lru_cache(maxsize=512)  # the same few keywords are read for every deal of every run
def parse_keyword(keyword: str) -> Terms | None:
    """The phrases a keyword asks for and rules out, or None when it can't be read: an unclosed or empty quote, or nothing to
    look for (only exclusions)."""
    wanted: list[str] = []
    unwanted: list[str] = []
    plain: list[str] = []
    for match in _TOKEN.finditer(keyword.casefold().translate(_CURLY_QUOTES)):
        dash, quoted, word = match.groups()
        if word is None:  # a quoted phrase, with or without a leading dash
            phrase = " ".join(quoted.split())
            if not phrase:
                return None
            (unwanted if dash else wanted).append(phrase)
        elif word.startswith('"') or word.startswith('-"'):  # a quote that is never closed
            return None
        elif _EXCLUDING.match(word):
            unwanted.append(word[1:])
        else:
            plain.append(word)
    if plain:
        wanted.insert(0, " ".join(plain))
    return Terms(tuple(wanted), tuple(unwanted)) if wanted else None


def same_keyword(a: str, b: str) -> bool:
    """Two keywords that ask for the same thing (case, spacing, quote style and the order of terms don't matter)."""
    ta, tb = parse_keyword(a), parse_keyword(b)
    if ta is None or tb is None:
        return " ".join(a.casefold().split()) == " ".join(b.casefold().split())
    return (sorted(ta.wanted), sorted(ta.unwanted)) == (sorted(tb.wanted), sorted(tb.unwanted))


def _found(phrase: str, text: str) -> bool:
    """The phrase as whole words (a plural "s" or "es" is fine: "headphone" matches "headphones", "box" matches "boxes")."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?:e?s)?(?!\w)", text) is not None


def matches(rule: dict[str, Any], deal: dict[str, Any], source: str) -> bool:
    """The rule is on, listens to this source, the price (if the rule has a ceiling) fits, and the keyword is in the title,
    store or category (see the syntax above).
    """
    if not rule.get("enabled", True) or source not in rule.get("sources", []):
        return False
    ceiling = rule.get("maxPrice")
    if ceiling is not None and (deal["price"] is None or deal["price"] > ceiling):
        return False
    text = " ".join(part for part in (deal["title"], deal.get("retailer"), deal.get("category")) if part).casefold()
    # A keyword that can't be read (only exclusions, say, saved by hand) still works as one plain phrase.
    terms = parse_keyword(rule["keyword"]) or Terms((" ".join(rule["keyword"].casefold().split()),), ())
    return all(_found(p, text) for p in terms.wanted) and not any(_found(p, text) for p in terms.unwanted)
