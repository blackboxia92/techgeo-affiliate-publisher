# Awin live ingestion (V2.4)

StackSignal can ingest one bounded Awin Enhanced retail feed without scraping.
The adapter reads its bearer token only from `AWIN_API_TOKEN`; it never writes
that value to a URL, data artifact, report, or log.

## Prerequisites

The publisher must first join an advertiser programme in Awin and confirm that
its Enhanced Product Feed is enabled for the intended locale. A publisher API
token can enumerate programmes, but it does not by itself grant product-feed
access. The Awin Product Feed List endpoint additionally requires its own feed
API key, created in Awin's Toolbox; it is not interchangeable with the Partner
API bearer token.

Configure the secret in the deployment environment, never in Git:

```text
AWIN_API_TOKEN=<Awin Partner API bearer token>
AWIN_PUBLISHER_ID=3107154
```

## Bounded run

Run only after an advertiser is joined and an Enhanced Feed is confirmed:

```text
python -m publisher ingest-awin-enhanced --advertiser-id <AWIN_ADVERTISER_ID> --locale es_ES --market ES --currency EUR --limit 100 --output data/ingest/awin/<batch> --history data/ingest/awin/history.json
```

The command stores the raw authorized feed response, normalized candidates,
an eligibility-gated `llm.json`, and a minimal lifecycle ledger. It does not
create public pages, alter legacy links, convert currency, or rank offers.

For a second snapshot, run the same command with a distinct `<batch>` and then:

```text
python -m publisher compare-ingest-snapshots data/ingest/awin/<batch-a>/normalized.json data/ingest/awin/<batch-b>/normalized.json
```

Missing offers are reported as observations. Lifecycle policy retains an entity
after a single missed snapshot; it does not delete it or redirect it.

## Publication guard

Every candidate goes through the existing `is_publishable()` gate. An Awin
listing is not treated as an editorial fact: price, availability, merchant and
affiliate route remain on `Offer`/`TemporalState`/`OfferHealth`; they are never
stored as permanent `Entity` facts. A record lacking verified editorial facts
therefore remains unpublished, even if its commercial fields are complete.
