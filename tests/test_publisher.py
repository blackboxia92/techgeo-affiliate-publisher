from __future__ import annotations

import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from publisher.affiliate import AMAZON_ASSOCIATE_TAG, amazon_url, assert_required_tag
from publisher.builder import build_site, expand_catalog
from publisher.indexnow import notify_indexnow
from publisher.schema import load_page
from publisher.weekly import generate_weekly_pages


PROJECT = Path(__file__).parents[1]


class AffiliateTests(unittest.TestCase):
    def test_required_tag_is_injected(self) -> None:
        url = amazon_url("1449373321")
        self.assertEqual(parse_qs(urlparse(url).query)["tag"], [AMAZON_ASSOCIATE_TAG])

    def test_wrong_tag_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_required_tag("different-20")


class BuildTests(unittest.TestCase):
    @staticmethod
    def reviewed_fixture_count() -> int:
        return sum(
            1
            for path in (PROJECT / "content" / "pages").rglob("*.json")
            if load_page(path)[0].indexable
        )

    def test_reviewed_pages_are_indexed_and_amazon_links_are_disclosed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = build_site(
                content_dir=PROJECT / "content" / "pages",
                output_dir=root / "dist",
                state_path=root / "data" / "state.sqlite3",
                base_url="https://guides.example",
            )
            self.assertEqual(report.reviewed, self.reviewed_fixture_count())
            self.assertEqual(report.drafts, 0)
            html = (root / "dist" / "guides" / "postgresql-vs-sqlite-backend" / "index.html").read_text(encoding="utf-8")
            self.assertIn("tag=blackboxia92-21", html)
            self.assertNotIn("paid link", html.lower())
            self.assertNotIn("enlace de pago", html.lower())
            self.assertNotIn("comprar aquí", html.lower())
            self.assertIn("Ver disponibilidad y precio actualizado en Amazon", html)
            self.assertIn('rel="sponsored nofollow noopener"', html)
            disclosure = "StackSignal participa en el programa de afiliados de Amazon. Si compras a través de nuestros enlaces recomendados, podemos recibir una comisión sin ningún costo adicional para vos."
            self.assertIn(disclosure, html)
            self.assertIn("As an Amazon Associate I earn from qualifying purchases.", html)
            self.assertLess(html.index('class="rag-comparison"'), html.index('class="article-hero"'))
            self.assertIn("| Criterion | PostgreSQL | SQLite |", html)
            self.assertIn("Consenso Real de Compradores (Pros, Contras y Veredicto)", html)
            self.assertIn("No se atribuyen opiniones, calificaciones ni consenso de compradores sin evidencia verificable.", html)
            sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("postgresql-vs-sqlite-backend", sitemap)
            self.assertNotIn("/drafts/", sitemap)
            ET.fromstring(sitemap)
            payload = re.search(
                r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
            )
            self.assertIsNotNone(payload)
            structured_data = json.loads(payload.group(1))
            self.assertEqual(structured_data["@context"], "https://schema.org")
            products = [node for node in structured_data["@graph"] if "Product" in node.get("@type", [])]
            self.assertEqual(len(products), 2)
            self.assertTrue(all(product["review"]["@type"] == "Review" for product in products))
            self.assertTrue(all("reviewRating" not in product["review"] for product in products))
            self.assertTrue(all("aggregateRating" not in product for product in products))
            self.assertTrue((root / "dist" / "library" / "page" / "1" / "index.html").exists())
            llms = (root / "dist" / "llms.txt").read_text(encoding="utf-8")
            self.assertIn("postgresql-vs-sqlite-backend", llms)
            homepage = (root / "dist" / "index.html").read_text(encoding="utf-8")
            self.assertEqual(homepage.count("tag=blackboxia92-21"), 3)
            self.assertEqual(homepage.count('rel="sponsored nofollow noopener"'), 3)
            self.assertIn('data-associate-tag="blackboxia92-21"', homepage)
            self.assertNotIn("paid link", homepage.lower())
            self.assertIn("Ver disponibilidad y precio actualizado en Amazon", homepage)
            self.assertIn("Consultar especificaciones y oferta en Amazon", homepage)
            self.assertIn(disclosure, homepage)

            hardware_slug = "raspberry-pi-5-vs-intel-nuc-13-pro-for-bootstrapped-saas-limited-space"
            hardware_dir = root / "dist" / "guides" / hardware_slug
            hardware_html = (hardware_dir / "index.html").read_text(encoding="utf-8")
            hardware_markdown = (hardware_dir / "index.md").read_text(encoding="utf-8")
            self.assertIn("Amazon Renewed / Enterprise Usado", hardware_html)
            self.assertIn("tag=blackboxia92-21", hardware_html)
            self.assertRegex(
                hardware_html,
                r"Ganador:.*precio estimado: USD 240;.*Ver disponibilidad y precio actualizado en Amazon",
            )
            self.assertIn("Canal de Memoria (Single/Dual)", hardware_markdown)
            self.assertIn("Límite de RAM Real", hardware_markdown)
            self.assertIn("Consumo en reposo (Watts)", hardware_markdown)

    def test_expanded_draft_is_noindex_and_excluded_from_sitemap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drafts = root / "content"
            created = expand_catalog(PROJECT / "content" / "catalog.json", drafts, limit=1)
            self.assertEqual(created, 1)
            report = build_site(
                content_dir=drafts,
                output_dir=root / "dist",
                state_path=root / "data" / "state.sqlite3",
                base_url="https://guides.example",
                include_drafts=True,
            )
            self.assertEqual(report.drafts, 1)
            draft_file = next((root / "dist" / "drafts").rglob("index.html"))
            html = draft_file.read_text(encoding="utf-8")
            self.assertIn('content="noindex,nofollow"', html)
            sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertNotIn("/drafts/", sitemap)

    def test_indexnow_dry_run_lists_only_changed_reviewed_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "data" / "state.sqlite3"
            build_site(
                content_dir=PROJECT / "content" / "pages",
                output_dir=root / "dist",
                state_path=state,
                base_url="https://guides.example",
                indexnow_key="12345678abcdefgh",
            )
            result = notify_indexnow(
                state_path=state,
                base_url="https://guides.example",
                key="12345678abcdefgh",
                dry_run=True,
            )
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["pending"], self.reviewed_fixture_count())

    def test_catalog_expansion_scales_pairwise_by_audience(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = {
                "items": [
                    {"name": f"Tool {i}", "slug": f"tool-{i}", "category": "x", "url": f"https://example.com/{i}"}
                    for i in range(10)
                ],
                "audiences": [{"name": f"Audience {i}", "slug": f"audience-{i}"} for i in range(25)],
            }
            catalog_path = root / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            created = expand_catalog(catalog_path, root / "drafts")
            self.assertEqual(created, 1125)
            self.assertEqual(len(list((root / "drafts").glob("*.json"))), 1125)

    def test_weekly_generation_creates_distinct_batches_with_affiliate_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = generate_weekly_pages(PROJECT / "content" / "catalog.json", root / "pages", limit=20)
            second = generate_weekly_pages(PROJECT / "content" / "catalog.json", root / "pages", limit=20)
            self.assertEqual(first.created, 20)
            self.assertEqual(second.created, 20)
            self.assertTrue(set(first.slugs).isdisjoint(second.slugs))
            report = build_site(
                content_dir=root / "pages",
                output_dir=root / "dist",
                state_path=root / "state.sqlite3",
                base_url="https://guides.example",
                configured_tag="blackboxia92-21",
            )
            self.assertEqual(report.reviewed, 40)
            pages = list((root / "dist" / "guides").rglob("index.html"))
            self.assertEqual(len(pages), 40)
            self.assertTrue(all("tag=blackboxia92-21" in page.read_text(encoding="utf-8") for page in pages))
            self.assertEqual((root / "dist" / "llms.txt").read_text(encoding="utf-8").count("/guides/"), 40)


if __name__ == "__main__":
    unittest.main()
