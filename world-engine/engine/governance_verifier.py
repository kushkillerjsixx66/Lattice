"""Cryptographic verification for externally issued governance receipts.

This is a non-authorizing primitive, not a production trust bootstrap or execution
gateway. The caller must obtain trust_records from an independently controlled
deployment trust source. Never pass receipt/request-supplied trust configuration.
No default issuer or key is trusted.
"""
from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .governance_receipt import DECISION_STATUSES, proposal_fingerprint
from .store import ValidationError

PAYLOAD_SCHEMA = "world-governance-signed-decision-v1"
_PAYLOAD_FIELDS = {
    "schema", "receipt_id", "issuer_id", "key_id", "decision",
    "decision_reference", "proposal_id", "world_id", "expected_revision",
    "proposal_fingerprint", "action_class", "issued_at", "expires_at",
    "nonce", "policy_ref", "policy_version",
}


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize the exact signed payload with deterministic UTF-8 JSON."""
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
        raise ValidationError("signed payload fields do not match the v1 contract")
    try:
        return json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("signed payload must contain finite JSON values") from exc


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


class ReceiptReplayStore:
    """Separate durable replay ledger; never writes to WorldStore or world events."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(database), isolation_level=None, timeout=5.0)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS consumed_governance_receipts (
                receipt_id TEXT PRIMARY KEY,
                issuer_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                consumed_at TEXT NOT NULL,
                UNIQUE(issuer_id, nonce)
            )"""
        )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "ReceiptReplayStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def consume(self, receipt_id: str, issuer_id: str, nonce: str, now: datetime) -> bool:
        try:
            self._db.execute(
                "INSERT INTO consumed_governance_receipts VALUES (?, ?, ?, ?)",
                (receipt_id, issuer_id, nonce, now.isoformat()),
            )
        except sqlite3.IntegrityError:
            return False
        return True


def verify_signed_governance_receipt(
    proposal: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    trust_records: Mapping[tuple[str, str], Mapping[str, Any]] | None,
    replay_store: ReceiptReplayStore,
    current_world_revision: int,
    expected_action_class: str,
    now: datetime | None = None,
    clock_skew_seconds: int = 30,
) -> dict[str, Any]:
    """Verify a signed receipt against independently supplied trust records.

    A VERIFIED result means only signature, issuer/key trust, scope, time,
    proposal binding, current revision, and replay checks passed. Policy is not
    evaluated here; execution_permitted, mutates_world, and grants_authority
    are unconditionally false.
    """
    base = {
        "verification_schema": "world-governance-verification-v1",
        "verification_status": "UNRESOLVED",
        "authenticity_status": "UNRESOLVED",
        "integrity_status": "UNRESOLVED",
        "issuer_trust_status": "UNRESOLVED",
        "scope_status": "UNRESOLVED",
        "validity_status": "UNRESOLVED",
        "replay_status": "NOT_CHECKED",
        "authorization_status": "NOT_EVALUATED",
        "execution_permitted": False,
        "mutates_world": False,
        "grants_authority": False,
        "verifier_id": "world-engine-ed25519-verifier",
        "verifier_version": "1.0.0",
        "trust_record_ref": None,
        "trust_bundle_version": None,
        "limitations": [
            "This verifier authenticates a signed decision artifact; it does not evaluate governance policy.",
            "A VERIFIED result is not execution permission.",
            "The caller must source trust records independently of the request and receipt.",
        ],
        "failure_reasons": [],
    }

    def fail(status: str, reason: str, **updates: Any) -> dict[str, Any]:
        result = dict(base)
        result.update(updates)
        result["verification_status"] = status
        result["failure_reasons"] = [reason]
        return result

    if not isinstance(proposal, Mapping) or not isinstance(envelope, Mapping):
        raise ValidationError("proposal and signed receipt envelope must be objects")
    if isinstance(current_world_revision, bool) or not isinstance(current_world_revision, int) or current_world_revision < 0:
        raise ValidationError("current_world_revision must be a non-negative integer")
    if not isinstance(expected_action_class, str) or not expected_action_class.strip():
        raise ValidationError("expected_action_class must be a non-empty string")
    if not isinstance(trust_records, Mapping) or not trust_records:
        return fail("UNRESOLVED", "independent trust configuration is missing or empty")

    payload = envelope.get("payload")
    signature_text = envelope.get("signature")
    canonical = canonical_payload_bytes(payload) if isinstance(payload, Mapping) else None
    if canonical is None:
        raise ValidationError("envelope payload must be an object")
    if not isinstance(signature_text, str) or not signature_text:
        raise ValidationError("envelope signature must be a non-empty base64 string")

    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("envelope signature must be valid base64") from exc
    if len(signature) != 64:
        raise ValidationError("Ed25519 signature must decode to 64 bytes")

    required_strings = (
        "receipt_id", "issuer_id", "key_id", "decision", "decision_reference",
        "proposal_id", "world_id", "proposal_fingerprint", "action_class",
        "nonce", "policy_ref", "policy_version",
    )
    for field in required_strings:
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"signed payload {field} must be a non-empty string")
    revision = payload["expected_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValidationError("signed payload expected_revision must be a non-negative integer")
    if payload["schema"] != PAYLOAD_SCHEMA:
        return fail("REJECTED", "unsupported signed payload schema")
    if payload["decision"] not in DECISION_STATUSES:
        raise ValidationError("signed payload decision is not recognized")

    if payload["world_id"] != proposal.get("world_id") or payload["proposal_id"] != proposal.get("proposal_id"):
        return fail("REJECTED", "receipt proposal/world binding mismatch", integrity_status="FAILED")
    if revision != proposal.get("expected_revision") or revision != current_world_revision:
        return fail("REJECTED", "receipt revision is stale or does not match the proposal", integrity_status="FAILED")
    fingerprint = proposal_fingerprint(proposal)
    if payload["proposal_fingerprint"] != fingerprint:
        return fail("REJECTED", "proposal fingerprint mismatch", integrity_status="FAILED")
    if payload["action_class"] != expected_action_class:
        return fail("REJECTED", "action class does not match trusted caller context", scope_status="FAILED")

    record = trust_records.get((payload["issuer_id"], payload["key_id"]))
    if not isinstance(record, Mapping):
        return fail("REJECTED", "issuer/key pair is not present in independent trust configuration",
                    issuer_trust_status="FAILED")
    if record.get("issuer_id") != payload["issuer_id"] or record.get("key_id") != payload["key_id"]:
        return fail("UNRESOLVED", "trust record identity is inconsistent", issuer_trust_status="UNRESOLVED")

    bundle_version = record.get("trust_bundle_version")
    if not isinstance(bundle_version, str) or not bundle_version.strip():
        return fail("UNRESOLVED", "trust record has no version", issuer_trust_status="UNRESOLVED")
    result_fields = {
        "trust_record_ref": record.get("trust_record_ref"),
        "trust_bundle_version": bundle_version,
    }
    try:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if current_time.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        issued_at = _timestamp(payload["issued_at"], "issued_at")
        expires_at = _timestamp(payload["expires_at"], "expires_at")
        key_start = _timestamp(record.get("not_before"), "trust record not_before")
        key_end = _timestamp(record.get("not_after"), "trust record not_after")
        revoked_at_value = record.get("revoked_at")
        revoked_at = _timestamp(revoked_at_value, "trust record revoked_at") if revoked_at_value else None
    except (ValidationError, ValueError, AttributeError) as exc:
        return fail("UNRESOLVED", f"invalid time configuration: {exc}", **result_fields)

    max_ttl = record.get("max_ttl_seconds")
    if isinstance(max_ttl, bool) or not isinstance(max_ttl, int) or max_ttl <= 0:
        return fail("UNRESOLVED", "trust record max_ttl_seconds is missing or invalid", **result_fields)
    if expires_at <= issued_at or (expires_at - issued_at).total_seconds() > max_ttl:
        return fail("REJECTED", "receipt validity window is invalid or exceeds issuer policy",
                    validity_status="FAILED", **result_fields)
    if issued_at > current_time + timedelta(seconds=clock_skew_seconds):
        return fail("REJECTED", "receipt issue time is in the future", validity_status="FAILED", **result_fields)
    if current_time >= expires_at or current_time < key_start or current_time >= key_end:
        return fail("REJECTED", "receipt or signing key is outside its validity window",
                    validity_status="FAILED", **result_fields)
    if revoked_at is not None and current_time >= revoked_at:
        return fail("REJECTED", "signing key is revoked", issuer_trust_status="REVOKED", **result_fields)

    worlds = record.get("allowed_world_ids")
    actions = record.get("allowed_action_classes")
    if not isinstance(worlds, list) or not isinstance(actions, list):
        return fail("UNRESOLVED", "trust record scope configuration is malformed", **result_fields)
    if payload["world_id"] not in worlds or payload["action_class"] not in actions:
        return fail("REJECTED", "issuer/key is not trusted for this world and action class",
                    scope_status="FAILED", **result_fields)

    public_key_text = record.get("public_key_b64")
    try:
        public_key_bytes = base64.b64decode(public_key_text, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, canonical)
    except (TypeError, ValueError, binascii.Error, InvalidSignature):
        return fail("REJECTED", "signature or configured public key is invalid",
                    authenticity_status="FAILED", issuer_trust_status="FAILED", **result_fields)

    result_fields.update({
        "receipt_id": payload["receipt_id"],
        "receipt_digest": __import__("hashlib").sha256(canonical).hexdigest(),
        "decision": payload["decision"],
        "policy_ref": payload["policy_ref"],
        "policy_version": payload["policy_version"],
        "authenticity_status": "VERIFIED",
        "integrity_status": "VERIFIED",
        "issuer_trust_status": "TRUSTED",
        "scope_status": "VERIFIED",
        "validity_status": "VALID",
    })
    if not replay_store.consume(payload["receipt_id"], payload["issuer_id"], payload["nonce"], current_time):
        return fail("REJECTED", "receipt ID or issuer nonce has already been consumed",
                    replay_status="REPLAYED", **result_fields)
    result_fields["replay_status"] = "UNIQUE"
    result = dict(base)
    result.update(result_fields)
    result["verification_status"] = "VERIFIED"
    result["failure_reasons"] = []
    return result
