"""Small contracts for the dynamic commerce edge around StackSignal's static core.

These in-memory implementations deliberately do not fetch, rank, convert
currency, or personalize. They make the later data source an adapter rather
than a reason to rewrite Entity, Intent, or editorial pages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, runtime_checkable

from .v2 import AffiliateRoute, Entity, Offer, OfferHealth, resolve_affiliate_link


_MARKET = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class QueryContext:
    """Request context, never a fixed property of an Entity."""

    market: str
    currency: str
    requested_currency: str | None = None

    def __post_init__(self) -> None:
        for field, value, pattern, label in (
            ("market", self.market, _MARKET, "ISO 3166-1 alpha-2 market"),
            ("currency", self.currency, _CURRENCY, "ISO 4217 currency"),
            ("requested_currency", self.requested_currency, _CURRENCY, "ISO 4217 requested currency"),
        ):
            if value is not None and not pattern.fullmatch(value):
                raise ValueError(f"{field} must be uppercase {label}")


@runtime_checkable
class IEntityRepository(Protocol):
    def get_entity(self, entity_id: str) -> Entity | None: ...


@runtime_checkable
class IOfferResolver(Protocol):
    def get_offers(self, entity_id: str, context: QueryContext) -> tuple[Offer, ...]: ...


@runtime_checkable
class IAffiliateRouter(Protocol):
    def generate_route(self, offer: Offer, context: QueryContext) -> str | None: ...


@runtime_checkable
class IOfferHealth(Protocol):
    def get_health(self, offer_id: str) -> OfferHealth | None: ...


@dataclass(frozen=True)
class StaticEntityRepository:
    entities: Mapping[str, Entity]

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)


@dataclass(frozen=True)
class StaticOfferResolver:
    offers: tuple[Offer, ...]

    def get_offers(self, entity_id: str, context: QueryContext) -> tuple[Offer, ...]:
        """Return market-compatible offers without subjective re-ranking."""
        return tuple(
            offer for offer in self.offers
            if offer.entity_id == entity_id
            and (
                offer.temporal_state.market in {None, context.market}
                or context.market in offer.ships_to
            )
        )


@dataclass(frozen=True)
class StaticAffiliateRouter:
    routes_by_offer: Mapping[str, tuple[AffiliateRoute, ...]]

    def generate_route(self, offer: Offer, context: QueryContext) -> str | None:
        del context
        routes = self.routes_by_offer.get(offer.id, ())
        try:
            return resolve_affiliate_link(offer, routes)
        except ValueError:
            return None


@dataclass(frozen=True)
class StaticOfferHealth:
    health_by_offer: Mapping[str, OfferHealth]

    def get_health(self, offer_id: str) -> OfferHealth | None:
        return self.health_by_offer.get(offer_id)


def offer_payload(offer: Offer, route: str | None = None) -> dict[str, object]:
    """Machine-readable dynamic output with original money, never FX conversion."""
    state = offer.temporal_state
    payload: dict[str, object] = {
        "merchant": offer.merchant_id,
        "market": state.market,
        "availability": state.availability,
        "ships_to": list(offer.ships_to),
        "freshness": {"verified_at": state.last_verified_at},
    }
    if state.price is not None and state.currency:
        payload["price_original"] = {"amount": state.price, "currency": state.currency}
    if route:
        payload["affiliate_route"] = {"url": route}
    return payload
