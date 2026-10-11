from __future__ import annotations

import pytest

from engine.governance_receipt import proposal_fingerprint
from engine.governance_revalidation import revalidate_governance_receipt
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


def _receipt(proposal):
    return {
        "receipt_id": "receipt-1",
        "decision": "AUTHORIZED",
        "proposal_id": proposal["proposal_id"],
        "world_id": proposal["world_id"],
        "expected_revision": proposal["expected_revision"],
        "proposal_fingerprint": proposal_fingerprint(proposal),
        "authority_source": "external-governance-service",
        "decision_reference": "decision-record:123",
    }


def test_current_revision_is_reported_fresh_but_never_authorized(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        before_events = store.list_events("valley")
        result = revalidate_governance_receipt(store, proposal, _receipt(proposal))

        assert result["freshness_status"] == "FRESH"
        assert result["current_revision"] == result["expected_revision"] == 1
        assert result["decision_usable_for_current_revision"] is False
        assert result["authorization_status"] == "UNVERIFIED"
        assert result["execution_permitted"] is False
        assert result["mutates_world"] is False
        assert result["grants_authority"] is False
        assert store.list_events("valley") == before_events


def test_revision_drift_marks_receipt_stale_without_mutating_world(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        store.advance_world_time(
            "valley", expected_revision=1, steps=1,
            actor="test-clock", intent="create revision drift fixture",
        )
        before_events = store.list_events("valley")

        result = revalidate_governance_receipt(store, proposal, receipt)

        assert result["freshness_status"] == "STALE"
        assert result["expected_revision"] == 1
        assert result["current_revision"] == 2
        assert result["decision_usable_for_current_revision"] is False
        assert result["execution_permitted"] is False
        assert store.list_events("valley") == before_events


def test_receipt_bound_to_different_proposal_is_rejected(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        receipt = _receipt(proposal)
        receipt["proposal_fingerprint"] = "0" * 64

        with pytest.raises(ValidationError, match="does not match"):
            revalidate_governance_receipt(store, proposal, receipt)
