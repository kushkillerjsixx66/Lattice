from __future__ import annotations

import copy

import pytest

from engine.governance_receipt import proposal_fingerprint, validate_governance_receipt
from engine.store import ValidationError, WorldStore
from engine.transition_proposal import build_transition_proposal
from engine.valley import seed_valley


def _proposal(store):
    seed_valley(store)
    return build_transition_proposal(
        store,
        world_id="valley",
        expected_revision=1,
        actor="planner-agent",
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


def _receipt(proposal, decision="AUTHORIZED"):
    return {
        "receipt_id": "receipt-1",
        "decision": decision,
        "proposal_id": proposal["proposal_id"],
        "world_id": proposal["world_id"],
        "expected_revision": proposal["expected_revision"],
        "proposal_fingerprint": proposal_fingerprint(proposal),
        "authority_source": "external-governance-service",
        "decision_reference": "decision-record:123",
    }


def test_matching_authorized_receipt_still_does_not_authorize_execution(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        before = store.list_events("valley")
        result = validate_governance_receipt(proposal, _receipt(proposal))

        assert result["decision"] == "AUTHORIZED"
        assert result["receipt_binding_status"] == "MATCHED_UNVERIFIED"
        assert result["authorization_status"] == "UNVERIFIED"
        assert result["execution_permitted"] is False
        assert result["mutates_world"] is False
        assert result["grants_authority"] is False
        assert store.list_events("valley") == before


@pytest.mark.parametrize("decision", ["DENIED", "UNRESOLVED", "STALE"])
def test_non_authorizing_decisions_remain_non_authorizing(tmp_path, decision):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        result = validate_governance_receipt(proposal, _receipt(proposal, decision))
        assert result["decision"] == decision
        assert result["execution_permitted"] is False


def test_receipt_cannot_be_replayed_for_modified_proposal(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        changed = copy.deepcopy(proposal)
        changed["proposed_state_change"][0]["attributes"]["grain"] = 1
        with pytest.raises(ValidationError, match="does not match"):
            validate_governance_receipt(changed, receipt)


@pytest.mark.parametrize("field,value", [
    ("proposal_id", "other-proposal"),
    ("world_id", "other-world"),
    ("expected_revision", 2),
    ("proposal_fingerprint", "0" * 64),
])
def test_receipt_binding_mismatch_is_rejected(tmp_path, field, value):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        receipt[field] = value
        with pytest.raises(ValidationError, match="does not match"):
            validate_governance_receipt(proposal, receipt)


def test_malformed_receipt_is_rejected(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        receipt["decision"] = "MAYBE"
        with pytest.raises(ValidationError, match="decision"):
            validate_governance_receipt(proposal, receipt)


def test_fingerprint_changes_when_effect_changes(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        original = proposal_fingerprint(proposal)
        proposal["effect_description"] = "Different effect"
        assert proposal_fingerprint(proposal) != original


@pytest.mark.parametrize("proposal", [None, [], "not-an-object", 42])
def test_fingerprint_rejects_non_mapping_proposals(proposal):
    with pytest.raises(ValidationError, match="proposal must be an object"):
        proposal_fingerprint(proposal)


@pytest.mark.parametrize(
    "self_asserted_field",
    ["verified", "signature_valid", "trusted", "issuer_verified"],
)
def test_self_asserted_verification_metadata_never_authenticates_receipt(
    tmp_path, self_asserted_field
):
    """Caller-controlled claims cannot substitute for an independent verifier."""
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        receipt[self_asserted_field] = True

        result = validate_governance_receipt(proposal, receipt)

        assert result["receipt_binding_status"] == "MATCHED_UNVERIFIED"
        assert result["authorization_status"] == "UNVERIFIED"
        assert result["execution_permitted"] is False
        assert result["mutates_world"] is False
        assert result["grants_authority"] is False
