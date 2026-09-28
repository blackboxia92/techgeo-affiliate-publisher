"""Curated, cross-domain content expansion with evidence gates.

This deliberately does *not* turn a product list × audience list into pages.
Each row is an observed query family with named entities, primary sources and
an explicit demand signal.  It is therefore safe to rerun: only this origin's
directory is replaced and no legacy route or affiliate URL is rewritten.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .affiliate import amazon_search_url
from .v2 import canonical_intent_key


ORIGIN = "transversal-v1"
CRITERIA = (
    ("model", "Option", "Named book, product, or service being evaluated."),
    ("workflow", "Primary workflow", "The documented job or workflow the option supports."),
    ("constraints", "Decision constraints", "Compatibility, ownership, or implementation limits to verify."),
    ("fit", "Best fit", "The stated use case for which the option is the stronger fit."),
)


@dataclass(frozen=True)
class TransversalReport:
    entities: int
    intents: int
    published: int
    catalog: Path
    output: Path


def _text(value: Any, field: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return " ".join(value.split())


def _source(entity: dict[str, Any]) -> dict[str, str]:
    source = entity.get("source")
    if not isinstance(source, dict):
        raise ValueError(f"entity {entity.get('id')!r} needs a primary source")
    return {
        "label": _text(source.get("label"), "entity.source.label", 8),
        "publisher": _text(source.get("publisher"), "entity.source.publisher"),
        "url": _text(source.get("url"), "entity.source.url", 12),
    }


def _meta(left: str, right: str, qualifier: str) -> str:
    value = f"{left} vs {right} for {qualifier}: documented workflows, constraints, and a source-backed decision summary."
    if len(value) > 170:
        value = f"{left} vs {right}: documented workflows, constraints, fit, and primary-source decision guidance for a considered choice."
    if len(value) < 110:
        value += " Compare primary documentation before committing."
    if not 110 <= len(value) <= 170:
        raise ValueError(f"Meta description out of range for {left} vs {right}")
    return value


def _validate_demand(item: dict[str, Any], index: int) -> dict[str, str]:
    evidence = item.get("demand_evidence")
    if not isinstance(evidence, dict):
        raise ValueError(f"comparisons[{index}] requires demand_evidence")
    if _text(evidence.get("kind"), f"comparisons[{index}].demand_evidence.kind") not in {"query-pattern", "serp-observation"}:
        raise ValueError(f"comparisons[{index}] has an unsupported demand evidence kind")
    return {
        "kind": _text(evidence.get("kind"), f"comparisons[{index}].demand_evidence.kind"),
        "query": _text(evidence.get("query"), f"comparisons[{index}].demand_evidence.query", 8),
        "observed_at": _text(evidence.get("observed_at"), f"comparisons[{index}].demand_evidence.observed_at", 10),
        "note": _text(evidence.get("note"), f"comparisons[{index}].demand_evidence.note", 20),
    }


def _page(item: dict[str, Any], entities: dict[str, dict[str, Any]], index: int) -> dict[str, Any]:
    entity_ids = item.get("entity_ids")
    if not isinstance(entity_ids, list) or len(entity_ids) != 2 or len(set(entity_ids)) != 2:
        raise ValueError(f"comparisons[{index}] must name exactly two distinct entities")
    try:
        left, right = (entities[entity_id] for entity_id in entity_ids)
    except KeyError as exc:
        raise ValueError(f"comparisons[{index}] references unknown entity {exc.args[0]!r}") from exc
    qualifier = _text(item.get("qualifier"), f"comparisons[{index}].qualifier", 8)
    slug = _text(item.get("slug"), f"comparisons[{index}].slug", 12)
    title = _text(item.get("title"), f"comparisons[{index}].title", 20)
    demand = _validate_demand(item, index)
    left_name, right_name = _text(left["name"], "entity.name"), _text(right["name"], "entity.name")
    left_facts, right_facts = left.get("facts"), right.get("facts")
    if not isinstance(left_facts, dict) or not isinstance(right_facts, dict):
        raise ValueError("Each transversal entity requires structured facts")
    for key in ("workflow", "constraints", "fit"):
        _text(left_facts.get(key), f"{left['id']}.facts.{key}", 15)
        _text(right_facts.get(key), f"{right['id']}.facts.{key}", 15)

    alternatives = []
    sources = []
    resources = []
    for entity in (left, right):
        facts = entity["facts"]
        alternatives.append({
            "name": _text(entity["name"], "entity.name"),
            "url": _source(entity)["url"],
            "summary": _text(entity.get("summary"), "entity.summary", 40),
            "specs": {"model": _text(entity["name"], "entity.name"), **{key: _text(facts[key], f"entity.facts.{key}", 15) for key in ("workflow", "constraints", "fit")}},
        })
        sources.append(_source(entity))
        if entity.get("amazon_query"):
            query = _text(entity["amazon_query"], "entity.amazon_query", 4)
            resources.append({
                "title": _text(entity["name"], "entity.name"),
                "target_url": amazon_search_url(query),
                "note": f"Check the current Amazon ES listing for the exact edition or model of {entity['name']}; no price, rating, or stock claim is made here.",
            })

    canonical = canonical_intent_key(
        category="software", intent_type="comparison",
        entity_ids=(f"entity:{entity_id}" for entity_id in entity_ids),
        constraints={"audience": qualifier},
    )
    verdict = _text(item.get("verdict"), f"comparisons[{index}].verdict", 100)
    return {
        "catalog_origin": ORIGIN,
        "catalog_entry_id": f"transversal-{index:04d}",
        "content_model": "v2",
        "slug": slug,
        "status": "reviewed",
        "locale": "en",
        "category": "software",
        "transversal_family": _text(item.get("family"), f"comparisons[{index}].family"),
        "intent_type": "comparison",
        "canonical_intent": canonical,
        "audience": qualifier,
        "demand_evidence": demand,
        "publication_role": (
            {
                "kind": "direct-monetization",
                "merchant": "amazon.es",
                "route_type": "affiliate-search",
                "cluster": "books-and-media",
                "note": "A current Amazon ES search route is present for the exact title or model; editorial facts remain merchant-agnostic.",
            }
            if resources else {
                "kind": "demand-cluster",
                "cluster": _text(item.get("family"), f"comparisons[{index}].family"),
                "note": "An explicit observed decision-query pattern contributes to a commercial comparison cluster without asserting a current merchant route.",
            }
        ),
        "entity_provenance": [
            {"entity_id": entity["id"], "entity_type": entity["entity_type"], "source": _source(entity), "facts_verified_at": entity["facts_verified_at"]}
            for entity in (left, right)
        ],
        "title": title,
        "meta_description": _meta(left_name, right_name, qualifier),
        "eyebrow": f"{_text(item.get('family'), f'comparisons[{index}].family')} comparison",
        "intro": (
            f"This source-backed comparison addresses the observed query pattern “{demand['query']}” for {qualifier}. "
            "It compares stable, documented workflows and constraints rather than volatile prices, inventory, ratings, or reviews."
        ),
        "verdict": verdict,
        "updated_at": date.today().isoformat(),
        "reviewed_by": "StackSignal editorial research desk",
        "criteria": [{"key": key, "label": label, "description": description} for key, label, description in CRITERIA],
        "alternatives": alternatives,
        "faq": [
            {"question": f"What query pattern justified this {left_name} vs {right_name} comparison?", "answer": f"The editorial backlog records the recurring query pattern “{demand['query']}” ({demand['kind']} observed {demand['observed_at']}). {demand['note']} This is a qualitative signal, not a claimed search-volume figure."},
            {"question": "Does this comparison include live price, availability, ratings, or a discount claim?", "answer": "No. Those values vary by plan, region, seller, edition, and time. The comparison links to primary documentation and, where relevant, an Amazon ES search route for the current listing."},
            {"question": "How should a reader make the final choice?", "answer": f"Start with the documented workflow and constraints: {left_name} is described for {left_facts['fit'].rstrip('.')}; {right_name} is described for {right_facts['fit'].rstrip('.')}. Confirm current account, device, plan, regional, and edition details in the cited primary sources."},
        ],
        "sources": sources,
        "resources": resources,
        "buyer_consensus": {"status": "No buyer-review dataset is claimed; this is a primary-source editorial synthesis.", "pros": [alternative["summary"] for alternative in alternatives], "cons": [alternative["specs"]["constraints"] for alternative in alternatives], "verdict": verdict},
    }


def generate_transversal_catalog(*, source_path: Path, pages_root: Path, catalog_path: Path) -> TransversalReport:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("version") != 1:
        raise ValueError("transversal source version must be 1")
    raw_entities = source.get("entities")
    comparisons = source.get("comparisons")
    if not isinstance(raw_entities, list) or not isinstance(comparisons, list):
        raise ValueError("transversal source requires entities and comparisons lists")
    entities: dict[str, dict[str, Any]] = {}
    for entity in raw_entities:
        if not isinstance(entity, dict):
            raise ValueError("entities must be objects")
        entity_id = _text(entity.get("id"), "entity.id", 4)
        if entity_id in entities:
            raise ValueError(f"duplicate entity id: {entity_id}")
        _text(entity.get("entity_type"), f"{entity_id}.entity_type", 4)
        _text(entity.get("facts_verified_at"), f"{entity_id}.facts_verified_at", 10)
        _source(entity)
        entities[entity_id] = entity

    slugs: set[str] = set()
    canonicals: set[str] = set()
    pages: list[dict[str, Any]] = []
    catalog_items: list[dict[str, Any]] = []
    for index, item in enumerate(comparisons, 1):
        if not isinstance(item, dict):
            raise ValueError("comparisons must be objects")
        page = _page(item, entities, index)
        if page["slug"] in slugs:
            raise ValueError(f"duplicate transversal slug: {page['slug']}")
        if page["canonical_intent"] in canonicals:
            raise ValueError(f"duplicate transversal canonical intent: {page['canonical_intent']}")
        slugs.add(page["slug"])
        canonicals.add(page["canonical_intent"])
        pages.append(page)
        catalog_items.append({"slug": page["slug"], "title": page["title"], "family": item["family"], "canonical_intent": page["canonical_intent"], "demand_evidence": page["demand_evidence"], "entities": page["entity_provenance"]})
    output = pages_root / "transversal"
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("*.json"):
        stale.unlink()
    for page in pages:
        (output / f"{page['slug']}.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog_path.write_text(json.dumps({"version": 1, "origin": ORIGIN, "generated_at": date.today().isoformat(), "entity_count": len(entities), "published_intents": len(catalog_items), "items": catalog_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return TransversalReport(len(entities), len(comparisons), len(catalog_items), catalog_path, output)
