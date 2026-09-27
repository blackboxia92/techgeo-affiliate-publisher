"""Product invariants used to block accidental legacy regressions."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .metrics import catalog_metrics, intentional_hub_paths
from .schema import load_page
from .v2 import adapt_legacy_page


@dataclass(frozen=True)
class RegressionReport:
    commercial_pages: int
    legacy_indexable_pages: int
    indexable_pages: int
    legacy_affiliate_url_count: int
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
    metrics = catalog_metrics(rows)
    indexable = [(page, raw) for page, raw in rows if page.indexable]
    legacy_indexable = [(page, raw) for page, raw in indexable if raw.get("content_model") != "v2"]
    commercial = [page for page, _ in rows if page.is_commercial]
    routes = [f"/guides/{page.slug}/" for page, _ in indexable]
    legacy_routes = [f"/guides/{page.slug}/" for page, _ in legacy_indexable]
    affiliate_urls: list[str] = []
    legacy_affiliate_urls: list[str] = []
    for page, raw in indexable:
        model = adapt_legacy_page(page, raw)
        destinations = [model.resource_url(resource) for resource in page.resources]
        if page.recommendation:
            destinations.append(model.recommendation_url() or "")
        affiliate_urls.extend(destinations)
        if raw.get("content_model") != "v2":
            legacy_affiliate_urls.extend(destinations)

    failures: list[str] = []
    for field, actual in (
        ("reviewed_guides", metrics.reviewed_guides),
        ("commercial_pages", metrics.commercial_pages),
        ("legacy_indexable_pages", len(legacy_indexable)),
        ("indexable_pages", len(indexable)),
        ("legacy_affiliate_url_count", len(legacy_affiliate_urls)),
        ("affiliate_url_count", metrics.affiliate_routes),
        ("sitemap_hubs", metrics.sitemap_hubs),
        ("legacy_indexable_url_sha256", _digest(legacy_routes)),
        ("legacy_affiliate_url_sha256", _digest(legacy_affiliate_urls)),
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
        actual_sitemap_urls = {node.findtext("s:loc", default="", namespaces=namespace) for node in sitemap_urls}
        expected_sitemap_urls = {
            f"{base_url}/guides/{page.slug}/" for page, _ in indexable
        } | {f"{base_url}{path}" for path in intentional_hub_paths(rows)}
        if len(actual_sitemap_urls) != expected["sitemap_urls"]:
            failures.append(f"sitemap URL count changed: expected {expected['sitemap_urls']}, got {len(actual_sitemap_urls)}")
        if actual_sitemap_urls != expected_sitemap_urls:
            failures.append("sitemap contains a URL outside the intentional indexable page and hub set")

    return RegressionReport(
        len(commercial), len(legacy_indexable), len(indexable), len(legacy_affiliate_urls), len(affiliate_urls), tuple(failures)
    )
