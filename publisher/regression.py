"""Product invariants used to block accidental legacy regressions."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .schema import load_page
from .v2 import adapt_legacy_page


@dataclass(frozen=True)
class RegressionReport:
    commercial_pages: int
    indexable_pages: int
    affiliate_url_count: int
    failures: tuple[str, ...]


def _digest(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def validate_product_invariants(
    *,
    content_dir: Path,
    manifest_path: Path,
    output_dir: Path | None = None,
    base_url: str | None = None,
) -> RegressionReport:
    """Compare current data/output with the deliberately checked-in baseline."""
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [load_page(path) for path in sorted(content_dir.rglob("*.json"))]
    indexable = [(page, raw) for page, raw in rows if page.indexable]
    commercial = [page for page, _ in rows if page.is_commercial]
    routes = [f"/guides/{page.slug}/" for page, _ in indexable]
    affiliate_urls: list[str] = []
    for page, raw in rows:
        model = adapt_legacy_page(page, raw)
        affiliate_urls.extend(model.resource_url(resource) for resource in page.resources)
        if page.recommendation:
            affiliate_urls.append(model.recommendation_url() or "")

    failures: list[str] = []
    for field, actual in (
        ("commercial_pages", len(commercial)),
        ("indexable_pages", len(indexable)),
        ("affiliate_url_count", len(affiliate_urls)),
        ("indexable_url_sha256", _digest(routes)),
        ("affiliate_url_sha256", _digest(affiliate_urls)),
    ):
        if expected[field] != actual:
            failures.append(f"{field} changed: expected {expected[field]!r}, got {actual!r}")

    if output_dir is not None:
        if not base_url:
            raise ValueError("base_url is required when validating output")
        article_outputs = list((output_dir / "guides").glob("*/index.html"))
        if len(article_outputs) != len(indexable):
            failures.append(f"historical output count changed: expected {len(indexable)}, got {len(article_outputs)}")
        # Source hashes cover every legacy URL and affiliate route. Read a
        # deterministic cross-section of HTML instead of making every unit
        # run perform 4,000 disk reads; the production build itself writes all.
        sample_indexes = sorted({0, len(indexable) // 2, len(indexable) - 1})
        for index in sample_indexes:
            page, _ = indexable[index]
            document = output_dir / "guides" / page.slug / "index.html"
            if not document.exists():
                failures.append(f"missing historical output: {page.slug}")
                continue
            canonical = f'<link rel="canonical" href="{base_url}/guides/{page.slug}/">'
            if canonical not in document.read_text(encoding="utf-8"):
                failures.append(f"incorrect canonical: {page.slug}")
        sitemap = ET.parse(output_dir / "sitemap.xml").getroot()
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        sitemap_urls = sitemap.findall("s:url", namespace)
        if len(sitemap_urls) != expected["sitemap_urls"]:
            failures.append(f"sitemap URL count changed: expected {expected['sitemap_urls']}, got {len(sitemap_urls)}")

    return RegressionReport(len(commercial), len(indexable), len(affiliate_urls), tuple(failures))
