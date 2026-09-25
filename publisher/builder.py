from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .affiliate import amazon_url, assert_required_tag
from .schema import ContentError, Page, load_page
from .store import StateStore

SITEMAP_LIMIT = 45_000


@dataclass(frozen=True)
class BuildReport:
    reviewed: int
    drafts: int
    changed: int
    skipped_drafts: int
    output: Path


def _canonical_base(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("base URL must be an absolute HTTPS origin")
    if parsed.path:
        raise ValueError("base URL must not contain a path")
    return value


def _json_ld(page: Page, public_url: str, site_name: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "TechArticle",
                "headline": page.title,
                "description": page.meta_description,
                "dateModified": page.updated_at,
                "inLanguage": page.locale,
                "mainEntityOfPage": public_url,
                "publisher": {"@type": "Organization", "name": site_name},
                "citation": [source.url for source in page.sources],
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
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item.question,
                        "acceptedAnswer": {"@type": "Answer", "text": item.answer},
                    }
                    for item in page.faq
                ],
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


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
        lines.append(f"- [{title}]({base_url}/guides/{page.slug}/): {description}")
    lines.extend(
        [
            "",
            "## Policies",
            "",
            "- Comparisons cite official documentation and identify their review method.",
            "- Amazon links are marked as paid links and use sponsored/nofollow attributes.",
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
) -> BuildReport:
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
    article_template = environment.get_template("article.html")
    index_template = environment.get_template("index.html")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(asset_dir, output_dir / "assets")

    pages: list[Page] = []
    reviewed = drafts = changed = skipped_drafts = 0
    with StateStore(state_path) as store:
        for path in sorted(content_dir.rglob("*.json")):
            page, raw = load_page(path)
            pages.append(page)
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
            content_hash = hashlib.sha256(
                json.dumps(substantive_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            html = article_template.render(
                page=page,
                canonical_url=public_url,
                site_name="StackSignal",
                amazon_url=amazon_url,
                json_ld=_json_ld(page, public_url, "StackSignal"),
            )
            destination.write_text(html, encoding="utf-8")
            if store.upsert_page(
                slug=page.slug,
                content_hash=content_hash,
                public_url=public_url,
                output_path=destination.as_posix(),
                status=page.status,
                lastmod=page.updated_at,
            ):
                changed += 1

        store.prune_except({page.slug for page in pages})
        reviewed_pages = sorted((page for page in pages if page.indexable), key=lambda page: page.updated_at, reverse=True)
        homepage = index_template.render(
            pages=reviewed_pages[:24],
            total_pages=len(reviewed_pages),
            canonical_url=f"{base_url}/",
            site_name="StackSignal",
        )
        (output_dir / "index.html").write_text(homepage, encoding="utf-8")
        library_template = environment.get_template("library.html")
        page_size = 100
        library_page_count = max(1, (len(reviewed_pages) + page_size - 1) // page_size)
        for number in range(1, library_page_count + 1):
            subset = reviewed_pages[(number - 1) * page_size : number * page_size]
            destination = output_dir / "library" / "page" / str(number) / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                library_template.render(
                    pages=subset,
                    page_number=number,
                    page_count=library_page_count,
                    canonical_url=f"{base_url}/library/page/{number}/",
                    site_name="StackSignal",
                ),
                encoding="utf-8",
            )
        latest = reviewed_pages[0].updated_at if reviewed_pages else date_today()
        sitemap_rows: list[object] = [
            {"public_url": f"{base_url}/", "lastmod": latest},
            *[
                {"public_url": f"{base_url}/library/page/{number}/", "lastmod": latest}
                for number in range(1, library_page_count + 1)
            ],
            *store.indexable_pages(),
        ]
        _write_sitemaps(output_dir, sitemap_rows, base_url)
        _write_llms(output_dir, reviewed_pages, base_url)

    (output_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nDisallow: /drafts/\nSitemap: {base_url}/sitemap.xml\n",
        encoding="utf-8",
    )
    if indexnow_key:
        from .indexnow import validate_key

        validate_key(indexnow_key)
        (output_dir / f"{indexnow_key}.txt").write_text(indexnow_key, encoding="utf-8")
    return BuildReport(reviewed, drafts, changed, skipped_drafts, output_dir)


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
