from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from dataclasses import replace
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from publisher.affiliate import AMAZON_ASSOCIATE_TAG, amazon_url, assert_required_tag, validate_affiliate_target
from publisher.builder import build_site, expand_catalog
from publisher.commerce import (
    IAffiliateRouter,
    IEntityRepository,
    IOfferHealth,
    IOfferResolver,
    QueryContext,
    StaticAffiliateRouter,
    StaticEntityRepository,
    StaticOfferHealth,
    StaticOfferResolver,
    offer_payload,
)
from publisher.graph import validate_site_graph
from publisher.indexnow import notify_indexnow
from publisher.ingest import (
    AwinAccessError, RawExternalItem, _awin_llm_payload, compare_normalized_snapshots, deduplicate,
    deduplicate_awin, fetch_awin_enhanced_feed, normalize_awin_product, normalize_openfoodfacts,
    publication_count, valid_gtin,
)
from publisher.lifecycle import LifecycleHistory, advance_history, compare_offer_snapshots, evaluate_lifecycle, update_history_ledger
from publisher.regression import validate_product_invariants
from publisher.metrics import catalog_metrics, intentional_hub_paths
from publisher.schema import load_page
from publisher.store import StateStore
from publisher.transversal import generate_transversal_catalog
from publisher.v2 import (
    AffiliateRoute,
    CATEGORY_SCHEMAS,
    Entity,
    Fact,
    Intent,
    Offer,
    OfferHealth,
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
    def test_public_metrics_are_single_source_for_home_and_sitemap(self) -> None:
        rows = [load_page(path) for path in (PROJECT / "content" / "pages").rglob("*.json")]
        metrics = catalog_metrics(rows)
        self.assertEqual(metrics.reviewed_guides + metrics.commercial_pages, metrics.indexable_pages)
        self.assertEqual(metrics.commercial_pages, 3957)
        self.assertGreater(metrics.indexable_pages, 9000)
        self.assertGreater(metrics.affiliate_routes, 13000)
        self.assertEqual(metrics.sitemap_urls, metrics.indexable_pages + metrics.sitemap_hubs)
        hubs = intentional_hub_paths(rows)
        self.assertIn("/books/", hubs)
        self.assertIn("/books/artificial-intelligence/", hubs)
        self.assertIn("/catalog/consumer-products/", hubs)

    def test_query_context_and_static_commerce_contracts_preserve_original_money(self) -> None:
        context = QueryContext(market="AR", currency="ARS", requested_currency="USD")
        with self.assertRaises(ValueError):
            QueryContext(market="arg", currency="ARS")
        with self.assertRaises(ValueError):
            QueryContext(market="AR", currency="ars")
        entity = Entity("entity:test", "physical-product", "Test", "robot-vacuum", ())
        health = OfferHealth(
            last_checked_at="2026-09-26T00:00:00Z", last_seen_at="2026-09-26T00:00:00Z",
            destination_valid=True, affiliate_valid=True, merchant_present=True, feed_present=True,
        )
        offer = Offer(
            "offer:test", entity.id, "merchant-us", "https://merchant.example/p",
            TemporalState(market="US", currency="USD", price=499, availability="in_stock", last_verified_at="2026-09-26T00:00:00Z"),
            ships_to=("AR",), health=health,
        )
        route = AffiliateRoute(offer.id, "future-network", "merchant-us", "adapter", "https://affiliate.example/p")
        repository = StaticEntityRepository({entity.id: entity})
        resolver = StaticOfferResolver((offer,))
        router = StaticAffiliateRouter({offer.id: (route,)})
        health_store = StaticOfferHealth({offer.id: health})
        self.assertIsInstance(repository, IEntityRepository)
        self.assertIsInstance(resolver, IOfferResolver)
        self.assertIsInstance(router, IAffiliateRouter)
        self.assertIsInstance(health_store, IOfferHealth)
        self.assertEqual(repository.get_entity(entity.id), entity)
        self.assertEqual(resolver.get_offers(entity.id, context), (offer,))
        resolved = router.generate_route(offer, context)
        self.assertEqual(resolved, "https://affiliate.example/p")
        self.assertEqual(health_store.get_health(offer.id), health)
        payload = offer_payload(offer, resolved)
        self.assertEqual(payload["price_original"], {"amount": 499, "currency": "USD"})
        self.assertEqual(payload["ships_to"], ["AR"])
        unhealthy = Offer(offer.id, offer.entity_id, offer.merchant_id, offer.raw_destination_url, offer.temporal_state, health=OfferHealth(destination_valid=False))
        self.assertEqual(evaluate_lifecycle(entity, (unhealthy,), LifecycleHistory()).status, "stale")

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


class TransversalCatalogTests(unittest.TestCase):
    def test_explicit_cross_domain_intents_keep_primary_sources_and_demand_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = generate_transversal_catalog(
                source_path=PROJECT / "content" / "transversal_source.json",
                pages_root=root / "pages",
                catalog_path=root / "transversal_catalog.json",
            )
            self.assertEqual((report.entities, report.intents, report.published), (24, 12, 12))
            rows = [load_page(path) for path in sorted((root / "pages" / "transversal").glob("*.json"))]
            self.assertEqual(len(rows), 12)
            published_intents: set[str] = set()
            for page, raw in rows:
                self.assertEqual(raw["content_model"], "v2")
                self.assertEqual(raw["catalog_origin"], "transversal-v1")
                self.assertEqual(raw["demand_evidence"]["kind"], "query-pattern")
                self.assertEqual(len(raw["entity_provenance"]), 2)
                self.assertEqual(len(page.sources), 2)
                model = adapt_legacy_page(page, raw)
                eligibility = is_publishable(
                    intent=model.intent,
                    category_schema=model.category_schema,
                    entities=model.entities,
                    sources=model.sources,
                    offers=model.offers,
                    existing_intents=published_intents,
                )
                self.assertTrue(eligibility.publishable, eligibility.reasons)
                published_intents.add(eligibility.canonical_intent)


class IngestLifecycleTests(unittest.TestCase):
    @staticmethod
    def raw_item(*, code: str, title: str = "  <b>SNACK</b>  DELUXE ", brand: str = "ACME") -> RawExternalItem:
        return RawExternalItem(
            source="openfoodfacts-api", source_url=f"https://us.openfoodfacts.org/api/v2/product/{code}.json",
            retrieved_at="2026-09-26T00:00:00+00:00", batch_id="test-batch",
            raw={"code": code, "product_name": title, "brands": brand, "packaging": "  Box ", "categories_tags": ["en:snacks"]},
        )

    def test_dirty_data_is_normalized_with_raw_and_provenance_preserved(self) -> None:
        candidate = normalize_openfoodfacts(self.raw_item(code="4006381333931"))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.title, "SNACK DELUXE")
        self.assertEqual(candidate.identifiers["GTIN"], "4006381333931")
        self.assertEqual(candidate.source.retrieved_at, "2026-09-26T00:00:00+00:00")
        self.assertEqual(candidate.raw.raw["product_name"], "  <b>SNACK</b>  DELUXE ")
        self.assertFalse(candidate.offers)
        self.assertEqual(publication_count((candidate,)), 0)

    def test_invalid_identifiers_and_variants_do_not_auto_merge(self) -> None:
        invalid = normalize_openfoodfacts(self.raw_item(code="not-a-gtin"))
        self.assertIsNotNone(invalid)
        assert invalid is not None
        self.assertFalse(valid_gtin("not-a-gtin"))
        self.assertEqual(invalid.identifiers["raw_code"], "not-a-gtin")
        first = normalize_openfoodfacts(self.raw_item(code="4006381333931"))
        duplicate = normalize_openfoodfacts(self.raw_item(code="4006381333931", title="Other listing"))
        variant = normalize_openfoodfacts(self.raw_item(code="unknown-code", title="SNACK DELUXE"))
        variant_second = normalize_openfoodfacts(self.raw_item(code="another-unknown-code", title="SNACK DELUXE"))
        accepted, duplicates, variants = deduplicate((first, duplicate, variant, variant_second))
        self.assertEqual(duplicates, 1)
        self.assertEqual(variants, 1)
        self.assertEqual(len(accepted), 3)
        self.assertTrue(accepted[-1].possible_duplicate)

    def test_lifecycle_never_deletes_or_redirects_on_one_missing_snapshot(self) -> None:
        entity = Entity("entity:test", "physical-product", "Test", "robot-vacuum", ())
        active = Offer("offer:test", entity.id, "merchant", "https://merchant.example/item", TemporalState(availability="active", price=100))
        unavailable = Offer("offer:test", entity.id, "merchant", "https://merchant.example/item", TemporalState(availability="temporarily_unavailable"))
        self.assertEqual(evaluate_lifecycle(entity, (active,), LifecycleHistory()).status, "active")
        self.assertEqual(evaluate_lifecycle(entity, (unavailable,), LifecycleHistory()).status, "temporarily_unavailable")
        missing_once = evaluate_lifecycle(entity, (), LifecycleHistory(consecutive_missing_count=1))
        self.assertEqual(missing_once.status, "stale")
        self.assertTrue(missing_once.indexable)
        self.assertFalse(missing_once.requires_retirement)
        self.assertFalse(missing_once.requires_redirect)
        discontinued = evaluate_lifecycle(entity, (), LifecycleHistory(explicit_discontinued=True))
        self.assertEqual(discontinued.status, "discontinued")
        replacement = evaluate_lifecycle(entity, (), LifecycleHistory(explicit_discontinued=True, official_successor_id="entity:new"))
        self.assertEqual(replacement.status, "replaced")
        self.assertFalse(replacement.requires_redirect)
        retired = evaluate_lifecycle(entity, (), LifecycleHistory(consecutive_missing_count=3, has_residual_value=False, has_traffic=False))
        self.assertTrue(retired.requires_retirement)
        self.assertFalse(retired.requires_redirect)
        seen = advance_history(LifecycleHistory(), entity_seen=True, offer_seen=True, observed_at="2026-09-26T00:00:00Z")
        missing = advance_history(seen, entity_seen=False, offer_seen=False, observed_at="2026-09-27T00:00:00Z")
        self.assertEqual(missing.consecutive_missing_count, 1)
        self.assertEqual(missing.missing_since, "2026-09-27T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "history.json"
            update_history_ledger(ledger_path, entity_ids=(entity.id,), offers=(active,), observed_at="2026-09-26T00:00:00Z")
            ledger = update_history_ledger(ledger_path, entity_ids=(), offers=(), observed_at="2026-09-27T00:00:00Z")
            self.assertEqual(ledger[entity.id].consecutive_missing_count, 1)

    def test_snapshot_diff_detects_offer_changes_without_retiring_entity(self) -> None:
        before = Offer("offer:test", "entity:test", "merchant", "https://merchant.example/a", TemporalState(price=100, availability="active"))
        after = Offer("offer:test", "entity:test", "merchant", "https://merchant.example/b", TemporalState(price=90, availability="temporarily_unavailable"))
        kinds = {change.kind for change in compare_offer_snapshots((before,), (after,))}
        self.assertEqual(kinds, {"price_changed", "availability_changed", "destination_changed"})


class AwinIngestTests(unittest.TestCase):
    @staticmethod
    def raw_item(*, merchant_id: str = "42", price: object = "249.99", in_stock: object = True) -> RawExternalItem:
        return RawExternalItem(
            source="awin-enhanced-feed", source_url="https://api.awin.com/publishers/3107154/awinfeeds/download/42-retail-es_ES.jsonl",
            retrieved_at="2026-09-27T00:00:00+00:00", batch_id="awin-test",
            raw={
                "aw_product_id": "sku-123", "product_name": "Example Robot Vacuum", "merchant_id": merchant_id,
                "merchant_name": "Example ES", "brand_name": "Example", "model_number": "RV-1",
                "product_type": "Robot vacuum", "ean": "4006381333931", "search_price": price,
                "currency": "eur", "in_stock": in_stock,
                "merchant_deep_link": "https://merchant.example/products/sku-123",
                "aw_deep_link": "https://www.awin1.com/cread.php?awinmid=42&awinaffid=3107154",
            },
        )

    def test_awin_market_money_provenance_health_and_route_are_preserved(self) -> None:
        candidate = normalize_awin_product(self.raw_item(), context=QueryContext(market="ES", currency="EUR"))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        offer = candidate.offers[0]
        self.assertEqual(offer.temporal_state.market, "ES")
        self.assertEqual(offer.temporal_state.currency, "EUR")
        self.assertEqual(offer.temporal_state.price, 249.99)
        self.assertEqual(offer.temporal_state.availability, "active")
        self.assertEqual(candidate.identifiers["GTIN"], "4006381333931")
        self.assertEqual(candidate.source.source_type, "authorized-product-feed")
        self.assertTrue(offer.health and offer.health.destination_valid)
        self.assertTrue(offer.health and offer.health.affiliate_valid)
        self.assertEqual(candidate.routes[0].network, "awin")
        self.assertEqual(candidate.routes[0].affiliate_url, self.raw_item().raw["aw_deep_link"])
        self.assertNotIn("price", {fact.key for fact in candidate.entity.facts})
        self.assertEqual(publication_count((candidate,)), 0)
        self.assertIn("price_original", _awin_llm_payload(candidate)["offers"][0])

    def test_awin_missing_or_invalid_commercial_fields_remain_missing(self) -> None:
        candidate = normalize_awin_product(
            self.raw_item(price="1.299,99", in_stock="unknown"), context=QueryContext(market="ES", currency="EUR")
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        offer = candidate.offers[0]
        self.assertIsNone(offer.temporal_state.price)
        self.assertIsNone(offer.temporal_state.availability)
        self.assertFalse(normalize_awin_product(
            replace(self.raw_item(), raw={"aw_product_id": "x", "merchant_id": "42"}),
            context=QueryContext(market="ES", currency="EUR"),
        ))

    def test_awin_gtin_merges_entity_but_preserves_offers_per_merchant(self) -> None:
        first = normalize_awin_product(self.raw_item(merchant_id="42"), context=QueryContext(market="ES", currency="EUR"))
        second = normalize_awin_product(self.raw_item(merchant_id="43"), context=QueryContext(market="ES", currency="EUR"))
        assert first is not None and second is not None
        accepted, duplicates, variants = deduplicate_awin((first, second))
        self.assertEqual((len(accepted), duplicates, variants), (1, 1, 0))
        self.assertEqual(len(accepted[0].offers), 2)
        self.assertEqual({offer.merchant_id for offer in accepted[0].offers}, {"awin:42", "awin:43"})

    def test_awin_snapshot_diff_and_lifecycle_keep_single_absence(self) -> None:
        before = normalize_awin_product(self.raw_item(), context=QueryContext(market="ES", currency="EUR"))
        after = normalize_awin_product(self.raw_item(price="199.99", in_stock=False), context=QueryContext(market="ES", currency="EUR"))
        assert before is not None and after is not None
        kinds = {change.kind for change in compare_offer_snapshots(before.offers, after.offers)}
        self.assertEqual(kinds, {"price_changed", "availability_changed"})
        missing_once = evaluate_lifecycle(before.entity, (), LifecycleHistory(consecutive_missing_count=1))
        self.assertTrue(missing_once.indexable)
        self.assertFalse(missing_once.requires_retirement)

    def test_awin_fetch_requires_environment_token_without_fallback(self) -> None:
        previous = os.environ.pop("AWIN_API_TOKEN", None)
        try:
            with self.assertRaises(AwinAccessError):
                fetch_awin_enhanced_feed(
                    publisher_id="3107154", advertiser_id="42", locale="es_ES", limit=1, batch_id="test"
                )
        finally:
            if previous is not None:
                os.environ["AWIN_API_TOKEN"] = previous


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
            self.assertIn("Editorial assessment", html)
            self.assertIn("does not claim buyer opinions, ratings, or product reviews", html)
            sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://guides.example/</loc>", sitemap)
            self.assertIn("postgresql-vs-sqlite-backend", sitemap)
            self.assertNotIn("/drafts/", sitemap)
            self.assertIn("raspberry-pi-5-vs-intel-nuc-13-pro", sitemap)
            ET.fromstring(sitemap)
            expected_metrics = catalog_metrics([load_page(path) for path in (PROJECT / "content" / "pages").rglob("*.json")])
            self.assertEqual(len(ET.fromstring(sitemap)), expected_metrics.sitemap_urls)
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
            self.assertTrue((root / "dist" / "topics" / "travel-and-consumer-services" / "index.html").exists())
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
            self.assertIn(f"{expected_metrics.reviewed_guides}</strong></dt><dd>reviewed decision guides", homepage)
            self.assertIn("3957</strong></dt><dd>commercial comparisons", homepage)
            self.assertIn(f"{expected_metrics.affiliate_routes}</strong></dt><dd>disclosed monetized destinations", homepage)
            self.assertIn('href="/catalog/"', homepage)
            self.assertIn('href="/topics/ci-cd/"', homepage)
            self.assertNotIn("Zero hidden sponsored links", homepage)
            self.assertNotIn("44 reviewed guides", (PROJECT / "publisher" / "templates" / "index.html").read_text(encoding="utf-8"))
            home_ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', homepage, re.DOTALL).group(1))
            self.assertEqual({node["@type"] for node in home_ld["@graph"]}, {"WebSite", "ItemList"})
            self.assertEqual(home_ld["@graph"][1]["numberOfItems"], expected_metrics.indexable_pages)

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
