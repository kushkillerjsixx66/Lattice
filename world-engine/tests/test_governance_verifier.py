from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from engine.governance_receipt import proposal_fingerprint
from engine.governance_verifier import (
    PAYLOAD_SCHEMA,
    ReceiptReplayStore,
    canonical_payload_bytes,
    verify_signed_governance_receipt,
)
from engine.store import WorldStore, ValidationError
from engine.transition_proposal import build_transition_proposal
from engine.valley import seed_valley


NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def _proposal(store):
    seed_valley(store)
    return build_transition_proposal(
        store, world_id="valley", expected_revision=1, actor="planner-agent",
        intent="transfer five grain units",
        changes=[{"op": "update", "entity_id": "north", "attributes": {"grain": 75}}],
        authority_reference="authority-record:example",
        constraints=["route-capacity<=10", "source-stock>=5"],
        evidence=["snapshot:valley:revision-1"],
        effect_description="Reduce north grain stock by five",
        reversibility="CONDITIONALLY_REVERSIBLE",
        recovery_plan="Restore only if no dependent transition occurred",
        lineage_reference="planner-run:turn-1",
    )


def _signed(proposal, private_key, **overrides):
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "receipt_id": "receipt-1",
        "issuer_id": "test-governance-issuer",
        "key_id": "key-2026-01",
        "decision": "AUTHORIZED",
        "decision_reference": "decision-123",
        "proposal_id": proposal["proposal_id"],
        "world_id": proposal["world_id"],
        "expected_revision": proposal["expected_revision"],
        "proposal_fingerprint": proposal_fingerprint(proposal),
        "action_class": "valley.grain.transfer",
        "issued_at": (NOW - timedelta(seconds=10)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=2)).isoformat(),
        "nonce": "nonce-1",
        "policy_ref": "canonical-policy-ref",
        "policy_version": "revision-42",
    }
    payload.update(overrides)
    signature = private_key.sign(canonical_payload_bytes(payload))
    return {"payload": payload, "signature": base64.b64encode(signature).decode()}


def _trust(private_key, **overrides):
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    record = {
        "issuer_id": "test-governance-issuer",
        "key_id": "key-2026-01",
        "public_key_b64": base64.b64encode(public_bytes).decode(),
        "trust_record_ref": "deployment-trust-bundle:test-v1",
        "trust_bundle_version": "test-v1",
        "not_before": (NOW - timedelta(days=1)).isoformat(),
        "not_after": (NOW + timedelta(days=30)).isoformat(),
        "revoked_at": None,
        "allowed_world_ids": ["valley"],
        "allowed_action_classes": ["valley.grain.transfer"],
        "max_ttl_seconds": 300,
    }
    record.update(overrides)
    return {("test-governance-issuer", "key-2026-01"): record}


def _verify(proposal, envelope, trust, replay, **kwargs):
    return verify_signed_governance_receipt(
        proposal, envelope, trust_records=trust, replay_store=replay,
        current_world_revision=1, expected_action_class="valley.grain.transfer",
        now=NOW, **kwargs,
    )


