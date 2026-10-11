"""Epistemic records kept separate from authoritative simulated state.

A claim records what a source asserts about a subject at a particular world
revision. The ledger preserves conflicting claims rather than choosing a winner.
It is evidence bookkeeping, not an inference engine or authorization service.
"""
from __future__ import annotations

from typing import Any

from .store import ValidationError, WorldStore

EPISTEMIC_STATUSES = ("OBSERVED", "INFERRED", "HYPOTHESIS", "UNKNOWN")


def observe_committed_world(store: WorldStore, world_id: str = "valley") -> dict[str, Any]:
    """Append a snapshot of committed simulation facts as OBSERVED claims.

    OBSERVED means observed in the authoritative simulated state, not verified
    truth about the external world. Each claim carries its source entity and the
    exact world revision from which the snapshot was read.
    """
    world = store.get_world(world_id)
    revision = world["revision"]
    entities = store.list_entities(world_id)
    claims = []
    for entity in entities:
        subject = entity["entity_id"]
        source_ref = f"entity:{subject}@revision:{revision}"
        facts = {
            "entity_type": entity["entity_type"],
            "lifecycle_state": entity["lifecycle_state"],
            "relationships": entity["relationships"],
            **entity["attributes"],
        }
        for predicate, value in sorted(facts.items()):
            claims.append(store.record_claim(
                world_id,
                subject=subject,
                predicate=predicate,
                value=value,
                epistemic_status="OBSERVED",
                source="world-engine-committed-state",
                source_ref=source_ref,
                world_revision=revision,
            ))
    return {
        "world_id": world_id,
        "world_revision": revision,
        "claim_count": len(claims),
        "claims": claims,
        "mutates_world": False,
    }


def record_model_claim(
    store: WorldStore,
    world_id: str,
    *,
    subject: str,
    predicate: str,
    value: Any,
    epistemic_status: str,
    source: str,
    source_ref: str,
    world_revision: int,
) -> dict[str, Any]:
    """Record a model-side assertion without changing world state."""
    if epistemic_status not in EPISTEMIC_STATUSES:
        raise ValidationError(f"unsupported epistemic status: {epistemic_status!r}")
    return store.record_claim(
        world_id,
        subject=subject,
        predicate=predicate,
        value=value,
        epistemic_status=epistemic_status,
        source=source,
        source_ref=source_ref,
        world_revision=world_revision,
    )


def read_epistemic_model(
    store: WorldStore, world_id: str = "valley", world_revision: int | None = None
) -> dict[str, Any]:
    """Return the claims and derived conflict labels for a requested scope."""
    world = store.get_world(world_id)
    revision = world["revision"] if world_revision is None else world_revision
    claims = store.list_claims(world_id, revision)
    return {
        "world_id": world_id,
        "world_revision": revision,
        "claims": claims,
        "claim_count": len(claims),
        "conflicted_count": sum(c["effective_status"] == "CONFLICTED" for c in claims),
        "mutates_world": False,
    }
