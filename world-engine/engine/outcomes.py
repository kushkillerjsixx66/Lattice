"""Revision-scoped descriptive comparison of committed world outcomes.

This module reports state differences only. A difference between revisions does
not, by itself, establish causation or identify which intervention caused it.
"""
from __future__ import annotations

from typing import Any

from .store import ValidationError, WorldStore


def _snapshot_at_revision(
    store: WorldStore, world_id: str, target_revision: int
) -> dict[str, dict[str, Any]]:
    world = store.get_world(world_id)
    if not isinstance(target_revision, int) or isinstance(target_revision, bool):
        raise ValidationError("target_revision must be an integer")
    if target_revision < 0 or target_revision > world["revision"]:
        raise ValidationError("target_revision must be within the world's revision history")

    entities: dict[str, dict[str, Any]] = {}
    for event in store.list_events(world_id):
        revision = event["post_revision"]
        if revision > target_revision:
            break
        payload = event["payload"]
        changes = payload.get("changes", []) if isinstance(payload, dict) else []
        if not isinstance(changes, list):
            raise ValidationError(f"malformed change history in event {event['event_id']}")
        for change in changes:
            if not isinstance(change, dict):
                raise ValidationError(f"malformed change record in event {event['event_id']}")
            entity_id = change.get("entity_id")
            op = change.get("op")
            if not isinstance(entity_id, str) or not entity_id:
                raise ValidationError(f"missing entity id in event {event['event_id']}")
            after = change.get("after")
            if op == "create":
                if not isinstance(after, dict):
                    raise ValidationError(f"malformed create record for {entity_id}")
                entities[entity_id] = {
                    "entity_type": after["entity_type"],
                    "attributes": after["attributes"],
                    "relationships": after["relationships"],
                    "lifecycle_state": after["lifecycle_state"],
                    "created_revision": revision,
                    "updated_revision": revision,
                    "provenance_event_id": event["event_id"],
                }
            elif op == "update":
                if entity_id not in entities or not isinstance(after, dict):
                    raise ValidationError(f"malformed update history for {entity_id}")
                entities[entity_id] = {
                    **entities[entity_id],
                    "entity_type": after["entity_type"],
                    "attributes": after["attributes"],
                    "relationships": after["relationships"],
                    "lifecycle_state": after["lifecycle_state"],
                    "updated_revision": revision,
                }
            elif op == "delete":
                if entity_id not in entities:
                    raise ValidationError(f"malformed delete history for {entity_id}")
                del entities[entity_id]
            else:
                raise ValidationError(f"unsupported operation in event history: {op!r}")
    return entities


def compare_world_revisions(
    store: WorldStore,
    *,
    baseline_revision: int,
    outcome_revision: int,
    world_id: str = "valley",
) -> dict[str, Any]:
    """Describe entity-state differences between two committed revisions.

    This is retrospective and read-only. It does not assert that a particular
    action caused the differences, and it does not mutate world or model state.
    """
    if not isinstance(baseline_revision, int) or isinstance(baseline_revision, bool):
        raise ValidationError("baseline_revision must be an integer")
    if not isinstance(outcome_revision, int) or isinstance(outcome_revision, bool):
        raise ValidationError("outcome_revision must be an integer")
    if baseline_revision < 0 or outcome_revision < 0:
        raise ValidationError("revision values must be non-negative")
    if outcome_revision < baseline_revision:
        raise ValidationError("outcome_revision must not precede baseline_revision")

    baseline = _snapshot_at_revision(store, world_id, baseline_revision)
    outcome = _snapshot_at_revision(store, world_id, outcome_revision)
    differences: list[dict[str, Any]] = []

    for entity_id in sorted(set(baseline) | set(outcome)):
        before = baseline.get(entity_id)
        after = outcome.get(entity_id)
        if before == after:
            continue
        if before is None:
            kind = "CREATED"
        elif after is None:
            kind = "DELETED"
        else:
            kind = "CHANGED"
        differences.append({
            "entity_id": entity_id,
            "change_kind": kind,
            "before": before,
            "after": after,
        })

    return {
        "world_id": world_id,
        "baseline_revision": baseline_revision,
        "outcome_revision": outcome_revision,
        "revision_distance": outcome_revision - baseline_revision,
        "differences": differences,
        "difference_count": len(differences),
        "causal_conclusion": False,
        "interpretation": (
            "Descriptive state differences only; this comparison does not establish causation."
        ),
        "mutates_world": False,
    }
