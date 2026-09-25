from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .affiliate import validate_amazon_target

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALLOWED_STATUS = {"draft", "reviewed"}


class ContentError(ValueError):
    pass


def _text(value: Any, field: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ContentError(f"{field} must contain at least {minimum} characters")
    return value.strip()


def _https_url(value: Any, field: str) -> str:
    url = _text(value, field)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ContentError(f"{field} must be an absolute HTTPS URL")
    return url


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class Alternative:
    name: str
    url: str
    summary: str
    specs: dict[str, str]


@dataclass(frozen=True)
class Faq:
    question: str
    answer: str


@dataclass(frozen=True)
class Source:
    label: str
    publisher: str
    url: str


@dataclass(frozen=True)
class Resource:
    title: str
    note: str
    asin: str | None = None
    target_url: str | None = None


@dataclass(frozen=True)
class Page:
    slug: str
    status: str
    locale: str
    title: str
    meta_description: str
    eyebrow: str
    intro: str
    verdict: str
    updated_at: str
    reviewed_by: str
    criteria: tuple[Criterion, ...]
    alternatives: tuple[Alternative, ...]
    faq: tuple[Faq, ...]
    sources: tuple[Source, ...]
    resources: tuple[Resource, ...]

    @property
    def indexable(self) -> bool:
        return self.status == "reviewed"


def load_page(path: Path) -> tuple[Page, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContentError(f"{path}: root must be an object")

    slug = _text(raw.get("slug"), "slug")
    if not _SLUG.fullmatch(slug):
        raise ContentError("slug must use lowercase letters, numbers and hyphens")
    status = _text(raw.get("status", "draft"), "status")
    if status not in _ALLOWED_STATUS:
        raise ContentError(f"status must be one of {sorted(_ALLOWED_STATUS)}")

    try:
        date.fromisoformat(_text(raw.get("updated_at"), "updated_at"))
    except ValueError as exc:
        raise ContentError("updated_at must use YYYY-MM-DD") from exc

    criteria = tuple(
        Criterion(
            key=_text(item.get("key"), f"criteria[{i}].key"),
            label=_text(item.get("label"), f"criteria[{i}].label"),
            description=_text(item.get("description"), f"criteria[{i}].description"),
        )
        for i, item in enumerate(raw.get("criteria", []))
    )
    alternatives = tuple(
        Alternative(
            name=_text(item.get("name"), f"alternatives[{i}].name"),
            url=_https_url(item.get("url"), f"alternatives[{i}].url"),
            summary=_text(item.get("summary"), f"alternatives[{i}].summary", 40),
            specs={str(k): _text(v, f"alternatives[{i}].specs.{k}") for k, v in item.get("specs", {}).items()},
        )
        for i, item in enumerate(raw.get("alternatives", []))
    )
    faq = tuple(
        Faq(
            question=_text(item.get("question"), f"faq[{i}].question", 10),
            answer=_text(item.get("answer"), f"faq[{i}].answer", 40),
        )
        for i, item in enumerate(raw.get("faq", []))
    )
    sources = tuple(
        Source(
            label=_text(item.get("label"), f"sources[{i}].label"),
            publisher=_text(item.get("publisher"), f"sources[{i}].publisher"),
            url=_https_url(item.get("url"), f"sources[{i}].url"),
        )
        for i, item in enumerate(raw.get("sources", []))
    )
    resource_items: list[Resource] = []
    for i, item in enumerate(raw.get("resources", [])):
        asin = item.get("asin")
        target_url = item.get("target_url")
        if bool(asin) == bool(target_url):
            raise ContentError(f"resources[{i}] must contain exactly one of asin or target_url")
        if target_url:
            try:
                target_url = validate_amazon_target(_https_url(target_url, f"resources[{i}].target_url"))
            except ValueError as exc:
                raise ContentError(str(exc)) from exc
        resource_items.append(
            Resource(
                title=_text(item.get("title"), f"resources[{i}].title"),
                note=_text(item.get("note"), f"resources[{i}].note", 20),
                asin=_text(asin, f"resources[{i}].asin") if asin else None,
                target_url=target_url,
            )
        )
    resources = tuple(resource_items)

    page = Page(
        slug=slug,
        status=status,
        locale=_text(raw.get("locale", "en"), "locale"),
        title=_text(raw.get("title"), "title", 20),
        meta_description=_text(raw.get("meta_description"), "meta_description", 80),
        eyebrow=_text(raw.get("eyebrow", "Technical comparison"), "eyebrow"),
        intro=_text(raw.get("intro"), "intro", 120),
        verdict=_text(raw.get("verdict"), "verdict", 100),
        updated_at=_text(raw.get("updated_at"), "updated_at"),
        reviewed_by=_text(raw.get("reviewed_by", "Pending editorial review"), "reviewed_by"),
        criteria=criteria,
        alternatives=alternatives,
        faq=faq,
        sources=sources,
        resources=resources,
    )
    _validate_page(page)
    return page, raw


def _validate_page(page: Page) -> None:
    keys = [criterion.key for criterion in page.criteria]
    if len(keys) != len(set(keys)):
        raise ContentError("criterion keys must be unique")
    if len(page.alternatives) < 2:
        raise ContentError("at least two alternatives are required")
    missing = [
        f"{alternative.name}:{key}"
        for alternative in page.alternatives
        for key in keys
        if key not in alternative.specs
    ]
    if missing:
        raise ContentError(f"missing comparison values: {', '.join(missing)}")

    if page.indexable:
        if len(page.criteria) < 3:
            raise ContentError("reviewed pages require at least three criteria")
        if len(page.faq) < 3:
            raise ContentError("reviewed pages require at least three FAQs")
        if len(page.sources) < 2:
            raise ContentError("reviewed pages require at least two primary sources")
        if page.reviewed_by == "Pending editorial review":
            raise ContentError("reviewed pages require a named editorial review role")
        if not 110 <= len(page.meta_description) <= 170:
            raise ContentError("reviewed meta descriptions must be 110-170 characters")
