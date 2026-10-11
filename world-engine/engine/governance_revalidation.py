"""Read-only freshness check for externally supplied governance receipts.

This module detects revision drift after structural receipt binding. It does not
authenticate a receipt, evaluate policy, grant authority, or execute a transition.
"""
from __future__ import annotations

from typing import Any, Mapping

from .governance_receipt import validate_governance_receipt
from .store import ValidationError, WorldStore


def revalidate_governance_receipt(
    store: WorldStore,
    proposal: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Check receipt binding and whether the proposal's expected revision is current.

    A FRESH result means only that the current world revision still matches the
    proposal revision. It is not an authorization decision and must never be
    used as a standalone execution permit.
    """
    if not isinstance(proposal, Mapping):
        raise ValidationError("proposal must be an object")

    binding = validate_governance_receipt(proposal, receipt)
    world_id = proposal.get("world_id")
    expected_revision = proposal.get("expected_revision")
    if not isinstance(world_id, str) or not world_id.strip():
        raise ValidationError("proposal world_id must be a non-empty string")
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise ValidationError("proposal expected_revision must be a non-negative integer")

    world = store.get_world(world_id)
    current_revision = world["revision"]
    freshness = "FRESH" if current_revision == expected_revision else "STALE"

    return {
        "revalidation_schema": "world-governance-revalidation-v0.1",
        "receipt_id": binding["receipt_id"],
        "proposal_id": binding["proposal_id"],
        "world_id": world_id,
        "proposal_fingerprint": binding["proposal_fingerprint"],
        "expected_revision": expected_revision,
        "current_revision": current_revision,
        "freshness_status": freshness,
        "decision_usable_for_current_revision": False,
        "receipt_binding_status": binding["receipt_binding_status"],
        "authorization_status": "UNVERIFIED",
        "execution_permitted": False,
        "mutates_world": False,
        "grants_authority": False,
        "limitations": [
            "Freshness checks do not authenticate the receipt or its authority source.",
            "Applicable governance policy has not been evaluated here.",
            "FRESH means revision-matched only; it is not permission to execute.",
            "Any later execution boundary must recheck drift and independently verify authority.",
        ],
    }
