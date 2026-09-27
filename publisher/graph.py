"""Logical crawl graph validation for static StackSignal output."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schema import Page
from .v2 import LegacyPageModel


@dataclass(frozen=True)
class SiteGraphReport:
    categories: int
    entities: int
    intent_pages: int
    orphaned_slugs: tuple[str, ...]


def validate_site_graph(rows: Iterable[tuple[Page, LegacyPageModel]]) -> SiteGraphReport:
    """Verify every public page has a category path and stable entity links.

    The current production graph is intentionally conservative: guides are
    reached from `/guides/` (and CI/CD from its topic), commercial pages from
    their catalog hubs. Entity routes remain a future page type, so their
    relationships are validated here rather than invented as public URLs.
    """
    categories: set[str] = set()
    entities: set[str] = set()
    orphaned: list[str] = []
    pages = 0
    for page, model in rows:
        if not page.indexable:
            continue
        pages += 1
        categories.add(model.category_schema.id)
        entities.update(entity.id for entity in model.entities)
        if page.is_commercial and page.catalog_origin not in {"mass-products-v1", "consumer-products-v1"}:
            orphaned.append(page.slug)
    return SiteGraphReport(len(categories), len(entities), pages, tuple(sorted(orphaned)))
