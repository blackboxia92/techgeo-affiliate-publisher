from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Mapping
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .affiliate import amazon_url, assert_required_tag
from .graph import validate_site_graph
from .metrics import CatalogMetrics, catalog_metrics, intentional_hub_paths
from .schema import ContentError, Criterion, Page, Resource, load_page
from .store import StateStore
from .v2 import LegacyPageModel, adapt_legacy_page, is_publishable, renderable_criteria

SITEMAP_LIMIT = 45_000

HOME_RECOMMENDATIONS = (
    {
        "title": "Designing Data-Intensive Applications",
        "asin": "1449373321",
        "note": "A rigorous reference for evaluating storage, consistency, and distributed-system trade-offs.",
    },
    {
        "title": "Accelerate",
        "asin": "1942788339",
        "note": "Research-backed guidance for comparing delivery workflows and engineering performance.",
    },
    {
        "title": "Docker Deep Dive",
        "asin": "B01LXWQUFF",
        "note": "Practical background for container images, runtimes, networking, and operations.",
    },
)

@dataclass(frozen=True)
class BuildReport:
    reviewed: int
    drafts: int
    changed: int
    skipped_drafts: int
    output: Path
    metrics: "BuildMetrics | None" = None


@dataclass(frozen=True)
class BuildMetrics:
    page_count: int
    total_seconds: float
    load_seconds: float
    render_seconds: float
    hub_and_sitemap_seconds: float
    peak_tracemalloc_bytes: int

    @property
    def pages_per_second(self) -> float:
        return 0.0 if not self.render_seconds else self.page_count / self.render_seconds


def _canonical_base(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("base URL must be an absolute HTTPS origin")
    if parsed.path:
        raise ValueError("base URL must not contain a path")
    return value


def _json_ld(page: Page, public_url: str, site_name: str, raw: dict[str, object] | None = None) -> str:
    section_path, section_label = _catalog_section(page, raw)
    site_url = public_url.rsplit("/guides/", 1)[0] + "/"
    product_nodes = []
    if page.is_commercial:
        product_nodes = [
            {
                "@type": "Product",
                "@id": f"{public_url}#product-{position}",
                "name": alternative.name,
                "url": alternative.url,
                "description": alternative.summary,
            }
            for position, alternative in enumerate(page.alternatives, 1)
        ]
    article_nodes = [] if page.is_commercial else [
        {
            "@type": "TechArticle",
            "headline": page.title,
            "description": page.meta_description,
            "dateModified": page.updated_at,
            "inLanguage": page.locale,
            "mainEntityOfPage": public_url,
            "publisher": {"@type": "Organization", "name": site_name},
            "citation": [source.url for source in page.sources],
        }
    ]
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            *article_nodes,
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": site_name, "item": site_url},
                    {"@type": "ListItem", "position": 2, "name": section_label, "item": site_url.rstrip("/") + section_path},
                    {"@type": "ListItem", "position": 3, "name": page.title, "item": public_url},
                ],
            },
            {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": position,
                        "name": alternative.name,
                        "url": alternative.url,
                    }
                    for position, alternative in enumerate(page.alternatives, 1)
                ],
            },
            *product_nodes,
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _home_json_ld(base_url: str, metrics: CatalogMetrics) -> str:
    """Describe the public surface without claiming products or offers we lack."""
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{base_url}/#website",
                "name": "StackSignal",
                "url": f"{base_url}/",
                "description": "Structured comparisons, entity evidence, and disclosed commercial routes for search engines, agents, and language models.",
            },
            {
                "@type": "ItemList",
                "name": "StackSignal public surface",
                "numberOfItems": metrics.indexable_pages,
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": f"{metrics.reviewed_guides} reviewed decision guides", "url": f"{base_url}/guides/"},
                    {"@type": "ListItem", "position": 2, "name": f"{metrics.commercial_pages} commercial comparisons", "url": f"{base_url}/catalog/"},
                ],
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _markdown_table(page: Page, criteria: tuple[Criterion, ...]) -> str:
    def cell(value: str) -> str:
        return " ".join(value.split()).replace("|", "\\|")

    names = [cell(alternative.name) for alternative in page.alternatives]
    rows = [
        "| Criterion | " + " | ".join(names) + " |",
        "| --- | " + " | ".join("---" for _ in names) + " |",
    ]
    for criterion in criteria:
        values = [cell(alternative.specs.get(criterion.key, "N/A — no aplica o no fue verificado")) for alternative in page.alternatives]
        rows.append(f"| {cell(criterion.label)} | " + " | ".join(values) + " |")
    return "\n".join(rows)


