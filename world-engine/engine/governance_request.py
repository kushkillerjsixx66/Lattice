"""Build read-only requests for an external governance evaluator.

This module defines an integration boundary only. It does not evaluate policy,
authenticate a decision, grant authority, or execute a world transition.
"""
from __future__ import annotations

import uuid
from typing import Any, Mapping

from .governance_receipt import proposal_fingerprint
from .store import ValidationError

REQUESTED_REVIEW_AREAS = (
    "authority_basis",
    "constraint_compliance",
    "lineage_integrity",
    "reversibility_and_recovery",
    "uncertainty_handling",
    "current_revision_and_scope",
)


def build_governance_request(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Package a proposal for external review without implying a decision."""
    if not isinstance(proposal, Mapping):
        raise ValidationError("proposal must be an object")

    fingerprint = proposal_fingerprint(proposal)
    proposal_id = proposal.get("proposal_id")
    world_id = proposal.get("world_id")
    expected_revision = proposal.get("expected_revision")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ValidationError("proposal_id must be a non-empty string")
    if not isinstance(world_id, str) or not world_id.strip():
        raise ValidationError("world_id must be a non-empty string")
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise ValidationError("expected_revision must be a non-negative integer")

    return {
        "request_schema": "world-governance-request-v0.1",
        "request_id": str(uuid.uuid4()),
        "proposal_id": proposal_id,
        "world_id": world_id,
        "expected_revision": expected_revision,
        "proposal_fingerprint": fingerprint,
        "proposal": {key: proposal[key] for key in (
            "proposal_schema",
            "proposal_id",
            "world_id",
            "expected_revision",
            "actor",
            "intent",
            "authority_reference",
            "constraints",
            "evidence",
            "proposed_state_change",
            "effect_description",
            "reversibility",
            "recovery_plan",
            "lineage_reference",
        )},
        "requested_review_areas": list(REQUESTED_REVIEW_AREAS),
        "request_status": "PENDING_EXTERNAL_EVALUATION",
        "authorization_status": "NOT_EVALUATED",
        "execution_status": "NOT_EXECUTED",
        "execution_permitted": False,
        "mutates_world": False,
        "grants_authority": False,
        "limitations": [
            "This request is not a governance decision.",
            "Requested review areas do not define or replace canonical policy.",
            "The recipient must independently authenticate its authority and evaluate applicable policy.",
            "Any returned decision must be separately verified and bound to this exact proposal and revision.",
        ],
    }
