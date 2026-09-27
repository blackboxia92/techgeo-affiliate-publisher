# V2.3 product surface and dynamic commerce boundary

## Public surface

The home, catalog, and regression checks use `publisher.metrics.CatalogMetrics`.
Its units are intentionally distinct: reviewed decision guides, commercial
comparison pages, indexable pages, affiliate routes, entities, sources, and
intentional sitemap hubs. Presentation does not own a count.

The sitemap contains every indexable guide page plus only these intentional,
indexable hubs when the underlying content exists: home, guides, CI/CD topic,
catalog, mass catalog, and consumer catalog. Catalog pagination is navigable
but `noindex`, so it is not a sitemap surface.

## Static core versus query and commerce layers

| Layer | Owns |
| --- | --- |
| Static core | Intent, CategorySchema, Entity, stable Fact, Source/provenance, editorial page and canonical URL |
| Query context | market and currency for this request; never a fixed Entity property |
| Dynamic commerce | TemporalState, Offer, OfferHealth, shipping coverage and AffiliateRoute |

`TemporalState.price` and `TemporalState.currency` preserve the original
observed money. V2.3 does not convert currency and has no FX service. A future
response may expose `price_original` only when both fields exist.

## Adapter contracts

`publisher.commerce` defines the small boundaries for a later source:

- `IEntityRepository.get_entity(entity_id)`
- `IOfferResolver.get_offers(entity_id, QueryContext)`
- `IAffiliateRouter.generate_route(offer, QueryContext)`
- `IOfferHealth.get_health(offer_id)`

The current implementations are in-memory/static adapters. They make no
network calls, do no merchant preference filtering, do no commission ranking,
and do no price monitoring. `StaticOfferResolver` only limits a result to a
matching market or an offer that explicitly ships to the requested market.

`OfferHealth` records check/seen times, destination and affiliate validity,
merchant/feed presence, and consecutive failures. Lifecycle considers an
explicitly unhealthy offer non-active, while unknown legacy health remains
non-failing. Existing conservative lifecycle rules still prevent automatic
301s, one-snapshot removal, or immediate retirement.

## Next data source

The next approved merchant/feed adapter must provide entity identity, merchant,
original price and currency, availability, destination URL, market, observation
timestamp, and affiliate route when one exists. It should first be exercised
with a bounded reviewed batch; no source is allowed to bypass V2 eligibility.