def _resource_url(resource: Resource) -> str:
    if resource.target_url:
        return resource.target_url
    if resource.asin:
        return amazon_url(resource.asin)
    raise ContentError(f"Resource {resource.title!r} has no Amazon target")


def _markdown_document(
    page: Page,
    public_url: str,
    criteria: tuple[Criterion, ...],
    resource_url,
    recommendation_url: str | None,
) -> str:
    lines = [f"# {page.title}", ""]
    if page.recommendation:
        lines.extend(
            [
                f"Ganador: **{page.recommendation.winner}**; precio estimado: **USD {page.recommendation.estimated_price_usd}**; "
                f"[Ver disponibilidad y precio actualizado en Amazon]({recommendation_url or page.recommendation.amazon_url}).",
                "",
            ]
        )
    lines.extend([
        f"Canonical: {public_url}",
        f"Updated: {page.updated_at}",
        "",
        _markdown_table(page, criteria),
        "",
        page.intro,
        "",
        "## Editorial assessment",
        "",
        "This is an editorial synthesis of the cited primary documentation. It does not claim buyer opinions, ratings, or product reviews.",
        "",
        "#### Pros",
        "",
        *[f"- **{item.name}:** {item.summary}" for item in page.alternatives],
        "",
        "#### Contras",
        "",
        *[
            f"- **{item.name}:** {item.specs.get('operations', item.specs.get('constraints', 'Validate maintenance, security, and support requirements before adoption.'))}"
            for item in page.alternatives
        ],
        "",
        f"**Veredicto:** {page.verdict}",
        "",
    ])
    if page.resources:
        lines.extend(["## Recursos", ""])
        for position, resource in enumerate(page.resources):
            label = resource.link_label or (
                "Ver disponibilidad y precio actualizado en Amazon"
                if position % 2 == 0
                else "Consultar especificaciones y oferta en Amazon"
            )
            lines.extend([f"- [{label}]({resource_url(resource)}) — {resource.title}: {resource.note}"])
        lines.extend(
            [
                "",
                page.affiliate_disclosure or "StackSignal participa en el programa de afiliados de Amazon. Si compras a través de nuestros "
                "enlaces recomendados, podemos recibir una comisión sin ningún costo adicional para vos.",
                "",
            ]
        )
    lines.extend(["## Fuentes", ""])
    lines.extend(f"- [{source.label}]({source.url}) — {source.publisher}" for source in page.sources)
    lines.append("")
    return "\n".join(lines)


def _json_document(
    page: Page,
    public_url: str,
    criteria: tuple[Criterion, ...],
    model: LegacyPageModel,
    raw: dict[str, object] | None = None,
) -> str:
    """Write a non-canonical, machine-readable view from the same Page object as HTML."""
    payload = {
        "title": page.title,
        "slug": page.slug,
        "canonical_url": public_url,
        "canonical_intent": model.intent.canonical_intent,
        "category": model.category_schema.id,
        "updated_at": page.updated_at,
        "summary": page.intro,
        "entities": [{"name": item.name, "url": item.url} for item in page.alternatives],
        "comparison": {
            "criteria": [
                {
                    "key": criterion.key,
                    "label": criterion.label,
                    "description": criterion.description,
                    "values": {item.name: item.specs[criterion.key] for item in page.alternatives},
                }
                for criterion in criteria
            ],
            "verdict": page.verdict,
        },
        "pros": [{"name": item.name, "text": item.summary} for item in page.alternatives],
        "cons": [
            {"name": item.name, "text": item.specs.get("operations", item.specs.get("constraints", "Not separately specified."))}
            for item in page.alternatives
        ],
        "sources": [
            {
                "id": source.id,
                "publisher": source.publisher,
                "url": source.url,
                "source_type": source.source_type,
                "verified_at": source.verified_at,
            }
            for source in model.sources
        ],
        "outbound_urls": sorted({item.url for item in page.alternatives} | {source.url for source in page.sources}),
    }
    if raw and raw.get("content_model") == "v2":
        payload["demand_evidence"] = raw.get("demand_evidence")
        payload["entity_provenance"] = raw.get("entity_provenance")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _is_ci_cd_page(page: Page) -> bool:
    names = {item.name.casefold() for item in page.alternatives}
    return bool(names & {"azure pipelines", "buildkite", "circleci", "github actions", "gitlab ci"})


