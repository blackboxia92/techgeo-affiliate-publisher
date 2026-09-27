"""Small, provenance-first external-feed ingestion pipeline.

The Google Books adapter is deliberately limited: it exercises real, imperfect
commercial records without creating public pages by itself. Publishing remains
the responsibility of the existing V2 eligibility gate.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .v2 import (
    AffiliateRoute,
    CATEGORY_SCHEMAS,
    Entity,
    Fact,
    Intent,
    Offer,
    Source,
    TemporalState,
    _identifier,
    canonical_intent_key,
    is_publishable,
)
from .lifecycle import update_history_ledger

GOOGLE_BOOKS_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"
OPEN_FOOD_FACTS_ENDPOINT = "https://us.openfoodfacts.org/api/v2/search"
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class RawExternalItem:
    source: str
    source_url: str
    retrieved_at: str
    batch_id: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class NormalizedCandidate:
    raw_id: str
    title: str
    brand: str | None
    model: str | None
    category: str
    identifiers: dict[str, str]
    entity: Entity
    offers: tuple[Offer, ...]
    routes: tuple[AffiliateRoute, ...]
    source: Source
    raw: RawExternalItem
    possible_duplicate: bool = False
    variant_key: str | None = None


@dataclass(frozen=True)
class IngestReport:
    source: str
    batch_id: str
    raw_items: int
    parsed: int
    rejected: int
    normalized: int
    duplicate_groups: int
    variants: int
    publishable: int
    active_offers: int
    entities: int
    errors: tuple[str, ...]
    quality: dict[str, float]
    lifecycle_records: int
    seconds: float


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = html.unescape(_TAGS.sub(" ", value))
    value = unicodedata.normalize("NFKC", value)
    value = _SPACE.sub(" ", value).strip()
    return value or None


def _valid_isbn13(value: str) -> bool:
    if not re.fullmatch(r"\d{13}", value):
        return False
    return sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(value)) % 10 == 0


def valid_gtin(value: str) -> bool:
    """Validate EAN/UPC/GTIN check digits without accepting arbitrary IDs."""
    if not re.fullmatch(r"\d{8}|\d{12,14}", value):
        return False
    return sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(value[:-1]))) % 10 == (10 - int(value[-1])) % 10


def _valid_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme == "https" and parsed.netloc else None


def _get_json(url: str) -> dict[str, Any]:
    """Small bounded retry for public feeds; never turn a transient 503 into data."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "StackSignal/2.2 (https://stacksignal-tech.netlify.app)"},
            )
            with urlopen(request, timeout=30) as response:  # nosec B310 - fixed HTTPS endpoints
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
            raise ValueError("feed response was not an object")
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    # Some managed Windows/Python environments reject public-feed TLS traffic
    # while their bundled curl succeeds. Keep this optional and bounded rather
    # than turning a transport quirk into invented data.
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        result = subprocess.run(
            [curl, "--fail", "--silent", "--show-error", "--max-time", "30", "-A", "StackSignal/2.2 (https://stacksignal-tech.netlify.app)", url],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                return payload
    raise RuntimeError(f"feed request failed after retries: {last_error}")


def _availability(saleability: str | None) -> str | None:
    if saleability in {"FOR_SALE", "FREE"}:
        return "active"
    if saleability in {"NOT_FOR_SALE", "FOR_PREORDER"}:
        return "temporarily_unavailable"
    return None


def normalize_google_book(item: RawExternalItem) -> NormalizedCandidate | None:
    """Normalize one real API response while retaining the complete raw row."""
    raw = item.raw
    volume = raw.get("volumeInfo") if isinstance(raw.get("volumeInfo"), dict) else {}
    sale = raw.get("saleInfo") if isinstance(raw.get("saleInfo"), dict) else {}
    raw_id = _clean_text(raw.get("id"))
    title = _clean_text(volume.get("title"))
    if not raw_id or not title:
        return None
    publisher = _clean_text(volume.get("publisher"))
    identifiers: dict[str, str] = {}
    for record in volume.get("industryIdentifiers", []):
        if not isinstance(record, dict):
            continue
        kind, value = _clean_text(record.get("type")), _clean_text(record.get("identifier"))
        if kind and value:
            identifiers[kind] = value
    isbn13 = identifiers.get("ISBN_13")
    valid_gtin = isbn13 if isbn13 and _valid_isbn13(isbn13) else None
    model = valid_gtin or identifiers.get("ISBN_10") or raw_id
    source = Source(
        id=f"google-books:{raw_id}", publisher="Google Books", url=f"https://www.googleapis.com/books/v1/volumes/{raw_id}",
        source_type="api", retrieved_at=item.retrieved_at, verified_at=item.retrieved_at,
    )
    facts = [
        Fact("model", model, source.id, item.retrieved_at),
        Fact("form", _clean_text(volume.get("printType")) or "BOOK", source.id, item.retrieved_at),
    ]
    page_count = volume.get("pageCount")
    if isinstance(page_count, int) and page_count > 0:
        facts.append(Fact("page_count", str(page_count), source.id, item.retrieved_at))
    entity_id = f"entity:google-books:{valid_gtin or raw_id}"
    entity = Entity(entity_id, "physical-or-digital-book", title, "consumer-product", tuple(facts))
    buy_link = _valid_url(sale.get("buyLink"))
    offers: list[Offer] = []
    routes: list[AffiliateRoute] = []
    if buy_link:
        price = sale.get("retailPrice") if isinstance(sale.get("retailPrice"), dict) else {}
        amount = price.get("amount") if isinstance(price.get("amount"), (int, float)) else None
        currency = _clean_text(price.get("currencyCode"))
        offer_id = f"offer:google-play:{raw_id}"
        offers.append(Offer(
            offer_id, entity_id, "google-play-books", buy_link,
            TemporalState(market=_clean_text(sale.get("country")), currency=currency, price=amount,
                          availability=_availability(_clean_text(sale.get("saleability"))), last_verified_at=item.retrieved_at),
        ))
        routes.append(AffiliateRoute(offer_id, "raw-only", "google-play-books", "raw-destination", None))
    return NormalizedCandidate(
        raw_id=raw_id, title=title, brand=publisher, model=model, category="consumer-product",
        identifiers=identifiers, entity=entity, offers=tuple(offers), routes=tuple(routes), source=source,
        raw=item, variant_key=valid_gtin or f"{_identifier(title)}:{_identifier(publisher or '')}",
    )


def deduplicate(candidates: Iterable[NormalizedCandidate]) -> tuple[list[NormalizedCandidate], int, int]:
    """Only merge exact valid ISBN-13 identifiers; ambiguity remains separate."""
    accepted: list[NormalizedCandidate] = []
    by_gtin: dict[str, NormalizedCandidate] = {}
    seen_variant: dict[str, int] = {}
    duplicate_groups = variants = 0
    for candidate in candidates:
        gtin = candidate.identifiers.get("GTIN") or candidate.identifiers.get("ISBN_13")
        if gtin and valid_gtin(gtin):
            if gtin in by_gtin:
                duplicate_groups += 1
                continue
            by_gtin[gtin] = candidate
        elif candidate.variant_key:
            seen_variant[candidate.variant_key] = seen_variant.get(candidate.variant_key, 0) + 1
            if seen_variant[candidate.variant_key] > 1:
                variants += 1
                candidate = replace(candidate, possible_duplicate=True)
        accepted.append(candidate)
    return accepted, duplicate_groups, variants


def quality_metrics(candidates: Iterable[NormalizedCandidate]) -> dict[str, float]:
    rows = tuple(candidates)
    if not rows:
        return {key: 0.0 for key in ("brand", "model", "gtin", "source_url", "offer", "price", "availability", "affiliate_url", "useful_facts", "possible_duplicate")}
    total = len(rows)
    def percent(value: int) -> float:
        return round(value * 100 / total, 2)
    return {
        "brand": percent(sum(bool(row.brand) for row in rows)),
        "model": percent(sum(bool(row.model) for row in rows)),
        "gtin": percent(sum(any(valid_gtin(value) for value in row.identifiers.values()) for row in rows)),
        "source_url": percent(sum(bool(row.source.url) for row in rows)),
        "offer": percent(sum(bool(row.offers) for row in rows)),
        "price": percent(sum(any(offer.temporal_state.price is not None for offer in row.offers) for row in rows)),
        "availability": percent(sum(any(offer.temporal_state.availability is not None for offer in row.offers) for row in rows)),
        "affiliate_url": percent(sum(any(route.affiliate_url for route in row.routes) for row in rows)),
        "useful_facts": percent(sum(len(row.entity.facts) >= 2 for row in rows)),
        "possible_duplicate": percent(sum(row.possible_duplicate for row in rows)),
    }


def publication_count(candidates: Iterable[NormalizedCandidate]) -> int:
    """Apply the normal V2 gate; no feed adapter may bypass it."""
    count = 0
    for candidate in candidates:
        intent = Intent(
            "entity", (candidate.entity.id,), None,
            canonical_intent_key(category=candidate.category, intent_type="entity", entity_ids=(candidate.entity.id,)),
        )
        result = is_publishable(
            intent=intent, category_schema=CATEGORY_SCHEMAS[candidate.category],
            entities=(candidate.entity,), sources=(candidate.source,), offers=candidate.offers,
        )
        count += int(result.publishable)
    return count


def fetch_google_books(*, query: str, limit: int, batch_id: str) -> list[RawExternalItem]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    retrieved_at = _now()
    rows: list[RawExternalItem] = []
    for start in range(0, limit, 40):
        request_url = f"{GOOGLE_BOOKS_ENDPOINT}?q={query.replace(' ', '+')}&startIndex={start}&maxResults={min(40, limit - start)}"
        payload = _get_json(request_url)
        for raw in payload.get("items", []):
            if isinstance(raw, dict):
                raw_id = _clean_text(raw.get("id")) or "unknown"
                rows.append(RawExternalItem("google-books-api", f"https://www.googleapis.com/books/v1/volumes/{raw_id}", retrieved_at, batch_id, raw))
    return rows[:limit]


def ingest_google_books(*, query: str, limit: int, output_dir: Path, batch_id: str | None = None, history_path: Path | None = None) -> IngestReport:
    """Fetch, preserve raw input, normalize and report without publishing URLs."""
    started = time.perf_counter()
    batch_id = batch_id or f"google-books-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    raw_rows = fetch_google_books(query=query, limit=limit, batch_id=batch_id)
    parsed = [candidate for row in raw_rows if (candidate := normalize_google_book(row)) is not None]
    accepted, duplicate_groups, variants = deduplicate(parsed)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw.json").write_text(json.dumps([asdict(row) for row in raw_rows], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "normalized.json").write_text(json.dumps([asdict(row) for row in accepted], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = update_history_ledger(history_path, entity_ids=(row.entity.id for row in accepted), offers=(offer for row in accepted for offer in row.offers), observed_at=raw_rows[0].retrieved_at) if history_path and raw_rows else {}
    report = IngestReport(
        source="google-books-api", batch_id=batch_id, raw_items=len(raw_rows), parsed=len(parsed), rejected=len(raw_rows) - len(parsed),
        normalized=len(accepted), duplicate_groups=duplicate_groups, variants=variants, publishable=publication_count(accepted),
        active_offers=sum(offer.temporal_state.availability == "active" for row in accepted for offer in row.offers),
        entities=len(accepted), errors=(), quality=quality_metrics(accepted), lifecycle_records=len(ledger), seconds=round(time.perf_counter() - started, 3),
    )
    (output_dir / "report.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def normalize_openfoodfacts(item: RawExternalItem) -> NormalizedCandidate | None:
    raw = item.raw
    code = _clean_text(raw.get("code"))
    title = _clean_text(raw.get("product_name"))
    if not code or not title:
        return None
    brand = _clean_text(raw.get("brands"))
    packaging = _clean_text(raw.get("packaging")) or _clean_text(raw.get("quantity"))
    source = Source(
        id=f"openfoodfacts:{code}", publisher="Open Food Facts", url=f"https://us.openfoodfacts.org/api/v2/product/{code}.json",
        source_type="api", retrieved_at=item.retrieved_at, verified_at=item.retrieved_at,
    )
    identifiers = {"GTIN": code} if valid_gtin(code) else {"raw_code": code}
    facts = [Fact("model", code, source.id, item.retrieved_at)]
    if packaging:
        facts.append(Fact("form", packaging, source.id, item.retrieved_at))
    categories = raw.get("categories_tags")
    if isinstance(categories, list) and categories:
        category = _clean_text(categories[0])
        if category:
            facts.append(Fact("source_category", category, source.id, item.retrieved_at))
    entity = Entity(f"entity:openfoodfacts:{code}", "physical-product", title, "consumer-product", tuple(facts))
    return NormalizedCandidate(
        raw_id=code, title=title, brand=brand, model=code, category="consumer-product", identifiers=identifiers,
        entity=entity, offers=(), routes=(), source=source, raw=item,
        variant_key=f"{_identifier(title)}:{_identifier(brand or '')}",
    )


def fetch_openfoodfacts(*, limit: int, batch_id: str) -> list[RawExternalItem]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    retrieved_at = _now()
    rows: list[RawExternalItem] = []
    fields = "code,product_name,brands,categories_tags,packaging,quantity,last_modified_t,stores,image_url"
    for page in range(1, (limit + 99) // 100 + 1):
        request_url = f"{OPEN_FOOD_FACTS_ENDPOINT}?categories_tags_en=snacks&fields={fields}&sort_by=popularity_key&page_size=100&page={page}"
        payload = _get_json(request_url)
        for raw in payload.get("products", []):
            if isinstance(raw, dict):
                code = _clean_text(raw.get("code")) or "unknown"
                rows.append(RawExternalItem("openfoodfacts-api", f"https://us.openfoodfacts.org/api/v2/product/{code}.json", retrieved_at, batch_id, raw))
    return rows[:limit]


def ingest_openfoodfacts(*, limit: int, output_dir: Path, batch_id: str | None = None, history_path: Path | None = None) -> IngestReport:
    started = time.perf_counter()
    batch_id = batch_id or f"openfoodfacts-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    raw_rows = fetch_openfoodfacts(limit=limit, batch_id=batch_id)
    parsed = [candidate for row in raw_rows if (candidate := normalize_openfoodfacts(row)) is not None]
    accepted, duplicate_groups, variants = deduplicate(parsed)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw.json").write_text(json.dumps([asdict(row) for row in raw_rows], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "normalized.json").write_text(json.dumps([asdict(row) for row in accepted], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = update_history_ledger(history_path, entity_ids=(row.entity.id for row in accepted), offers=(), observed_at=raw_rows[0].retrieved_at) if history_path and raw_rows else {}
    report = IngestReport(
        source="openfoodfacts-api", batch_id=batch_id, raw_items=len(raw_rows), parsed=len(parsed), rejected=len(raw_rows) - len(parsed),
        normalized=len(accepted), duplicate_groups=duplicate_groups, variants=variants, publishable=publication_count(accepted),
        active_offers=0, entities=len(accepted), errors=(), quality=quality_metrics(accepted), lifecycle_records=len(ledger),
        seconds=round(time.perf_counter() - started, 3),
    )
    (output_dir / "report.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def compare_normalized_snapshots(previous: Path, current: Path) -> dict[str, int]:
    """Compare preserved normalized snapshots without treating absence as deletion."""
    before = json.loads(previous.read_text(encoding="utf-8"))
    after = json.loads(current.read_text(encoding="utf-8"))
    before_entities = {row["entity"]["id"] for row in before}
    after_entities = {row["entity"]["id"] for row in after}
    def offers(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {offer["id"]: offer for row in rows for offer in row.get("offers", [])}
    before_offers, after_offers = offers(before), offers(after)
    common = before_offers.keys() & after_offers.keys()
    return {
        "entity_new": len(after_entities - before_entities),
        "entity_missing": len(before_entities - after_entities),
        "offer_new": len(after_offers.keys() - before_offers.keys()),
        "offer_missing": len(before_offers.keys() - after_offers.keys()),
        "price_changed": sum(
            before_offers[key]["temporal_state"]["price"] != after_offers[key]["temporal_state"]["price"] for key in common
        ),
        "availability_changed": sum(
            before_offers[key]["temporal_state"]["availability"] != after_offers[key]["temporal_state"]["availability"] for key in common
        ),
        "destination_changed": sum(
            before_offers[key]["raw_destination_url"] != after_offers[key]["raw_destination_url"] for key in common
        ),
    }
