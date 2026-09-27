"""Small, build-time V2 domain model.

This module deliberately adapts the existing JSON pages instead of making the
static publisher depend on a database or a second content format.  New content
may use the same concepts directly; legacy pages keep their stable routes and
commercial URLs through :func:`adapt_legacy_page`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil
import re
from typing import Any, Mapping

from .affiliate import amazon_url
from .schema import Criterion, Page, Resource


PLACEHOLDER_VALUES = frozenset({
    "", "-", "n/a", "n/d", "na", "nd", "unknown", "not measured",
    "not stated", "pending research", "not applicable",
})


@dataclass(frozen=True)
class Source:
    """A source with explicit provenance fields for facts added in V2."""

    id: str
    publisher: str
    url: str
    source_type: str
    retrieved_at: str | None = None
    verified_at: str | None = None


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    source_id: str | None
    verified_at: str | None


@dataclass(frozen=True)
class Entity:
    id: str
    entity_type: str
    name: str
    category: str
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class TemporalState:
    """Changing commercial state; it is intentionally not an Entity fact."""

    market: str | None = None
    currency: str | None = None
    price: int | float | None = None
    availability: str | None = None
    last_verified_at: str | None = None


@dataclass(frozen=True)
class Offer:
    id: str
    entity_id: str
    merchant_id: str
    raw_destination_url: str | None
    temporal_state: TemporalState


@dataclass(frozen=True)
class AffiliateRoute:
    offer_id: str
    network: str
    merchant_id: str
    route_type: str
    affiliate_url: str | None
    priority: int = 100
    fallback: bool = True


@dataclass(frozen=True)
class Intent:
    kind: str
    entity_ids: tuple[str, ...]
    qualifier: str | None
    canonical_intent: str


@dataclass(frozen=True)
class AttributeSchema:
    """Render contract for one comparison dimension.

    Units are metadata for future typed facts; legacy text remains untouched.
    """

    key: str
    value_type: str = "text"
    unit: str | None = None
    comparable: bool = True
    required: bool = False


@dataclass(frozen=True)
class CategorySchema:
    id: str
    fields: tuple[AttributeSchema, ...] | None
    minimum_useful_ratio: float = 0.5

    @property
    def relevant_keys(self) -> frozenset[str] | None:
        return frozenset(field.key for field in self.fields) if self.fields is not None else None

    def selects(self, criterion: Criterion, alternatives: int, values: list[str]) -> bool:
        if self.relevant_keys is not None and criterion.key not in self.relevant_keys:
            return False
        useful = sum(_is_useful(value) for value in values)
        return useful >= max(1, ceil(alternatives * self.minimum_useful_ratio))


CATEGORY_SCHEMAS: Mapping[str, CategorySchema] = {
    # The fields are a category contract, not a universal comparison table.
    "ci-cd": CategorySchema("ci-cd", (
        AttributeSchema("model", required=True),
        AttributeSchema("operations", required=True),
        AttributeSchema("fit", required=True),
        AttributeSchema("audience"),
    )),
    "hardware": CategorySchema("hardware", None),
    "consumer-product": CategorySchema(
        "consumer-product", (
            AttributeSchema("model", required=True),
            AttributeSchema("interface"),
            AttributeSchema("form"),
            AttributeSchema("operations", required=True),
            AttributeSchema("fit", required=True),
            AttributeSchema("intent"),
        )
    ),
    "software": CategorySchema("software", None),
}


@dataclass(frozen=True)
class LegacyPageModel:
    intent: Intent
    category_schema: CategorySchema
    entities: tuple[Entity, ...]
    sources: tuple[Source, ...]
    offers: tuple[Offer, ...]
    affiliate_routes: tuple[AffiliateRoute, ...]
    recommendation_offer_id: str | None = None

    def resource_url(self, resource: Resource) -> str:
        """Resolve the existing route first; it is the V2 legacy safety rule."""
        offer = next(offer for offer in self.offers if offer.id == _resource_id(resource))
        routes = tuple(route for route in self.affiliate_routes if route.offer_id == offer.id)
        return resolve_affiliate_link(offer, routes, context={"legacy": True})

    def recommendation_url(self) -> str | None:
        if not self.recommendation_offer_id:
            return None
        offer = next(offer for offer in self.offers if offer.id == self.recommendation_offer_id)
        routes = tuple(route for route in self.affiliate_routes if route.offer_id == offer.id)
        return resolve_affiliate_link(offer, routes, context={"legacy": True})


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "unnamed"


def _resource_id(resource: Resource) -> str:
    return f"offer:amazon-es:{_identifier(resource.title)}"


def _is_useful(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    if normalized in PLACEHOLDER_VALUES:
        return False
    # A legacy generator used longer explanatory variants of these placeholders.
    return not any(marker in normalized for marker in (
        "n/a", "n/d", "not measured", "not stated", "no aplica", "no fue verificado",
    ))


def category_for_page(page: Page, raw: Mapping[str, Any] | None = None) -> str:
    configured_category = (raw or {}).get("category")
    if configured_category in CATEGORY_SCHEMAS:
        return str(configured_category)
    names = {alternative.name.casefold() for alternative in page.alternatives}
    if names & {"azure pipelines", "buildkite", "circleci", "github actions", "gitlab ci"}:
        return "ci-cd"
    if page.catalog_origin == "mass-products-v1":
        return "hardware"
    if page.catalog_origin == "consumer-products-v1":
        return "consumer-product"
    return "software"


def renderable_criteria(page: Page, schema: CategorySchema | None = None) -> tuple[Criterion, ...]:
    """Return visible rows without altering the legacy source data."""
    schema = schema or CATEGORY_SCHEMAS[category_for_page(page)]
    return tuple(
        criterion for criterion in page.criteria
        if schema.selects(
            criterion,
            len(page.alternatives),
            [alternative.specs.get(criterion.key, "") for alternative in page.alternatives],
        )
    )


def resolve_affiliate_link(
    offer: Offer,
    routes: tuple[AffiliateRoute, ...],
    context: Mapping[str, Any] | None = None,
) -> str:
    """Return an approved affiliate route or the raw destination as a fallback.

    ``context`` reserves market/sub-id controls for a future configured resolver.
    It is deliberately not used to rewrite historical URLs.
    """
    del context
    for route in sorted(routes, key=lambda item: item.priority):
        if route.affiliate_url:
            return route.affiliate_url
    if offer.raw_destination_url:
        return offer.raw_destination_url
    raise ValueError(f"Offer {offer.id} has neither an affiliate route nor a raw destination")


def adapt_legacy_page(page: Page, raw: Mapping[str, Any] | None = None) -> LegacyPageModel:
    """Adapt one existing page without changing its source file or public URL."""
    category = category_for_page(page, raw)
    schema = CATEGORY_SCHEMAS[category]
    sources = tuple(
        Source(
            id=f"source:{page.slug}:{position}",
            publisher=source.publisher,
            url=source.url,
            source_type="legacy-primary",
            verified_at=page.updated_at,
        )
        for position, source in enumerate(page.sources, 1)
    )
    entities = tuple(
        Entity(
            id=f"entity:{_identifier(alternative.name)}",
            entity_type="product-or-service",
            name=alternative.name,
            category=category,
            # Legacy specs retain their reviewed_at date, but do not claim a
            # per-field source that the old input never recorded.
            facts=tuple(
                Fact(key=key, value=value, source_id=None, verified_at=page.updated_at)
                for key, value in alternative.specs.items()
            ),
        )
        for alternative in page.alternatives
    )
    resource_entities: dict[str, str] = {entity.name.casefold(): entity.id for entity in entities}
    offers: list[Offer] = []
    routes: list[AffiliateRoute] = []
    for resource in page.resources:
        entity_id = resource_entities.get(resource.title.casefold(), f"entity:{_identifier(resource.title)}")
        affiliate_url = resource.target_url or (amazon_url(resource.asin) if resource.asin else None)
        offers.append(
            Offer(
                id=_resource_id(resource),
                entity_id=entity_id,
                merchant_id="amazon.es",
                raw_destination_url=None,
                temporal_state=TemporalState(market="ES", last_verified_at=page.updated_at),
            )
        )
        routes.append(
            AffiliateRoute(
                offer_id=_resource_id(resource),
                network="amazon-associates-direct",
                merchant_id="amazon.es",
                route_type="legacy-direct",
                affiliate_url=affiliate_url,
            )
        )
    recommendation_offer_id = None
    if page.recommendation:
        recommendation_offer_id = f"offer:recommendation:{page.slug}"
        winner = resource_entities.get(page.recommendation.winner.casefold(), f"entity:{_identifier(page.recommendation.winner)}")
        offers.append(
            Offer(
                id=recommendation_offer_id,
                entity_id=winner,
                merchant_id="amazon.es",
                raw_destination_url=None,
                temporal_state=TemporalState(
                    market="ES",
                    currency="USD",
                    price=page.recommendation.estimated_price_usd,
                    last_verified_at=page.updated_at,
                ),
            )
        )
        routes.append(
            AffiliateRoute(
                offer_id=recommendation_offer_id,
                network="amazon-associates-direct",
                merchant_id="amazon.es",
                route_type="legacy-direct",
                affiliate_url=page.recommendation.amazon_url,
            )
        )
    qualifier = str((raw or {}).get("canonical_intent") or page.slug)
    intent = Intent(
        kind="comparison",
        entity_ids=tuple(entity.id for entity in entities),
        qualifier=qualifier,
        canonical_intent=f"comparison:{'--vs--'.join(_identifier(item.name) for item in page.alternatives)}:{_identifier(qualifier)}",
    )
    return LegacyPageModel(intent, schema, entities, sources, tuple(offers), tuple(routes), recommendation_offer_id)


def create_comparison(
    *,
    slug: str,
    title: str,
    category: str,
    alternatives: list[Mapping[str, Any]],
    criteria: list[Mapping[str, Any]],
    sources: list[Mapping[str, Any]],
    audience: str,
) -> dict[str, Any]:
    """Create a minimal *draft* payload; review is still required before publish."""
    if category not in CATEGORY_SCHEMAS:
        raise ValueError(f"Unknown category schema: {category}")
    if len(alternatives) < 2 or not criteria or not sources:
        raise ValueError("A comparison needs at least two alternatives, one criterion, and one source")
    entity_ids = [_identifier(str(item["name"])) for item in alternatives]
    return {
        "slug": slug,
        "status": "draft",
        "locale": "en",
        "title": title,
        "meta_description": (
            f"Editorial draft comparing {' and '.join(str(item['name']) for item in alternatives)} for {audience}; "
            "primary-source research and editorial review are required before publication."
        ),
        "eyebrow": f"{category} comparison draft",
        "intro": (
            f"This editorial draft compares {' and '.join(str(item['name']) for item in alternatives)} for {audience}. "
            "It is intentionally excluded from search until an editor verifies the facts against primary sources, "
            "explains the relevant trade-offs, and completes the review."
        ),
        "verdict": (
            "No recommendation is published in this draft. Verify the current product facts, evidence, and audience "
            "trade-offs before an editor changes its status to reviewed."
        ),
        "updated_at": date.today().isoformat(),
        "reviewed_by": "Pending editorial review",
        "canonical_intent": f"comparison:{'--vs--'.join(entity_ids)}:{_identifier(audience)}",
        "category": category,
        "audience": audience,
        "alternatives": alternatives,
        "criteria": criteria,
        "sources": sources,
        "faq": [],
        "resources": [],
    }
