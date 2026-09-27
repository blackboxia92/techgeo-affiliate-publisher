from __future__ import annotations

import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from publisher.affiliate import AMAZON_ASSOCIATE_TAG, amazon_url, assert_required_tag, validate_affiliate_target
from publisher.builder import build_site, expand_catalog
from publisher.graph import validate_site_graph
from publisher.indexnow import notify_indexnow
from publisher.regression import validate_product_invariants
from publisher.schema import load_page
from publisher.store import StateStore
from publisher.v2 import (
    AffiliateRoute,
    CATEGORY_SCHEMAS,
    Entity,
    Fact,
    Intent,
    Offer,
    Source,
    TemporalState,
    adapt_legacy_page,
    canonical_intent_key,
    create_comparison,
    is_publishable,
    renderable_criteria,
    resolve_affiliate_link,
)
from publisher.weekly import generate_weekly_pages


PROJECT = Path(__file__).parents[1]


class AffiliateTests(unittest.TestCase):
    def test_required_tag_is_injected(self) -> None:
        url = amazon_url("1449373321")
        self.assertEqual(parse_qs(urlparse(url).query)["tag"], [AMAZON_ASSOCIATE_TAG])

    def test_wrong_tag_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_required_tag("different-20")

    def test_sovrn_target_is_preserved_and_unrelated_targets_are_rejected(self) -> None:
        self.assertEqual(validate_affiliate_target("https://sovrn.co/ngrip4g"), "https://sovrn.co/ngrip4g")
        with self.assertRaises(ValueError):
            validate_affiliate_target("https://www.walmart.com/ip/example")