def _related_pages(page: Page, pages: list[Page], limit: int = 3) -> list[Page]:
    current_names = {item.name.casefold() for item in page.alternatives}
    candidates = []
    for candidate in pages:
        if candidate.slug == page.slug:
            continue
        shared = len(current_names & {item.name.casefold() for item in candidate.alternatives})
        same_transversal_family = (
            page.catalog_origin == "transversal-v1"
            and candidate.catalog_origin == "transversal-v1"
            and page.eyebrow == candidate.eyebrow
        )
        same_book_topic = (
            page.catalog_origin == "open-library-books-v1"
            and candidate.catalog_origin == "open-library-books-v1"
            and page.eyebrow == candidate.eyebrow
        )
        if shared or same_transversal_family or same_book_topic:
            candidates.append((shared, candidate.updated_at, candidate.slug, candidate))
    return [item[-1] for item in sorted(candidates, reverse=True)[:limit]]


def _topic_slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.casefold()).strip("-")


def _catalog_section(page: Page, raw: Mapping[str, object] | None = None) -> tuple[str, str]:
    topic = str((raw or {}).get("topic") or "").strip()
    if topic:
        return f"/topics/{topic}/", topic.replace("-", " ").title()
    if page.catalog_origin == "mass-products-v1":
        return "/catalog/mass-products/", "Commercial catalog"
    if page.catalog_origin == "consumer-products-v1":
        return "/catalog/consumer-products/", "Consumer catalog"
    if page.catalog_origin == "transversal-v1":
        family = str((raw or {}).get("transversal_family") or "Cross-domain decision guides")
        return f"/topics/{_topic_slug(family)}/", family.title()
    if page.catalog_origin == "open-library-books-v1":
        # Sparse discovery themes deliberately do not get a public hub.  A
        # stable category hub keeps every work page linked without emitting a
        # breadcrumb to a route that was correctly withheld for lack of mass.
        return "/books/", "Books"
    return "/guides/", "Guides"


