"""Deterministic lifecycle policy for entities and offers."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .v2 import Entity, Offer


@dataclass(frozen=True)
class LifecycleHistory:
    last_seen_at: str | None = None
    missing_since: str | None = None
    last_offer_seen_at: str | None = None
    last_verified_at: str | None = None
    consecutive_missing_count: int = 0
    explicit_discontinued: bool = False
    official_successor_id: str | None = None
    has_residual_value: bool = True
    has_traffic: bool = False


@dataclass(frozen=True)
class LifecycleDecision:
    status: str
    reasons: tuple[str, ...]
    action: str
    publishable: bool
    indexable: bool
    show_alternatives: bool
    requires_redirect: bool
    requires_retirement: bool


def advance_history(
    history: LifecycleHistory,
    *,
    entity_seen: bool,
    offer_seen: bool,
    observed_at: str,
) -> LifecycleHistory:
    """Advance snapshot evidence without converting a first miss into removal."""
    if entity_seen:
        return LifecycleHistory(
            last_seen_at=observed_at,
            missing_since=None,
            last_offer_seen_at=observed_at if offer_seen else history.last_offer_seen_at,
            last_verified_at=observed_at,
            consecutive_missing_count=0,
            explicit_discontinued=history.explicit_discontinued,
            official_successor_id=history.official_successor_id,
            has_residual_value=history.has_residual_value,
            has_traffic=history.has_traffic,
        )
    return LifecycleHistory(
        last_seen_at=history.last_seen_at,
        missing_since=history.missing_since or observed_at,
        last_offer_seen_at=history.last_offer_seen_at,
        last_verified_at=history.last_verified_at,
        consecutive_missing_count=history.consecutive_missing_count + 1,
        explicit_discontinued=history.explicit_discontinued,
        official_successor_id=history.official_successor_id,
        has_residual_value=history.has_residual_value,
        has_traffic=history.has_traffic,
    )


def update_history_ledger(
    path: Path,
    *,
    entity_ids: Iterable[str],
    offers: Iterable[Offer],
    observed_at: str,
) -> dict[str, LifecycleHistory]:
    """Persist minimal snapshot history in one local JSON file (no new DB)."""
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current_entities = set(entity_ids)
    current_offer_entities = {offer.entity_id for offer in offers}
    result: dict[str, LifecycleHistory] = {}
    for entity_id in set(previous) | current_entities:
        old = LifecycleHistory(**previous.get(entity_id, {}))
        result[entity_id] = advance_history(
            old,
            entity_seen=entity_id in current_entities,
            offer_seen=entity_id in current_offer_entities,
            observed_at=observed_at,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: asdict(value) for key, value in sorted(result.items())}, indent=2) + "\n", encoding="utf-8")
    return result


def evaluate_lifecycle(entity: Entity, offers: Iterable[Offer], history: LifecycleHistory) -> LifecycleDecision:
    """Choose a safe action; never 301 or delete from a single absence."""
    offers = tuple(offers)
    active = [offer for offer in offers if offer.temporal_state.availability == "active"]
    unavailable = [offer for offer in offers if offer.temporal_state.availability == "temporarily_unavailable"]
    if active:
        return LifecycleDecision("active", ("at least one active offer",), "keep", True, True, False, False, False)
    if history.explicit_discontinued:
        if history.official_successor_id:
            return LifecycleDecision(
                "replaced", ("official discontinuation", "official successor recorded"), "review-successor",
                True, True, True, False, False,
            )
        return LifecycleDecision(
            "discontinued", ("official discontinuation",), "keep-context-and-alternatives",
            True, True, True, False, False,
        )
    if unavailable:
        return LifecycleDecision(
            "temporarily_unavailable", ("offers reported unavailable",), "keep-and-recheck",
            True, True, True, False, False,
        )
    if history.consecutive_missing_count < 3:
        return LifecycleDecision(
            "stale", ("offer absent without enough consecutive snapshots",), "retain-and-recheck",
            True, True, False, False, False,
        )
    if history.has_residual_value or history.has_traffic:
        return LifecycleDecision(
            "retired", ("offers absent across multiple snapshots", "residual informational or traffic value"),
            "noindex-after-editor-review", True, False, True, False, False,
        )
    return LifecycleDecision(
        "retired", ("offers absent across multiple snapshots", "no residual value or traffic"),
        "evaluate-410-after-editor-review", False, False, False, False, True,
    )


@dataclass(frozen=True)
class SnapshotChange:
    kind: str
    key: str
    detail: str


def compare_offer_snapshots(previous: Iterable[Offer], current: Iterable[Offer]) -> tuple[SnapshotChange, ...]:
    """Compare snapshots without treating a missing offer as a deletion."""
    before = {offer.id: offer for offer in previous}
    after = {offer.id: offer for offer in current}
    changes: list[SnapshotChange] = []
    for offer_id in sorted(before.keys() - after.keys()):
        changes.append(SnapshotChange("offer_missing", offer_id, "absent from current snapshot"))
    for offer_id in sorted(after.keys() - before.keys()):
        changes.append(SnapshotChange("offer_new", offer_id, "new offer in current snapshot"))
    for offer_id in sorted(before.keys() & after.keys()):
        old, new = before[offer_id], after[offer_id]
        if old.temporal_state.price != new.temporal_state.price:
            changes.append(SnapshotChange("price_changed", offer_id, "price changed"))
        if old.temporal_state.availability != new.temporal_state.availability:
            changes.append(SnapshotChange("availability_changed", offer_id, "availability changed"))
        if old.raw_destination_url != new.raw_destination_url:
            changes.append(SnapshotChange("destination_changed", offer_id, "destination URL changed"))
        if old.merchant_id != new.merchant_id:
            changes.append(SnapshotChange("merchant_changed", offer_id, "merchant changed"))
    return tuple(changes)
