# Awin ES merchant selection (V2.5)

This shortlist is a discovery configuration, not an approval or a publishing
configuration. Every advertiser stays disabled until Awin exposes an authorized
feed and the publisher relationship has been confirmed.

## Live API scope

On 2026-09-27, the Publisher API returned 442 active ES programmes with a
`notjoined` relationship. The relevant sectors account for 94 programmes:
39 Home & Garden, 21 Electronic Superstore, 8 Electronic Accessories, 8
Department Stores, 6 PC & Video Games, 4 White Goods, 3 Office Supplies, 3
DIY and 2 Software Downloads.

The Publisher API exposes membership status, deeplink support, currency,
programme metadata, commission range and KPIs. It does not expose an
auto-approval flag or standard-feed availability through the general Partner
API token. Those values must therefore remain unverified rather than inferred.

## Tier A

| Advertiser | Why it is prioritized | Verified API facts | Feed status |
| --- | --- | --- | --- |
| 20982 — PcComponentes ES | Broad Spanish technology retailer; best first candidate for computers, components, peripherals and consumer technology. | ES, EUR, Electronic Superstore, links online, deep linking enabled; Awin Index 58.59. | Unverified; requires joined relationship or a Product Feed List key. |
| 9294 — alternate ES | Explicitly describes a catalogue of more than 30,000 hard/software, notebooks, TV, gaming, tools and household appliances. | ES, EUR, Electronic Superstore, links online, deep linking enabled. | Unverified; requires joined relationship or a Product Feed List key. |
| 17092 — Aosom ES | Broad home, garden, tools and household catalogue; provides category coverage complementary to technology retail. | ES, EUR, Home & Garden, links online, deep linking enabled; Awin Index 52.09. | Unverified; requires joined relationship or a Product Feed List key. |

## Tier B

| Advertiser | Role if Tier A is unavailable |
| --- | --- |
| 20598 — Leroy Merlin ES | Home, DIY and tools coverage. |
| 122484 — Dyson ES | Focused appliance/vacuum candidate; useful once a broad feed is proven. |
| 21707 — Samsung ES | Broad consumer-electronics manufacturer catalogue. |
| 124624 — Coolmod ES | PC hardware, components and gaming specialist. |
| 23677 — Xiaomi ES | Consumer electronics and smart-home coverage. |

All eight candidates were returned as active ES/EUR programmes, with online
links, deep linking enabled and membership `Not joined`. The API returned no
commission range for the current not-joined relationship; commission is not
used to select the first technical feed.

## Feed verification and approval

The standard Product Feed List is the authoritative check for the feed ID,
language, vertical, last import and mapped columns. Its key is distinct from
the Partner API bearer token. Once a programme is joined, wait up to one hour
for the relationship to appear in Create-a-Feed before treating a missing feed
as a failure.

The desired first feed must provide, at minimum, product name, Awin deep link,
merchant ID/name, price, currency, merchant deep link and `last_updated`.
GTIN/EAN, model, image, `in_stock` and `stock_quantity` are preferred. The
adapter already preserves missing values rather than inventing them.

## Gabi's minimal manual steps

1. In Awin, open and apply to **PcComponentes ES (advertiser 20982)**. Accept
   its terms only after reviewing them.
2. If it is manual or rejected, repeat for **alternate ES (9294)**, then
   **Aosom ES (17092)**.
3. Once one relationship is `Joined`, open **Toolbox → Create-a-Feed** for that
   advertiser. Confirm a retail feed with `es_ES`, and copy its Feed List API
   key only into a secret manager if feed-list discovery is needed.
4. Do not change `enabled` in `config/awin-candidates.json` until the above is
   actually confirmed.

No programme-join request is sent by StackSignal: joining may entail advertiser
terms and is an explicit publisher decision.

## First post-approval command

With `AWIN_API_TOKEN` supplied only by the process environment and the chosen
advertiser's Enhanced Feed confirmed:

```text
python -m publisher ingest-awin-enhanced --publisher-id 3107154 --advertiser-id 20982 --locale es_ES --market ES --currency EUR --limit 100 --output data/ingest/awin/pccomponentes-a --history data/ingest/awin/history.json
```

Run the same command later with a different output directory for snapshot B,
then use `compare-ingest-snapshots` on the two `normalized.json` files. This
does not publish pages; `is_publishable()` remains the final gate.
