from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

AMAZON_ASSOCIATE_TAG = "blackboxia92-21"
AMAZON_DOMAIN = "www.amazon.es"
_ASIN = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def amazon_url(asin: str) -> str:
    """Return a canonical Amazon detail link with the required Associate tag."""
    cleaned = asin.strip().upper()
    if not _ASIN.fullmatch(cleaned):
        raise ValueError(f"Invalid Amazon ASIN/ISBN-10: {asin!r}")
    return f"https://{AMAZON_DOMAIN}/dp/{cleaned}?{urlencode({'tag': AMAZON_ASSOCIATE_TAG})}"


def amazon_search_url(query: str) -> str:
    """Return a tagged Amazon search link for products without a stable ASIN."""
    cleaned = " ".join(query.split())
    if len(cleaned) < 3:
        raise ValueError("Amazon search query must contain at least three characters")
    return f"https://{AMAZON_DOMAIN}/s?{urlencode({'k': cleaned, 'tag': AMAZON_ASSOCIATE_TAG})}"


def validate_amazon_target(url: str) -> str:
    """Accept only HTTPS Amazon.es links carrying the configured Associate tag."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {AMAZON_DOMAIN, "amazon.es"}:
        raise ValueError("Amazon target must be an HTTPS amazon.es URL")
    if parse_qs(parsed.query).get("tag") != [AMAZON_ASSOCIATE_TAG]:
        raise ValueError(f"Amazon target must include tag={AMAZON_ASSOCIATE_TAG}")
    return url


def assert_required_tag(configured_tag: str | None) -> None:
    """Prevent accidental publication with a missing or substituted tag."""
    if configured_tag and configured_tag != AMAZON_ASSOCIATE_TAG:
        raise ValueError(
            f"AMAZON_ASSOCIATE_TAG must be exactly {AMAZON_ASSOCIATE_TAG!r}."
        )