class V2ModelTests(unittest.TestCase):
    def test_legacy_catalog_adapter_preserves_count_and_affiliate_routes(self) -> None:
        legacy_rows = [load_page(path) for path in (PROJECT / "content" / "pages").rglob("*.json")]
        pages = [page for page, _ in legacy_rows]
        commercial = [page for page in pages if page.is_commercial]
        self.assertEqual(len(commercial), 3957)

        page, raw = load_page(PROJECT / "content" / "pages" / "postgresql-vs-sqlite-backend.json")
        model = adapt_legacy_page(page, raw)
        self.assertTrue(model.entities)
        self.assertTrue(model.offers)
        self.assertTrue(model.affiliate_routes)
        self.assertNotEqual(model.entities[0].id, model.offers[0].id)
        self.assertEqual(model.resource_url(page.resources[0]), page.resources[0].target_url or amazon_url(page.resources[0].asin))
        self.assertIn(":comparison:", model.intent.canonical_intent)
        self.assertTrue(all(source.verified_at == page.updated_at for source in model.sources))
        for legacy_page, legacy_raw in legacy_rows:
            legacy_model = adapt_legacy_page(legacy_page, legacy_raw)
            for resource in legacy_page.resources:
                self.assertEqual(
                    legacy_model.resource_url(resource),
                    resource.target_url or amazon_url(resource.asin),
                )
            if legacy_page.recommendation:
                self.assertEqual(legacy_model.recommendation_url(), legacy_page.recommendation.amazon_url)

    def test_category_schema_removes_placeholders_without_erasing_hardware_facts(self) -> None:
        azure, raw = load_page(PROJECT / "content" / "pages" / "azure-pipelines-vs-buildkite-for-self-hosted-infrastructure.json")
        azure_keys = {criterion.key for criterion in renderable_criteria(azure, adapt_legacy_page(azure, raw).category_schema)}
        self.assertEqual(azure_keys, {"model", "operations", "fit", "audience"})
        self.assertNotIn("ram_limit", azure_keys)

        consumer_path = next((PROJECT / "content" / "pages" / "consumer").glob("*.json"))
        consumer, raw = load_page(consumer_path)
        consumer_keys = {criterion.key for criterion in renderable_criteria(consumer, adapt_legacy_page(consumer, raw).category_schema)}
        self.assertFalse({"memory_channel", "ram_limit", "idle_watts"} & consumer_keys)

        mass_path = next((PROJECT / "content" / "pages" / "mass").glob("*.json"))
        mass, raw = load_page(mass_path)
        mass_keys = {criterion.key for criterion in renderable_criteria(mass, adapt_legacy_page(mass, raw).category_schema)}
        self.assertTrue({"memory_channel", "ram_limit"} <= mass_keys)

    def test_draft_factory_requires_intent_inputs_and_never_writes_layout(self) -> None:
        draft = create_comparison(
            slug="alpha-vs-beta-for-teams",
            title="Alpha vs Beta for teams",
            category="software",
            audience="teams",
            alternatives=[{"name": "Alpha"}, {"name": "Beta"}],
            criteria=[{"key": "fit", "label": "Fit"}],
            sources=[{"url": "https://example.com"}],
        )
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["category"], "software")
        self.assertIn("canonical_intent", draft)

    def test_archetype_schemas_and_eligibility_are_explicit(self) -> None:
        self.assertTrue({"robot-vacuum", "ci-cd", "hotel"} <= set(CATEGORY_SCHEMAS))
        robot = CATEGORY_SCHEMAS["robot-vacuum"]
        hotel = CATEGORY_SCHEMAS["hotel"]
        self.assertTrue(robot.requires_offer)
        self.assertTrue(any(field.temporal for field in hotel.fields or ()))

        source = Source("source:roborock", "Roborock", "https://example.com/source", "official", verified_at="2026-09-26")
        entities = (
            Entity("entity:roborock-qrevo-s", "physical-product", "Roborock Qrevo S", "robot-vacuum", (
                Fact("navigation", "LiDAR", source.id, "2026-09-26"),
                Fact("mopping", "Supported", source.id, "2026-09-26"),
            )),
            Entity("entity:irobot-roomba", "physical-product", "iRobot Roomba", "robot-vacuum", (
                Fact("navigation", "Camera-based", source.id, "2026-09-26"),
                Fact("mopping", "Not supported", source.id, "2026-09-26"),
            )),
        )
        intent = Intent("comparison", tuple(item.id for item in entities), "pet hair", canonical_intent_key(
            category="robot-vacuum", intent_type="comparison", entity_ids=(item.id for item in entities), constraints={"use_case": "pet hair"}
        ))
        offers = (
            Offer(
                "offer:roborock:merchant-a", entities[0].id, "merchant-a", "https://merchant-a.example/p",
                TemporalState(market="US", currency="USD", price=499, availability="in_stock", last_verified_at="2026-09-26"),
            ),
            Offer(
                "offer:roborock:merchant-b", entities[0].id, "merchant-b", "https://merchant-b.example/p",
                TemporalState(market="US", currency="USD", price=479, availability="limited", last_verified_at="2026-09-26"),
            ),
        )
        route = AffiliateRoute("offer:roborock:merchant-a", "future-network", "merchant-a", "api", "https://affiliate.example/link")
        self.assertEqual(resolve_affiliate_link(offers[0], (route,)), "https://affiliate.example/link")
        self.assertNotIn("price", {fact.key for entity in entities for fact in entity.facts})
        result = is_publishable(
            intent=intent, category_schema=robot, entities=entities, sources=(source, source), offers=offers
        )
        self.assertTrue(result.publishable, result.reasons)
        duplicate = is_publishable(
            intent=intent, category_schema=robot, entities=entities, sources=(source, source), offers=offers, existing_intents=(intent.canonical_intent,)
        )
        self.assertFalse(duplicate.publishable)
        self.assertIn("duplicate canonical intent", duplicate.reasons)

    def test_canonical_intent_normalizes_budget_synonyms_and_graph_reuses_entities(self) -> None:
        first = canonical_intent_key(
            category="robot-vacuum", intent_type="best-for", entity_ids=("entity:a",), constraints={"price": "cheap"}
        )
        second = canonical_intent_key(
            category="robot-vacuum", intent_type="best-for", entity_ids=("entity:a",), constraints={"price": "affordable"}
        )
        self.assertEqual(first, second)

        paths = [
            PROJECT / "content" / "pages" / "azure-pipelines-vs-buildkite-for-self-hosted-infrastructure.json",
            PROJECT / "content" / "pages" / "azure-pipelines-vs-gitlab-ci-for-self-hosted-infrastructure.json",
        ]
        rows = [load_page(path) for path in paths]
        graph = validate_site_graph((page, adapt_legacy_page(page, raw)) for page, raw in rows)
        self.assertEqual(graph.orphaned_slugs, ())
        self.assertGreaterEqual(graph.entities, 3)


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
            self.assertEqual(report.reviewed, 4000)
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
            self.assertIn("Editorial assessment", html)
            self.assertIn("does not claim buyer opinions, ratings, or product reviews", html)
            sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://guides.example/</loc>", sitemap)
            self.assertIn("postgresql-vs-sqlite-backend", sitemap)
            self.assertNotIn("/drafts/", sitemap)
            self.assertIn("raspberry-pi-5-vs-intel-nuc-13-pro", sitemap)
            ET.fromstring(sitemap)
            self.assertEqual(len(ET.fromstring(sitemap)), 4006)
            regression = validate_product_invariants(
                content_dir=PROJECT / "content" / "pages",
                manifest_path=PROJECT / "tests" / "fixtures" / "production-invariants.json",
                output_dir=root / "dist",
                base_url="https://guides.example",
            )
            self.assertEqual(regression.failures, ())
            payload = re.search(
                r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
            )
            self.assertIsNotNone(payload)
            structured_data = json.loads(payload.group(1))
            self.assertEqual(structured_data["@context"], "https://schema.org")
            types = {node["@type"] for node in structured_data["@graph"]}
            self.assertEqual(types, {"TechArticle", "BreadcrumbList", "ItemList"})
            self.assertTrue((root / "dist" / "guides" / "index.html").exists())
            self.assertTrue((root / "dist" / "topics" / "ci-cd" / "index.html").exists())
            self.assertTrue((root / "dist" / "catalog" / "index.html").exists())
            self.assertTrue((root / "dist" / "catalog" / "mass-products" / "index.html").exists())
            self.assertTrue((root / "dist" / "catalog" / "consumer-products" / "page" / "2" / "index.html").exists())
            self.assertFalse((root / "dist" / "library").exists())
            llms = (root / "dist" / "llms.txt").read_text(encoding="utf-8")
            self.assertIn("postgresql-vs-sqlite-backend", llms)
            homepage = (root / "dist" / "index.html").read_text(encoding="utf-8")
            analytics = (root / "dist" / "assets" / "analytics.js").read_text(encoding="utf-8")
            self.assertIn('src="/assets/analytics.js"', homepage)
            self.assertIn('data-privacy="no-cookies"', homepage)
            self.assertIn("navigator.doNotTrack", analytics)
            self.assertIn("navigator.sendBeacon", analytics)
            self.assertNotIn("document.cookie", analytics)
            self.assertNotIn("localStorage", analytics)
            self.assertEqual(homepage.count("tag=blackboxia92-21"), 3)
            self.assertEqual(homepage.count('rel="sponsored nofollow noopener"'), 3)
            self.assertIn('data-associate-tag="blackboxia92-21"', homepage)
            self.assertNotIn("paid link", homepage.lower())
            self.assertIn("Ver disponibilidad y precio actualizado en Amazon", homepage)
            self.assertIn("Consultar especificaciones y oferta en Amazon", homepage)
            self.assertIn(disclosure, homepage)

            target_dir = root / "dist" / "guides" / "azure-pipelines-vs-buildkite-for-self-hosted-infrastructure"
            target_html = (target_dir / "index.html").read_text(encoding="utf-8")
            target_markdown = (target_dir / "index.md").read_text(encoding="utf-8")
            target_json = json.loads((target_dir / "index.json").read_text(encoding="utf-8"))
            self.assertIn('href="/guides/"', target_html)
            self.assertIn("Related guides", target_html)
            self.assertNotIn("Canal de Memoria", target_html)
            self.assertIn("Canonical: https://guides.example/guides/azure-pipelines-vs-buildkite-for-self-hosted-infrastructure/", target_markdown)
            self.assertEqual(target_json["canonical_url"], "https://guides.example/guides/azure-pipelines-vs-buildkite-for-self-hosted-infrastructure/")

            commercial_slug = "raspberry-pi-5-vs-intel-nuc-13-pro-for-bootstrapped-saas-limited-space"
            commercial_dir = root / "dist" / "guides" / commercial_slug
            commercial_html = (commercial_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("tag=blackboxia92-21", commercial_html)
            self.assertIn('href="/catalog/mass-products/"', commercial_html)
            commercial_ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', commercial_html, re.DOTALL).group(1))
            self.assertIn("Product", [node["@type"] for node in commercial_ld["@graph"]])
            self.assertNotIn('"@type":"Review"', commercial_html)

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

    def test_state_pruning_has_no_sql_parameter_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with StateStore(Path(temp) / "state.sqlite3") as store:
                for index in range(1_200):
                    store.upsert_page(
                        slug=f"page-{index}", content_hash=f"hash-{index}", public_url=f"https://example.com/{index}",
                        output_path=f"/{index}", status="reviewed", lastmod="2026-09-26",
                    )
                store.prune_except({f"page-{index}" for index in range(1_100)})
                self.assertEqual(len(store.indexable_pages()), 1_100)

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
            article_pages = [page for page in pages if page.parent.name != "guides"]
            self.assertEqual(len(article_pages), 40)
            self.assertTrue(all("tag=blackboxia92-21" in page.read_text(encoding="utf-8") for page in article_pages))
            self.assertEqual((root / "dist" / "llms.txt").read_text(encoding="utf-8").count("/guides/"), 40)


if __name__ == "__main__":
    unittest.main()
