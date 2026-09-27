# V2.1 scale assessment

## Measured baseline

On 2026-09-26, a clean local production build of 4,000 reviewed pages took
19.54 seconds: 3.02 seconds loading/validation, 15.72 seconds rendering and
writing article representations, and 0.11 seconds for hubs/sitemap. Render
throughput was 254.4 pages/second. Python allocation peak is optional via
`--trace-memory`; it was not used for the normal timing because allocation
tracking materially distorts this I/O-heavy build.

Run the measurement locally:

```powershell
python -m publisher build --content content/pages --output dist --state data/state.sqlite3 --base-url https://stacksignal-tech.netlify.app --metrics
```

## Scale posture

The sitemap writer already emits a sitemap index after 45,000 URLs, below the
standard 50,000-URL limit. Full static sitemap regeneration is inexpensive at
current scale. At 100k+, split sitemaps by stable page type/category only if
operations need smaller diffs; do not change public URLs to do so.

The SQLite prune operation uses a temporary table, not an unbounded `IN (...)`
parameter list, so it does not hit SQLite variable limits at 20k/100k. The
main remaining constraint is static output I/O (three files per article) and
the current in-memory legacy raw-page list. Keep full rebuilds through about
100k when the build host has adequate disk and memory; measure again before
500k. A future streaming/partial renderer is justified only if those
measurements show the in-memory list or deployment upload is the bottleneck.

Linear lower-bound estimates from the measured render rate are roughly:

| Reviewed pages | Render/write | Full build planning range |
| --- | ---: | ---: |
| 20,000 | 79 s | 1.5–2 min |
| 100,000 | 393 s | 7–10 min |
| 500,000 | 1,965 s | 35–50 min |

The planning range deliberately adds filesystem, sitemap and deployment
overhead; it is not a promise. At 500k, use a build host/CI artifact flow and
benchmark memory before publishing a large batch.

## Reusable archetypes

The V2 model supports these without changing the core: `StableEntity + Offers`,
`DigitalService + Plans`, `LocationEntity + Availability`, `Route/Event +
TemporalOffer`, `FinancialProduct + Eligibility/Fees`, `Subscription + Tiers`,
and `MarketplaceListing + Provider`. The additional cross-cutting archetype is
`Comparison/Intent + Explainable Selection`: it joins stable entities and
offers without duplicating their facts.

## Release invariants

`tests/fixtures/production-invariants.json` fixes the accepted legacy counts
and SHA-256 fingerprints of every indexable route and affiliate URL. The
regression validator checks those fingerprints, sampled canonical output, full
article output count and sitemap count. Updating that manifest is an explicit
review decision, not a side effect of a build.
