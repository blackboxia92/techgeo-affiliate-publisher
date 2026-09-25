from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

from .affiliate import amazon_search_url


ORIGIN = "mass-products-v1"
BUYER_EVIDENCE_BOUNDARY = (
    "No independently verified buyer-review dataset is available; technical synthesis only."
)

CRITERIA = (
    ("model", "Product", "Exact product family or model compared."),
    ("interface", "Interface", "Primary connectivity, protocol, or platform interface."),
    ("form", "Form factor", "Physical or deployment form factor."),
    ("operations", "Operational trade-off", "Maintenance, compatibility, and operating considerations."),
    ("fit", "Best fit", "Workload or environment where the option is strongest."),
    ("intent", "Decision lens", "How the option maps to this long-tail buying intent."),
)


@dataclass(frozen=True)
class MassReport:
    total: int
    preserved: int
    generated: int
    catalog: Path
    output: Path


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return " ".join(value.split())


def _meta(left: str, right: str, intent: str) -> str:
    value = f"Compare {left} vs {right} for {intent}: interfaces, operations, deployment fit, and official technical documentation."
    if len(value) > 170:
        value = f"{left} vs {right} for {intent}, using official specifications, compatibility, and operational requirements."
    if len(value) > 170:
        value = f"{left} vs {right}: official specifications, compatibility, deployment fit, and operational requirements."
    if len(value) < 110:
        value += " Includes a concise decision matrix."
    if not 110 <= len(value) <= 170:
        raise ValueError(f"Generated meta description has invalid length: {len(value)}")
    return value


def _entry_from_existing(raw: dict[str, Any]) -> dict[str, Any]:
    alternatives = raw["alternatives"]
    resources = raw.get("resources", [])
    first_target = (
        resources[0].get("target_url")
        if resources and resources[0].get("target_url")
        else amazon_search_url(alternatives[0]["name"])
    )
    second_target = (
        resources[1].get("target_url")
        if len(resources) > 1 and resources[1].get("target_url")
        else amazon_search_url(alternatives[1]["name"])
    )
    return {
        "id": f"existing-{raw['slug']}",
        "slug": raw["slug"],
        "title": raw["title"],
        "category": "existing technical comparison",
        "intent": raw.get("eyebrow", "technical decision"),
        "specifications": {
            alternative["name"]: alternative["specs"] for alternative in alternatives
        },
        "buyer_consensus": {
            "status": BUYER_EVIDENCE_BOUNDARY,
            "pros": [alternative["summary"] for alternative in alternatives],
            "cons": [
                alternative["specs"].get(
                    "operations", "Validate maintenance, compatibility, and support requirements."
                )
                for alternative in alternatives
            ],
            "verdict": raw["verdict"],
        },
        "target_url": first_target,
        "secondary_target_url": second_target,
        "sources": [source["url"] for source in raw["sources"]],
    }


