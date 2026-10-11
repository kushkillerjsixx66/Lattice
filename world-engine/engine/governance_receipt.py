"""Structural validation for externally produced governance decision receipts.

A matching receipt is not proof of authenticity. This module has no trust store,
signature verifier, policy evaluator, or execution capability. It always returns
execution_permitted=False and authorization_status=UNVERIFIED.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .store import ValidationError

DECISION_STATUSES = {"AUTHORIZED", "DENIED", "UNRESOLVED", "STALE"}
_BOUND_FIELDS = (
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
)


def proposal_fingerprint(proposal: Mapping[str, Any]) -> str:
    """Return a deterministic digest of the proposal's decision-relevant fields."""
    if not isinstance(proposal, Mapping):
        raise ValidationError("proposal must be an object")
    missing = [field for field in _BOUND_FIELDS if field not in proposal]
    if missing:
        raise ValidationError(f"proposal missing fingerprint fields: {', '.join(missing)}")
    payload = {field: proposal[field] for field in _BOUND_FIELDS}
    try:
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("proposal fields must be valid finite JSON values") from exc
    return hashlib.sha256(canonical).hexdigest()


def validate_governance_receipt(
    proposal: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Check exact proposal binding and receipt shape without granting permission.

    The upstream governance service must authenticate the receipt and evaluate
    the applicable policy. This function does neither.
    """
    if not isinstance(proposal, Mapping) or not isinstance(receipt, Mapping):
        raise ValidationError("proposal and receipt must be objects")

    required = {
        "receipt_id": receipt.get("receipt_id"),
        "decision": receipt.get("decision"),
        "proposal_id": receipt.get("proposal_id"),
        "world_id": receipt.get("world_id"),
        "expected_revision": receipt.get("expected_revision"),
        "proposal_fingerprint": receipt.get("proposal_fingerprint"),
        "authority_source": receipt.get("authority_source"),
        "decision_reference": receipt.get("decision_reference"),
    }
    for field, value in required.items():
        if field == "expected_revision":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError("receipt expected_revision must be a non-negative integer")
        elif not isinstance(value, str) or not value.strip():
            raise ValidationError(f"receipt {field} must be a non-empty string")

    if receipt["decision"] not in DECISION_STATUSES:
        raise ValidationError("receipt decision must be AUTHORIZED, DENIED, UNRESOLVED, or STALE")

    fingerprint = proposal_fingerprint(proposal)
    expected_bindings = {
        "proposal_id": proposal.get("proposal_id"),
        "world_id": proposal.get("world_id"),
        "expected_revision": proposal.get("expected_revision"),
        "proposal_fingerprint": fingerprint,
    }
    mismatches = [
        field for field, expected in expected_bindings.items()
        if receipt[field] != expected
    ]
    if mismatches:
        raise ValidationError(
            "receipt does not match proposal fields: " + ", ".join(mismatches)
        )

    return {
        "receipt_schema": "world-governance-receipt-validation-v0.1",
        "receipt_id": receipt["receipt_id"],
        "proposal_id": proposal["proposal_id"],
        "proposal_fingerprint": fingerprint,
        "decision": receipt["decision"],
        "receipt_binding_status": "MATCHED_UNVERIFIED",
        "authorization_status": "UNVERIFIED",
        "execution_permitted": False,
        "mutates_world": False,
        "grants_authority": False,
        "limitations": [
            "Receipt authenticity has not been verified.",
            "Applicable governance policy has not been evaluated here.",
            "A matching receipt does not authorize execution.",
        ],
    }
