# StackSignal V2 domain model

The static site remains a single build from `content/pages/**/*.json`. V2 is an
internal adapter, so existing files and their historical `/guides/<slug>/`
routes do not move.

```text
Intent -> CategorySchema -> Entity -> Fact <- Source/provenance
                                      |
                                      +-> Offer -> AffiliateRoute
                                      |
                                      +-> static HTML / JSON-LD / Markdown / JSON
```

- `Entity` contains the stable identity and source-backed facts.
- `Fact` can carry `source_id` and `verified_at`; legacy facts retain their
  page-level verification date and deliberately have no invented field source.
- `TemporalState` is attached to an `Offer`, never used as a permanent entity
  fact. It supports market, currency, price, availability and verification
  time when a future feed has those facts.
- `AffiliateRoute` is separate from an `Offer`. The legacy adapter creates an
  `amazon-associates-direct` route for every existing resource and gives it
  priority, preserving the exact historical affiliate URL.
- `Intent.canonical_intent` is a stable comparison key. It is emitted in the
  non-canonical JSON representation and can later prevent duplicate briefs.

## Category rendering

`CategorySchema` declares typed `AttributeSchema` field contracts (key, value
type, optional unit, comparability and required flag) and chooses visible
criteria at build time. It does not mutate the legacy JSON. A row must be
category-relevant and useful for at least half of the alternatives. Known
placeholder forms (`N/A`, `N/D`, `not measured`, etc.) are ignored. CI/CD
permits only its decision dimensions; consumer-product pages omit synthetic
hardware memory/power rows; hardware pages retain useful memory and power data.

## New comparison draft

Use the small data factory instead of copying markup:

```python
from publisher.v2 import create_comparison

draft = create_comparison(
    slug="alpha-vs-beta-for-platform-teams",
    title="Alpha vs Beta for platform teams",
    category="software",
    audience="platform teams",
    alternatives=[
        {"name": "Alpha", "url": "https://vendor.example/alpha", "summary": "...", "specs": {"fit": "..."}},
        {"name": "Beta", "url": "https://vendor.example/beta", "summary": "...", "specs": {"fit": "..."}},
    ],
    criteria=[{"key": "fit", "label": "Team fit", "description": "Decision relevance."}],
    sources=[{"label": "Official docs", "publisher": "Vendor", "url": "https://vendor.example/docs"}],
)
```

Save the resulting JSON under `content/pages/`. It is an intentionally
`draft` payload: fill the source-backed criteria, sources, FAQ and editorial
fields, then change it to `reviewed`. No template edit is required. Editing a
fact, source, resource, or offer in the JSON and rebuilding updates every
derived surface (HTML, JSON-LD where applicable, Markdown and JSON) from the
same source.

`category` currently accepts `ci-cd`, `software`, `hardware`, and
`consumer-product`. New domains can add a `CategorySchema` without changing a
template or the legacy adapter.