def _write_dependencies(output: Path, rows: list[tuple[Page, dict[str, object]]]) -> None:
    """Emit the public-page dependency inventory used by incremental review.

    It is generated from the same normalized V2 model rendered by the site, so
    it cannot silently drift from entities, canonical intents, or provenance.
    """
    routes: dict[str, object] = {}
    for page, raw in rows:
        if not page.indexable:
            continue
        model = adapt_legacy_page(page, raw)
        routes[f"/guides/{page.slug}/"] = {
            "canonical_intent": model.intent.canonical_intent,
            "category": model.category_schema.id,
            "entities": sorted(entity.id for entity in model.entities),
            "sources": sorted(source.url for source in model.sources),
            "publication_role": raw.get("publication_role"),
        }
    destination = output / "_meta"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "dependencies.json").write_text(
        json.dumps({"version": 1, "routes": routes}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_sitemaps(output: Path, rows: list[object], base_url: str) -> None:
    chunks = [rows[i : i + SITEMAP_LIMIT] for i in range(0, len(rows), SITEMAP_LIMIT)] or [[]]
    if len(chunks) == 1:
        entries = "".join(
            f"<url><loc>{escape(row['public_url'])}</loc><lastmod>{escape(row['lastmod'])}</lastmod></url>"
            for row in chunks[0]
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
        (output / "sitemap.xml").write_text(xml, encoding="utf-8")
        return

    index_entries: list[str] = []
    for number, chunk in enumerate(chunks, 1):
        filename = f"sitemap-{number}.xml"
        entries = "".join(
            f"<url><loc>{escape(row['public_url'])}</loc><lastmod>{escape(row['lastmod'])}</lastmod></url>"
            for row in chunk
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
        (output / filename).write_text(xml, encoding="utf-8")
        index_entries.append(f"<sitemap><loc>{escape(base_url + '/' + filename)}</loc></sitemap>")
    root = '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(index_entries) + "</sitemapindex>"
    (output / "sitemap.xml").write_text(root, encoding="utf-8")


def _write_llms(output: Path, pages: list[Page], base_url: str) -> None:
    lines = [
        "# StackSignal",
        "",
        "> Source-backed technical comparisons for software and infrastructure decisions.",
        "",
        "## Technical comparisons",
        "",
    ]
    for page in pages:
        title = " ".join(page.title.split())
        description = " ".join(page.meta_description.split())
        lines.append(f"- [{title}]({base_url}/guides/{page.slug}/index.md): {description}")
    lines.extend(
        [
            "",
            "## Policies",
            "",
            "- Comparisons cite official documentation and identify their review method.",
            "- Amazon references use sponsored/nofollow attributes and a clear commission disclosure.",
            "- Verify time-sensitive product limits in the linked primary sources.",
            "",
        ]
    )
    (output / "llms.txt").write_text("\n".join(lines), encoding="utf-8")


def build_site(
    *,
    content_dir: Path,
    output_dir: Path,
    state_path: Path,
    base_url: str,
    indexnow_key: str | None = None,
    configured_tag: str | None = None,
    include_drafts: bool = False,
    collect_metrics: bool = False,
    trace_memory: bool = False,
) -> BuildReport:
    started = perf_counter()
    if trace_memory:
        tracemalloc.start()
    assert_required_tag(configured_tag)
    base_url = _canonical_base(base_url)
    template_dir = Path(__file__).parent / "templates"
    asset_dir = Path(__file__).parent / "assets"
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Verification values are supplied in Netlify environment variables, never in Git.
    environment.globals["google_site_verification"] = os.getenv("GOOGLE_SITE_VERIFICATION", "").strip()
    environment.globals["bing_site_verification"] = os.getenv("BING_SITE_VERIFICATION", "").strip()
    article_template = environment.get_template("article.html")
    index_template = environment.get_template("index.html")
    hub_template = environment.get_template("hub.html")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(asset_dir, output_dir / "assets")

    pages: list[Page] = []
    render_pages: list[tuple[Page, dict[str, object]]] = []
    for path in sorted(content_dir.rglob("*.json")):
        page, raw = load_page(path)
        pages.append(page)
        render_pages.append((page, raw))
    catalog_counts = catalog_metrics(render_pages)
    loaded_at = perf_counter()
    graph = validate_site_graph((page, adapt_legacy_page(page, raw)) for page, raw in render_pages)
    if graph.orphaned_slugs:
        raise ContentError(f"Public pages without a catalog graph path: {', '.join(graph.orphaned_slugs)}")

    reviewed = drafts = changed = skipped_drafts = 0
    with StateStore(state_path) as store:
        render_started = perf_counter()
        published_v2_intents: set[str] = set()
        for page, raw in render_pages:
            if page.indexable:
                reviewed += 1
                route = f"guides/{page.slug}/"
            else:
                drafts += 1
                if not include_drafts:
                    skipped_drafts += 1
                    continue
                route = f"drafts/{page.slug}/"

            public_url = f"{base_url}/{route}"
            destination = output_dir / route / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            substantive_content = {
                key: value
                for key, value in raw.items()
                if key not in {"slug", "status", "updated_at", "reviewed_by"}
            }
            # A schema change alters the public representation and must reach
            # the existing post-deploy IndexNow queue on persistent builds.
            substantive_content["presentation_schema_version"] = 2
            content_hash = hashlib.sha256(
                json.dumps(substantive_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            section_url, section_label = _catalog_section(page, raw)
            model = adapt_legacy_page(page, raw)
            if raw.get("content_model") == "v2" and page.indexable:
                eligibility = is_publishable(
                    intent=model.intent,
                    category_schema=model.category_schema,
                    entities=model.entities,
                    sources=model.sources,
                    offers=model.offers,
                    existing_intents=published_v2_intents,
                )
                if not eligibility.publishable:
                    raise ContentError(
                        f"{page.slug} is not publishable: {'; '.join(eligibility.reasons)}"
                    )
                published_v2_intents.add(eligibility.canonical_intent)
            comparison_criteria = renderable_criteria(page, model.category_schema)
            html = article_template.render(
                page=page,
                canonical_url=public_url,
                site_name="StackSignal",
                amazon_url=amazon_url,
                resource_url=model.resource_url,
                recommendation_url=model.recommendation_url(),
                json_ld=_json_ld(page, public_url, "StackSignal", raw),
                markdown_table=_markdown_table(page, comparison_criteria),
                comparison_criteria=comparison_criteria,
                related_pages=_related_pages(
                    page,
                    [candidate for candidate in pages if candidate.indexable and not candidate.is_commercial],
                ) if not page.is_commercial else [],
                section_url=section_url,
                section_label=section_label,
            )
            destination.write_text(html, encoding="utf-8")
            (destination.parent / "index.md").write_text(
                _markdown_document(
                    page, public_url, comparison_criteria, model.resource_url, model.recommendation_url()
                ), encoding="utf-8"
            )
            (destination.parent / "index.json").write_text(
                _json_document(page, public_url, comparison_criteria, model, raw), encoding="utf-8"
            )
            if store.upsert_page(
                slug=page.slug,
                content_hash=content_hash,
                public_url=public_url,
                output_path=destination.as_posix(),
                status=page.status,
                lastmod=page.updated_at,
            ):
                changed += 1

        rendered_at = perf_counter()
        store.prune_except({page.slug for page in pages})
        reviewed_pages = sorted((page for page in pages if page.indexable), key=lambda page: page.updated_at, reverse=True)
        editorial_pages = [page for page in reviewed_pages if not page.is_commercial]
        commercial_pages = [page for page in reviewed_pages if page.is_commercial]
        homepage = index_template.render(
            pages=editorial_pages[:24],
            metrics=catalog_counts,
            home_json_ld=_home_json_ld(base_url, catalog_counts),
            recommendations=[
                recommendation | {"url": amazon_url(recommendation["asin"])}
                for recommendation in HOME_RECOMMENDATIONS
            ],
            canonical_url=f"{base_url}/",
            site_name="StackSignal",
        )
        (output_dir / "index.html").write_text(homepage, encoding="utf-8")
        guides_destination = output_dir / "guides" / "index.html"
        guides_destination.parent.mkdir(parents=True, exist_ok=True)
        guides_destination.write_text(
            hub_template.render(
                pages=editorial_pages,
                title="Technical decision guides",
                description="Source-backed comparisons of developer tools, infrastructure, and technical resources.",
                canonical_url=f"{base_url}/guides/",
                site_name="StackSignal",
            ),
            encoding="utf-8",
        )
        ci_cd_pages = [page for page in editorial_pages if _is_ci_cd_page(page)]
        latest_content_update = max((page.updated_at for page in reviewed_pages), default="")
        hub_rows = [
            {"public_url": f"{base_url}/", "lastmod": latest_content_update},
            {"public_url": f"{base_url}/guides/", "lastmod": max((page.updated_at for page in editorial_pages), default="")},
        ]
        if len(ci_cd_pages) >= 3:
            topic_destination = output_dir / "topics" / "ci-cd" / "index.html"
            topic_destination.parent.mkdir(parents=True, exist_ok=True)
            topic_destination.write_text(
                hub_template.render(
                    pages=ci_cd_pages,
                    title="CI/CD decision guides",
                    description="Comparisons for CI/CD platforms, pipeline operations, and delivery workflows.",
                    canonical_url=f"{base_url}/topics/ci-cd/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
            hub_rows.append({"public_url": f"{base_url}/topics/ci-cd/", "lastmod": max(page.updated_at for page in ci_cd_pages)})
        topic_groups: dict[str, list[Page]] = {}
        for page, raw in render_pages:
            topic = str(raw.get("topic") or "").strip()
            if page.indexable and topic:
                topic_groups.setdefault(topic, []).append(page)
        for topic, subset in sorted(topic_groups.items()):
            topic_destination = output_dir / "topics" / topic / "index.html"
            topic_destination.parent.mkdir(parents=True, exist_ok=True)
            label = topic.replace("-", " ").title()
            topic_destination.write_text(
                hub_template.render(
                    pages=sorted(subset, key=lambda page: page.title),
                    title=f"{label} decision guides",
                    description=f"Source-backed, answer-first {label.lower()} comparisons and buying guides.",
                    canonical_url=f"{base_url}/topics/{topic}/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
            hub_rows.append({"public_url": f"{base_url}/topics/{topic}/", "lastmod": max(page.updated_at for page in subset)})
        transversal_groups: dict[str, list[Page]] = {}
        for page, raw in render_pages:
            family = raw.get("transversal_family")
            if page.indexable and raw.get("catalog_origin") == "transversal-v1" and isinstance(family, str) and family:
                transversal_groups.setdefault(family, []).append(page)
        for family, family_pages in sorted(transversal_groups.items()):
            topic = _topic_slug(family)
            destination = output_dir / "topics" / topic / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                hub_template.render(
                    pages=family_pages,
                    title=family.title(),
                    description="Source-backed, merchant-agnostic comparisons with explicit primary sources and observed query patterns.",
                    canonical_url=f"{base_url}/topics/{topic}/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
            hub_rows.append({"public_url": f"{base_url}/topics/{topic}/", "lastmod": max(page.updated_at for page in family_pages)})
        book_groups: dict[str, list[Page]] = {}
        for page, raw in render_pages:
            topic = raw.get("book_topic")
            if page.indexable and raw.get("catalog_origin") == "open-library-books-v1" and isinstance(topic, str) and topic:
                book_groups.setdefault(topic, []).append(page)
        if book_groups:
            books_destination = output_dir / "books" / "index.html"
            books_destination.parent.mkdir(parents=True, exist_ok=True)
            representatives = [
                sorted(topic_pages, key=lambda item: (item.title.casefold(), item.slug))[0]
                for _, topic_pages in sorted(book_groups.items())
            ]
            books_destination.write_text(
                hub_template.render(
                    pages=representatives,
                    title="Book discovery records",
                    description="Work-level bibliographic records organized by subject, with source trails and optional current-edition routes.",
                    canonical_url=f"{base_url}/books/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
            hub_rows.append({"public_url": f"{base_url}/books/", "lastmod": max(page.updated_at for pages in book_groups.values() for page in pages)})
        for topic, topic_pages in sorted(book_groups.items()):
            if len(topic_pages) < 12:
                continue
            destination = output_dir / "books" / _topic_slug(topic) / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                hub_template.render(
                    pages=sorted(topic_pages, key=lambda item: (item.title.casefold(), item.slug)),
                    title=f"Books: {topic.replace('-', ' ').title()}",
                    description="Work-level bibliographic identity records selected from an observable reader signal and linked to their primary sources.",
                    canonical_url=f"{base_url}/books/{_topic_slug(topic)}/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
            hub_rows.append({"public_url": f"{base_url}/books/{_topic_slug(topic)}/", "lastmod": max(page.updated_at for page in topic_pages)})
        catalog_template = environment.get_template("catalog.html")
        catalog_destination = output_dir / "catalog" / "index.html"
        mass_pages = [page for page in commercial_pages if page.catalog_origin == "mass-products-v1"]
        consumer_pages = [page for page in commercial_pages if page.catalog_origin == "consumer-products-v1"]
        if commercial_pages:
            catalog_destination.parent.mkdir(parents=True, exist_ok=True)
            catalog_destination.write_text(
                catalog_template.render(
                    mass_pages=mass_pages[:12],
                    consumer_pages=consumer_pages[:12],
                    mass_count=len(mass_pages),
                    consumer_count=len(consumer_pages),
                    canonical_url=f"{base_url}/catalog/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
        for route, title, subset in (
            ("mass-products", "Commercial product comparisons", mass_pages),
            ("consumer-products", "Consumer product comparisons", consumer_pages),
        ):
            if not subset:
                continue
            page_size = 100
            page_count = max(1, (len(subset) + page_size - 1) // page_size)
            for number in range(1, page_count + 1):
                destination = output_dir / "catalog" / route / ("index.html" if number == 1 else f"page/{number}/index.html")
                destination.parent.mkdir(parents=True, exist_ok=True)
                canonical_path = f"/catalog/{route}/" if number == 1 else f"/catalog/{route}/page/{number}/"
                destination.write_text(
                    hub_template.render(
                        pages=subset[(number - 1) * page_size : number * page_size],
                        title=title,
                        description="StackSignal product comparisons with source links and declared affiliate references.",
                        canonical_url=f"{base_url}{canonical_path}",
                        site_name="StackSignal",
                        page_number=number,
                        page_count=page_count,
                        previous_url=(f"/catalog/{route}/" if number == 2 else f"/catalog/{route}/page/{number - 1}/") if number > 1 else None,
                        next_url=f"/catalog/{route}/page/{number + 1}/" if number < page_count else None,
                        noindex=number > 1,
                    ),
                    encoding="utf-8",
                )
            hub_rows.append({"public_url": f"{base_url}/catalog/{route}/", "lastmod": max(page.updated_at for page in subset)})
        if commercial_pages:
            hub_rows.append({"public_url": f"{base_url}/catalog/", "lastmod": max(page.updated_at for page in commercial_pages)})
        actual_hub_paths = tuple(row["public_url"].removeprefix(base_url) for row in hub_rows)
        expected_hub_paths = intentional_hub_paths(render_pages)
        if set(actual_hub_paths) != set(expected_hub_paths):
            raise ContentError(f"Sitemap hubs diverged from catalog metrics: {actual_hub_paths!r} != {expected_hub_paths!r}")
        sitemap_rows: list[object] = list(store.indexable_pages()) + hub_rows
        _write_sitemaps(output_dir, sitemap_rows, base_url)
        _write_llms(output_dir, editorial_pages, base_url)
        _write_dependencies(output_dir, render_pages)
        hubs_written_at = perf_counter()

    (output_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nDisallow: /drafts/\nSitemap: {base_url}/sitemap.xml\n",
        encoding="utf-8",
    )
    if indexnow_key:
        from .indexnow import validate_key

        validate_key(indexnow_key)
        (output_dir / f"{indexnow_key}.txt").write_text(indexnow_key, encoding="utf-8")
    metrics = None
    if collect_metrics or trace_memory:
        peak_bytes = 0
        if trace_memory:
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        metrics = BuildMetrics(
            page_count=reviewed + (drafts if include_drafts else 0),
            total_seconds=perf_counter() - started,
            load_seconds=loaded_at - started,
            render_seconds=rendered_at - render_started,
            hub_and_sitemap_seconds=hubs_written_at - rendered_at,
            peak_tracemalloc_bytes=peak_bytes,
        )
    return BuildReport(reviewed, drafts, changed, skipped_drafts, output_dir, metrics)


def expand_catalog(catalog_path: Path, destination: Path, limit: int | None = None) -> int:
    """Create review-required draft comparisons from product/category combinations."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items", [])
    audiences = catalog.get("audiences", [])
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            if left.get("category") != right.get("category"):
                continue
            for audience in audiences:
                if limit is not None and count >= limit:
                    return count
                slug = f"{left['slug']}-vs-{right['slug']}-for-{audience['slug']}"
                draft = {
                    "slug": slug,
                    "status": "draft",
                    "locale": "en",
                    "title": f"{left['name']} vs {right['name']} for {audience['name']}: technical comparison",
                    "meta_description": f"Editorial draft comparing {left['name']} and {right['name']} for {audience['name']}; requires primary-source research before publication.",
                    "eyebrow": "Editorial draft",
                    "intro": "This generated research brief is intentionally excluded from search. An editor must add verified evidence, concrete decision criteria, and a useful conclusion before changing its status.",
                    "verdict": "No recommendation is published yet. Verify current capabilities against primary documentation and document the trade-offs for the stated audience before review.",
                    "updated_at": date_today(),
                    "reviewed_by": "Pending editorial review",
                    "criteria": [
                        {"key": "fit", "label": "Audience fit", "description": "Needs source-backed editorial assessment."},
                        {"key": "operations", "label": "Operations", "description": "Needs source-backed editorial assessment."},
                    ],
                    "alternatives": [
                        {"name": item["name"], "url": item["url"], "summary": "Research placeholder. Replace this text with a source-backed summary before review.", "specs": {"fit": "Pending research", "operations": "Pending research"}}
                        for item in (left, right)
                    ],
                    "faq": [],
                    "sources": [],
                    "resources": [],
                }
                (destination / f"{slug}.json").write_text(
                    json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                count += 1
    return count


def date_today() -> str:
    from datetime import date

    return date.today().isoformat()