def test_valid_signature_verifies_receipt_but_never_authorizes_execution(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world:
        proposal = _proposal(world)
        before = world.list_events("valley")
        with ReceiptReplayStore(tmp_path / "replay.sqlite3") as replay:
            result = _verify(proposal, _signed(proposal, private_key), _trust(private_key), replay)
        assert result["verification_status"] == "VERIFIED"
        assert result["authenticity_status"] == "VERIFIED"
        assert result["integrity_status"] == "VERIFIED"
        assert result["issuer_trust_status"] == "TRUSTED"
        assert result["scope_status"] == "VERIFIED"
        assert result["validity_status"] == "VALID"
        assert result["replay_status"] == "UNIQUE"
        assert result["authorization_status"] == "NOT_EVALUATED"
        assert result["execution_permitted"] is False
        assert result["mutates_world"] is False
        assert result["grants_authority"] is False
        assert world.list_events("valley") == before


def test_missing_trust_configuration_is_unresolved(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        result = _verify(proposal, _signed(proposal, private_key), None, replay)
        assert result["verification_status"] == "UNRESOLVED"
        assert result["execution_permitted"] is False


@pytest.mark.parametrize("change", [
    {"world_id": "other-world"},
    {"proposal_fingerprint": "0" * 64},
    {"action_class": "admin.root"},
    {"expires_at": (NOW + timedelta(hours=2)).isoformat()},
])
def test_modified_or_out_of_policy_signed_payload_does_not_verify(tmp_path, change):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key, **change)
        result = _verify(proposal, envelope, _trust(private_key), replay)
        assert result["verification_status"] == "REJECTED"
        assert result["execution_permitted"] is False


def test_authenticated_denial_verifies_but_never_authorizes(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key, decision="DENIED")
        result = _verify(proposal, envelope, _trust(private_key), replay)
        assert result["verification_status"] == "VERIFIED"
        assert result["decision"] == "DENIED"
        assert result["authorization_status"] == "NOT_EVALUATED"
        assert result["execution_permitted"] is False
        assert result["mutates_world"] is False
        assert result["grants_authority"] is False


def test_tampered_payload_signature_is_rejected(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key)
        envelope["payload"]["decision_reference"] = "tampered"
        result = _verify(proposal, envelope, _trust(private_key), replay)
        assert result["verification_status"] == "REJECTED"
        assert result["authenticity_status"] == "FAILED"


def test_unknown_issuer_key_is_rejected(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        result = _verify(proposal, _signed(proposal, private_key), {}, replay)
        assert result["verification_status"] == "UNRESOLVED"


def test_revoked_key_is_rejected(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        trust = _trust(private_key, revoked_at=(NOW - timedelta(minutes=1)).isoformat())
        result = _verify(proposal, _signed(proposal, private_key), trust, replay)
        assert result["verification_status"] == "REJECTED"
        assert result["issuer_trust_status"] == "REVOKED"


def test_expired_receipt_is_rejected(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key,
                           expires_at=(NOW - timedelta(seconds=1)).isoformat())
        result = _verify(proposal, envelope, _trust(private_key), replay)
        assert result["verification_status"] == "REJECTED"


def test_current_world_revision_must_match_receipt(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        result = verify_signed_governance_receipt(
            proposal, _signed(proposal, private_key), trust_records=_trust(private_key),
            replay_store=replay, current_world_revision=2,
            expected_action_class="valley.grain.transfer", now=NOW,
        )
        assert result["verification_status"] == "REJECTED"


def test_replay_is_persistently_rejected(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key)
        trust = _trust(private_key)
        with ReceiptReplayStore(tmp_path / "replay.sqlite3") as replay:
            first = _verify(proposal, envelope, trust, replay)
        with ReceiptReplayStore(tmp_path / "replay.sqlite3") as replay:
            second = _verify(proposal, envelope, trust, replay)
        assert first["verification_status"] == "VERIFIED"
        assert second["verification_status"] == "REJECTED"
        assert second["replay_status"] == "REPLAYED"
        assert second["execution_permitted"] is False


def test_unknown_signed_payload_fields_are_rejected(tmp_path):
    with pytest.raises(ValidationError, match="fields do not match"):
        canonical_payload_bytes({"unexpected": True})


def test_receipt_self_asserted_verified_flag_is_not_signed_contract_input(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    with WorldStore(tmp_path / "world.sqlite3") as world, ReceiptReplayStore() as replay:
        proposal = _proposal(world)
        envelope = _signed(proposal, private_key)
        envelope["verified"] = True
        result = _verify(proposal, envelope, _trust(private_key), replay)
        assert result["verification_status"] == "VERIFIED"
        assert result["authorization_status"] == "NOT_EVALUATED"
        assert result["execution_permitted"] is False
