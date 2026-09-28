"""One build-time definition of StackSignal's public catalog metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .schema import Page
from .v2 import adapt_legacy_page, category_for_page


def _topic_slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.casefold()).strip("-")


@dataclass(frozen=True)
class CatalogMetrics:
    """Counts with explicit units; no presentation code owns its own totals."""

    reviewed_guides: int
    commercial_pages: int
    indexable_pages: int
    affiliate_routes: int
    entities: int
    sources: int
    mass_catalog_pages: int
    consumer_catalog_pages: int
    sitemap_hubs: int

    @property
    def sitemap_urls(self) -> int:
        return self.indexable_pages + self.sitemap_hubs


def _indexable_rows(rows: Iterable[tuple[Page, Mapping[str, object]]]) -> tuple[tuple[Page, Mapping[str, object]], ...]:
    return tuple((page, raw) for page, raw in rows if page.indexable)


def intentional_hub_paths(rows: Iterable[tuple[Page, Mapping[str, object]]]) -> tuple[str, ...]:
    """Indexable hub routes, deliberately excluding noindex pagination."""
    indexable = _indexable_rows(rows)
    paths = ["/", "/guides/"]
    if sum(category_for_page(page, raw) == "ci-cd" for page, raw in indexable) >= 3:
        paths.append("/topics/ci-cd/")
    topics = sorted({str(raw.get("topic")) for _, raw in indexable if raw.get("topic")})
    paths.extend(f"/topics/{topic}/" for topic in topics)
    transversal_families = {
        str(raw["transversal_family"])
        for page, raw in indexable
        if raw.get("catalog_origin") == "transversal-v1" and raw.get("transversal_family")
    }
    paths.extend(f"/topics/{_topic_slug(family)}/" for family in sorted(transversal_families))
    book_topics: dict[str, int] = {}
    for page, raw in indexable:
        topic = raw.get("book_topic")
        if page.catalog_origin == "open-library-books-v1" and isinstance(topic, str) and topic:
            book_topics[topic] = book_topics.get(topic, 0) + 1
    if book_topics:
        paths.append("/books/")
    # A topic becomes a public hub only once it can support useful discovery;
    # a singleton bibliographic record is linked through /guides/, not a hub.
    paths.extend(f"/books/{topic}/" for topic, count in sorted(book_topics.items()) if count >= 12)
    commercial = [page for page, _ in indexable if page.is_commercial]
    if commercial:
        paths.append("/catalog/")
    if any(page.catalog_origin == "mass-products-v1" for page in commercial):
        paths.append("/catalog/mass-products/")
    if any(page.catalog_origin == "consumer-products-v1" for page in commercial):
        paths.append("/catalog/consumer-products/")
    return tuple(paths)


def catalog_metrics(rows: Iterable[tuple[Page, Mapping[str, object]]]) -> CatalogMetrics:
    """Derive all visible/product-regression counts from source pages once."""
    indexable = _indexable_rows(rows)
    commercial = [(page, raw) for page, raw in indexable if page.is_commercial]
    models = [adapt_legacy_page(page, raw) for page, raw in indexable]
    return CatalogMetrics(
        reviewed_guides=sum(not page.is_commercial for page, _ in indexable),
        commercial_pages=len(commercial),
        indexable_pages=len(indexable),
        affiliate_routes=sum(len(model.affiliate_routes) for model in models),
        entities=len({entity.id for model in models for entity in model.entities}),
        sources=len({source.url for model in models for source in model.sources}),
        mass_catalog_pages=sum(page.catalog_origin == "mass-products-v1" for page, _ in commercial),
        consumer_catalog_pages=sum(page.catalog_origin == "consumer-products-v1" for page, _ in commercial),
        sitemap_hubs=len(intentional_hub_paths(indexable)),
    )
