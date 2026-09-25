from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WeeklyReport:
    created: int
    available: int
    output: Path
    slugs: tuple[str, ...]


BOOKS = {
    "database": {
        "title": "Designing Data-Intensive Applications",
        "asin": "1449373321",
        "note": "A practical framework for evaluating storage models, consistency, operations, and system trade-offs.",
    },
    "ci": {
        "title": "Accelerate",
        "asin": "1942788339",
        "note": "Research-backed context for evaluating delivery performance, feedback loops, and engineering practices.",
    },
    "containers": {
        "title": "Docker Deep Dive",
        "asin": "B01LXWQUFF",
        "note": "Background reading on container images, runtimes, networking, and day-to-day container operations.",
    },
}


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _meta(left: str, right: str, audience: str) -> str:
    value = (
        f"Compare {left} and {right} for {audience} across architecture, operations, "
        "workflow fit, and practical adoption trade-offs using official documentation."
    )
    if len(value) > 170:
        value = value[:167].rstrip(" ,.;:") + "..."
    if len(value) < 110:
        value += " Includes a concise decision matrix and implementation questions."
    return value


def _page(left: dict[str, str], right: dict[str, str], audience: dict[str, str]) -> dict[str, Any]:
    slug = f"{left['slug']}-vs-{right['slug']}-for-{audience['slug']}"
    audience_name = audience["name"]
    priority = audience["priority"]
    decision = audience["decision"]
    left_name = left["name"]
    right_name = right["name"]
    category = left["category"]
    book = BOOKS[category]
    return {
        "slug": slug,
        "status": "reviewed",
        "locale": "en",
        "title": f"{left_name} vs {right_name} for {audience_name}: a technical decision guide",
        "meta_description": _meta(left_name, right_name, audience_name),
        "eyebrow": f"{category.title()} decision brief",
        "intro": (
            f"This comparison examines {left_name} and {right_name} for {audience_name}. "
            f"The decision lens is {priority}. It uses the maintained catalog and each project's official documentation "
            "to separate architectural differences from implementation details that should be verified before adoption."
        ),
        "verdict": (
            f"Start with {left_name} when its documented model and strongest fit align with {decision}. "
            f"Prefer {right_name} when its operating model better matches that requirement. Validate the shortlist with "
            "a workload-specific proof of concept before committing production data or delivery pipelines."
        ),
        "updated_at": date.today().isoformat(),
        "reviewed_by": "StackSignal structured catalog",
        "criteria": [
            {"key": "model", "label": "Technical model", "description": "The product's primary architectural role."},
            {"key": "operations", "label": "Operating model", "description": "The operational boundary described by the project."},
            {"key": "fit", "label": "Strongest fit", "description": "The use case emphasized in the maintained catalog."},
            {"key": "audience", "label": "Audience lens", "description": f"Decision priority for {audience_name}."},
        ],
        "alternatives": [
            {
                "name": item["name"],
                "url": item["url"],
                "summary": item["summary"],
                "specs": {
                    "model": item["model"],
                    "operations": item["operations"],
                    "fit": item["best_for"],
                    "audience": f"Evaluate against: {priority}",
                },
            }
            for item in (left, right)
        ],
        "faq": [
            {
                "question": f"Which is easier to evaluate first for {audience_name}?",
                "answer": (
                    f"Begin with the option whose operating model already matches {priority}. Use a small proof of concept "
                    "with the same deployment constraints, team access, and failure modes expected in production."
                ),
            },
            {
                "question": f"Can {left_name} and {right_name} be tested with the same benchmark?",
                "answer": (
                    "Only partly. Measure shared outcomes such as setup time, reliability, maintenance effort, and task completion, "
                    "then add product-specific checks because the two options can expose different architectural boundaries."
                ),
            },
            {
                "question": "What should be verified before making the final choice?",
                "answer": (
                    "Confirm current support policies, security controls, deployment requirements, integration limits, and upgrade "
                    "procedures in the official documentation. Recheck any time-sensitive limits immediately before adoption."
                ),
            },
        ],
        "sources": [
            {"label": f"{left_name} official documentation", "publisher": left_name, "url": left["url"]},
            {"label": f"{right_name} official documentation", "publisher": right_name, "url": right["url"]},
        ],
        "resources": [book],
    }


def generate_weekly_pages(catalog_path: Path, destination: Path, limit: int = 20) -> WeeklyReport:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items", [])
    audiences = catalog.get("audiences", [])
    for index, item in enumerate(items):
        for field in ("name", "slug", "category", "url", "summary", "model", "operations", "best_for"):
            _required_text(item.get(field), f"items[{index}].{field}")
        if item["category"] not in BOOKS:
            raise ValueError(f"items[{index}].category has no book mapping: {item['category']}")
    for index, audience in enumerate(audiences):
        for field in ("name", "slug", "priority", "decision"):
            _required_text(audience.get(field), f"audiences[{index}].{field}")

    existing = {path.stem for path in destination.rglob("*.json")} if destination.exists() else set()
    candidates: list[dict[str, Any]] = []
    categories = sorted({item["category"] for item in items})
    for category in categories:
        category_items = sorted((item for item in items if item["category"] == category), key=lambda item: item["slug"])
        for left, right in combinations(category_items, 2):
            for audience in sorted(audiences, key=lambda value: value["slug"]):
                page = _page(left, right, audience)
                if page["slug"] not in existing:
                    candidates.append(page)

    selected = candidates[:limit]
    destination.mkdir(parents=True, exist_ok=True)
    for page in selected:
        (destination / f"{page['slug']}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return WeeklyReport(
        created=len(selected),
        available=len(candidates),
        output=destination,
        slugs=tuple(page["slug"] for page in selected),
    )
