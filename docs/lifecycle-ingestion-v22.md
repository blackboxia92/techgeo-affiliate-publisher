# V2.2 ingestion and lifecycle

## Pipeline

`RawExternalItem → NormalizedCandidate → Entity / Offer / TemporalState /
Source → is_publishable → optional public page`

Raw payloads are preserved verbatim with source URL, retrieval timestamp and
import batch. Normalization never makes missing price, availability, merchant
or affiliate tracking look present.

The limited Open Food Facts adapter is intentionally an ingestion proof, not a
content generator:

```powershell
python -m publisher ingest-openfoodfacts --limit 200 --output data/ingest/openfoodfacts-a --history data/ingest/openfoodfacts-history.json
python -m publisher ingest-openfoodfacts --limit 200 --output data/ingest/openfoodfacts-b --history data/ingest/openfoodfacts-history.json
python -m publisher compare-ingest-snapshots data/ingest/openfoodfacts-a/normalized.json data/ingest/openfoodfacts-b/normalized.json
```

It normalizes title, brand, GTIN/model, packaging/category, source URLs and
timestamps. Exact valid GTIN wins deduplication. Ambiguous brand/title matches
remain separate and are marked possible variants; weak similarity never
auto-merges entities.

## Lifecycle policy

`evaluate_lifecycle(entity, offers, history)` returns status, reasons,
recommended action, publication/indexability, alternatives and retirement /
redirect flags. `advance_history(...)` tracks `last_seen_at`,
`missing_since`, `last_offer_seen_at`, verification time and consecutive misses
across snapshots. `--history` persists that minimal evidence as local JSON;
there is no new database or service.

- An active offer keeps an entity active.
- A reported unavailable offer is temporary, not a deletion.
- One absent snapshot produces `stale`; it never redirects or retires.
- Explicit discontinuation keeps useful context and may show alternatives.
- An official successor produces `replaced`, but always requires editorial
  redirect review; it never emits an automatic 301.
- Three or more misses can lead to a reviewed `noindex`/410 decision only when
  residual informational value and traffic do not justify retaining the page.

The current adapter uses raw-only routes when a source supplies a destination
without affiliate tracking. A real affiliate URL is never fabricated.

## Current controlled feed result

The V2.2 run used Open Food Facts' public API because the initially attempted
Mercado Libre endpoint returned 403 from this environment and Google Books
returned 429. The selected source returned 200 real snack products over two
snapshots. It has strong identity/provenance coverage but no offers, prices,
stock or affiliate URLs in this endpoint, so the V2 page gate rejected every
candidate. This is the intended safe outcome: no external feed becomes public
content merely because it was parseable.