def _comparison_page(
    *, left: dict[str, Any], right: dict[str, Any], intent: dict[str, str], number: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    left_name = _text(left["name"], "product.name")
    right_name = _text(right["name"], "product.name")
    intent_name = _text(intent["name"], "intent.name")
    slug = f"{left['slug']}-vs-{right['slug']}-for-{intent['slug']}"
    title = f"{left_name} vs {right_name} for {intent_name}: technical buying guide"
    left_fit = f"{left['best_for']} For this comparison, assess it specifically for {intent_name}."
    right_fit = f"{right['best_for']} For this comparison, assess it specifically for {intent_name}."
    verdict = (
        f"Choose {left_name} when {left['decision']} is the leading requirement. Choose {right_name} "
        f"when {right['decision']} matters more. For {intent_name}, verify compatibility, support, "
        "current availability, and workload limits in the cited manufacturer documentation before purchase."
    )
    intro = (
        f"This source-backed comparison evaluates {left_name} and {right_name} for {intent_name}. "
        "It focuses on stable technical characteristics, deployment fit, interfaces, form factor, and "
        "operational trade-offs. It does not copy volatile prices, stock, star ratings, or unverified user claims."
    )
    specs_left = {
        "model": left_name,
        "interface": left["interface"],
        "form": left["form"],
        "operations": left["operations"],
        "fit": left_fit,
        "intent": f"Use when {left['decision']} best supports {intent_name}.",
    }
    specs_right = {
        "model": right_name,
        "interface": right["interface"],
        "form": right["form"],
        "operations": right["operations"],
        "fit": right_fit,
        "intent": f"Use when {right['decision']} best supports {intent_name}.",
    }
    left_target = amazon_search_url(left["amazon_query"])
    right_target = amazon_search_url(right["amazon_query"])
    page = {
        "catalog_origin": ORIGIN,
        "catalog_entry_id": f"mass-{number:04d}",
        "slug": slug,
        "status": "reviewed",
        "locale": "en",
        "title": title,
        "meta_description": _meta(left_name, right_name, intent_name),
        "eyebrow": f"{left['category'].title()} comparison",
        "intro": intro,
        "verdict": verdict,
        "updated_at": date.today().isoformat(),
        "reviewed_by": "StackSignal technical editorial desk",
        "criteria": [
            {"key": key, "label": label, "description": description}
            for key, label, description in CRITERIA
        ],
        "alternatives": [
            {
                "name": left_name,
                "url": left["official_url"],
                "summary": left["summary"],
                "specs": specs_left,
            },
            {
                "name": right_name,
                "url": right["official_url"],
                "summary": right["summary"],
                "specs": specs_right,
            },
        ],
        "faq": [
            {
                "question": f"Which option is easier to evaluate for {intent_name}?",
                "answer": f"Start with compatibility and deployment constraints. {left_name} uses {left['interface']}, while {right_name} uses {right['interface']}; confirm the complete requirements in the linked official documentation.",
            },
            {
                "question": "Does this comparison include live prices or availability?",
                "answer": "No. Price, inventory, bundles, and regional availability change frequently, so this guide links to current listings instead of freezing volatile commercial data.",
            },
            {
                "question": "Are the buyer ratings and review claims independently verified?",
                "answer": "No buyer-review dataset is claimed. Pros, cons, and the verdict are an editorial technical synthesis of the cited manufacturer documentation.",
            },
        ],
        "sources": [
            {"label": f"{left_name} official documentation", "publisher": left["publisher"], "url": left["official_url"]},
            {"label": f"{right_name} official documentation", "publisher": right["publisher"], "url": right["official_url"]},
        ],
        "resources": [
            {"title": left_name, "target_url": left_target, "note": f"Check current specifications and availability for {left_name}."},
            {"title": right_name, "target_url": right_target, "note": f"Check current specifications and availability for {right_name}."},
        ],
        "buyer_consensus": {
            "status": BUYER_EVIDENCE_BOUNDARY,
            "pros": [left["summary"], right["summary"]],
            "cons": [left["operations"], right["operations"]],
            "verdict": verdict,
        },
    }
    catalog_entry = {
        "id": page["catalog_entry_id"],
        "slug": slug,
        "title": title,
        "category": left["category"],
        "intent": intent_name,
        "specifications": {left_name: specs_left, right_name: specs_right},
        "buyer_consensus": page["buyer_consensus"],
        "target_url": left_target,
        "secondary_target_url": right_target,
        "sources": [left["official_url"], right["official_url"]],
    }
    return page, catalog_entry


def generate_mass_catalog(
    *, source_path: Path, pages_root: Path, catalog_path: Path, total: int = 1000
) -> MassReport:
    if total < 1:
        raise ValueError("total must be positive")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    products = source.get("products", [])
    intents = source.get("intents", [])
    if len(products) < 2 or not intents:
        raise ValueError("product source requires at least two products and one intent")

    mass_dir = (pages_root / "mass").resolve()
    pages_root = pages_root.resolve()
    if pages_root not in mass_dir.parents:
        raise ValueError("mass output must remain inside the page root")
    mass_dir.mkdir(parents=True, exist_ok=True)

    preserved_paths: list[Path] = []
    for path in sorted(pages_root.rglob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("catalog_origin") != ORIGIN:
            if raw.get("status") != "reviewed":
                raise ValueError(f"Preserved page is not reviewed: {path}")
            preserved_paths.append(path)
    if len(preserved_paths) > total:
        raise ValueError(f"There are already {len(preserved_paths)} preserved pages, above total {total}")

    for stale in mass_dir.glob("*.json"):
        if stale.resolve().parent != mass_dir:
            raise ValueError(f"Refusing to remove file outside mass directory: {stale}")
        stale.unlink()

    product_by_slug = {product["slug"]: product for product in products}
    pair_specs = source.get("pairs", [])
    if pair_specs:
        seen_pairs: set[tuple[str, str]] = set()
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for index, pair in enumerate(pair_specs):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"pairs[{index}] must contain two product slugs")
            try:
                left, right = (product_by_slug[pair[0]], product_by_slug[pair[1]])
            except KeyError as exc:
                raise ValueError(f"pairs[{index}] references an unknown product: {exc}") from exc
            key = tuple(sorted((left["slug"], right["slug"])))
            if key in seen_pairs:
                raise ValueError(f"Duplicate product pair: {key}")
            seen_pairs.add(key)
            pairs.append((left, right))
    else:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for product in products:
            grouped.setdefault(_text(product["category"], "product.category"), []).append(product)
        pairs = [
            (left, right)
            for category in sorted(grouped)
            for left, right in combinations(grouped[category], 2)
        ]
    candidates = [(left, right, intent) for left, right in pairs for intent in intents]
    needed = total - len(preserved_paths)
    if len(candidates) < needed:
        raise ValueError(f"Only {len(candidates)} unique comparison candidates are available; {needed} required")

    catalog_entries = [
        _entry_from_existing(json.loads(path.read_text(encoding="utf-8")))
        for path in preserved_paths
    ]
    seen_slugs = {entry["slug"] for entry in catalog_entries}
    generated = 0
    for left, right, intent in candidates:
        page, catalog_entry = _comparison_page(
            left=left, right=right, intent=intent, number=generated + 1
        )
        if page["slug"] in seen_slugs:
            continue
        seen_slugs.add(page["slug"])
        destination = mass_dir / f"{page['slug']}.json"
        destination.write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        catalog_entries.append(catalog_entry)
        generated += 1
        if generated == needed:
            break
    if len(catalog_entries) != total:
        raise RuntimeError(f"Generated catalog contains {len(catalog_entries)} entries, expected {total}")
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": date.today().isoformat(),
                "associate_tag": "blackboxia92-21",
                "buyer_evidence_policy": BUYER_EVIDENCE_BOUNDARY,
                "count": total,
                "items": catalog_entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return MassReport(total, len(preserved_paths), generated, catalog_path, mass_dir)
