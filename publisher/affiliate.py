from __future__ import annotations

import re
from urllib.parse import urlencode

AMAZON_ASSOCIATE_TAG = "blackboxia92-21"
AMAZON_DOMAIN = "www.amazon.es"
_ASIN = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def amazon_url(asin: str) -> str:
    """Return a canonical Amazon detail link with the required Associate tag."""
    cleaned = asin.strip().upper()
    if not _ASIN.fullmatch(cleaned):
        raise ValueError(f"Invalid Amazon ASIN/ISBN-10: {asin!r}")
    return f"https://{AMAZON_DOMAIN}/dp/{cleaned}?{urlencode({'tag': AMAZON_ASSOCIATE_TAG})}"


def assert_required_tag(configured_tag: str | None) -> None:
    """Prevent accidental publication with a missing or substituted tag."""
    if configured_tag and configured_tag != AMAZON_ASSOCIATE_TAG:
        raise ValueError(
            f"AMAZON_ASSOCIATE_TAG must be exactly {AMAZON_ASSOCIATE_TAG!r}."
        )

