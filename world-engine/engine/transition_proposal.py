"""Validated, non-authorizing envelopes for exact proposed world transitions.

This module records intent and required evidence fields. It does not decide
whether the actor is authorized and cannot execute the proposed transition.
"""
from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from .store import RevisionConflict, ValidationError, WorldStore

REVERSIBILITY_CLASSES = {
    "REVERSIBLE",
    "CONDITIONALLY_REVERSIBLE",
    "IRREVERSIBLE",
    "UNKNOWN",
}


def build_transition_proposal(
    store: WorldStore,
    *,
    world_id: str,
    expected_revision: int,
    actor: str,
    intent: str,
    changes: Sequence[Mapping[str, Any]],
    authority_reference: str,
    constraints: Sequence[str],
    evidence: Sequence[str],
    effect_description: str,
    reversibility: str,
    recovery_plan: str | None,
    lineage_reference: str,
) -> dict[str, Any]:
    """Build a validated proposal envelope without changing world state.

    authority_reference is an auditable reference only, not proof of authority.
    A caller must separately evaluate authority and constraints before execution.
    """
    required_strings = {
        "world_id": world_id,
        "actor": actor,
        "intent": intent,
        "authority_reference": authority_reference,
        "effect_description": effect_description,
        "lineage_reference": lineage_reference,
    }
    for field, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field} must be a non-empty string")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValidationError("expected_revision must be a non-negative integer")
    if not isinstance(changes, Sequence) or isinstance(changes, (str, bytes)) or not changes:
        raise ValidationError("changes must be a non-empty sequence of change objects")
    normalized_changes: list[dict[str, Any]] = []
    for index, change in enumerate(changes):
        if not isinstance(change, Mapping) or not isinstance(change.get("op"), str):
            raise ValidationError(f"changes[{index}] must be an object with an op")
        normalized_changes.append(dict(change))
    for field, values in (("constraints", constraints), ("evidence", evidence)):
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValidationError(f"{field} must be a sequence of references")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValidationError(f"{field} entries must be non-empty strings")
    if not constraints:
        raise ValidationError("constraints must explicitly list at least one constraint")
    if not evidence:
        raise ValidationError("evidence must explicitly list at least one evidence reference")
    if reversibility not in REVERSIBILITY_CLASSES:
        raise ValidationError("reversibility must be a declared reversibility class")
    if reversibility in {"REVERSIBLE", "CONDITIONALLY_REVERSIBLE"}:
        if not isinstance(recovery_plan, str) or not recovery_plan.strip():
            raise ValidationError("reversible proposals require an explicit recovery_plan")
    elif recovery_plan is not None and (
        not isinstance(recovery_plan, str) or not recovery_plan.strip()
    ):
        raise ValidationError("recovery_plan must be null or a non-empty string")

    world = store.get_world(world_id)
    current_revision = world["revision"]
    if current_revision != expected_revision:
        raise RevisionConflict(
            f"proposal expected revision {expected_revision}, current revision is {current_revision}"
        )

    return {
        "proposal_schema": "world-transition-proposal-v0.1",
        "proposal_id": str(uuid.uuid4()),
        "world_id": world_id,
        "expected_revision": expected_revision,
        "actor": actor,
        "intent": intent,
        "authority_reference": authority_reference,
        "constraints": list(constraints),
        "evidence": list(evidence),
        "proposed_state_change": normalized_changes,
        "effect_description": effect_description,
        "reversibility": reversibility,
        "recovery_plan": recovery_plan,
        "lineage_reference": lineage_reference,
        "authorization_status": "NOT_EVALUATED",
        "execution_status": "NOT_EXECUTED",
        "mutates_world": False,
        "grants_authority": False,
    }
