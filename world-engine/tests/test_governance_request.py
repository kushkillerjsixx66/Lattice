from __future__ import annotations

import copy

import pytest

from engine.governance_request import (
    REQUESTED_REVIEW_AREAS,
    build_governance_request,
)
from engine.governance_receipt import proposal_fingerprint
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


def test_request_is_revision_bound_and_non_authorizing(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        before_events = store.list_events("valley")
        request = build_governance_request(proposal)

        assert request["request_schema"] == "world-governance-request-v0.1"
        assert request["proposal_id"] == proposal["proposal_id"]
        assert request["world_id"] == "valley"
        assert request["expected_revision"] == 1
        assert request["proposal_fingerprint"] == proposal_fingerprint(proposal)
        assert request["request_status"] == "PENDING_EXTERNAL_EVALUATION"
        assert request["authorization_status"] == "NOT_EVALUATED"
        assert request["execution_status"] == "NOT_EXECUTED"
        assert request["execution_permitted"] is False
        assert request["mutates_world"] is False
        assert request["grants_authority"] is False
        assert set(request["requested_review_areas"]) == set(REQUESTED_REVIEW_AREAS)
        assert store.list_events("valley") == before_events


def test_request_contains_proposal_snapshot_not_mutable_alias(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        request = build_governance_request(proposal)
        request["proposal"]["proposed_state_change"][0]["attributes"]["grain"] = -100
        assert proposal["proposed_state_change"][0]["attributes"]["grain"] == 75


def test_missing_fingerprint_field_is_rejected():
    with pytest.raises(ValidationError, match="missing fingerprint fields"):
        build_governance_request({"proposal_id": "p"})


@pytest.mark.parametrize("field,value", [
    ("proposal_id", ""),
    ("world_id", ""),
    ("expected_revision", True),
    ("expected_revision", -1),
])
def test_invalid_request_binding_is_rejected(tmp_path, field, value):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        invalid = copy.deepcopy(proposal)
        invalid[field] = value
        with pytest.raises(ValidationError):
            build_governance_request(invalid)


def test_request_fingerprint_recomputes_from_embedded_proposal_snapshot(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        request = build_governance_request(proposal)

        assert proposal_fingerprint(request["proposal"]) == request["proposal_fingerprint"]
        assert request["proposal"]["world_id"] == request["world_id"]
        assert request["proposal"]["expected_revision"] == request["expected_revision"]


def test_tampering_with_embedded_proposal_breaks_fingerprint_binding(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        request = build_governance_request(_proposal(store))
        original_fingerprint = request["proposal_fingerprint"]

        request["proposal"]["proposed_state_change"][0]["attributes"]["grain"] = 999

        assert proposal_fingerprint(request["proposal"]) != original_fingerprint
        assert request["execution_permitted"] is False
        assert request["mutates_world"] is False
        assert request["grants_authority"] is False


@pytest.mark.parametrize(
    "self_asserted_field,value",
    [
        ("authorization_status", "AUTHORIZED"),
        ("execution_status", "EXECUTED"),
        ("execution_permitted", True),
        ("mutates_world", True),
        ("grants_authority", True),
        ("verified", True),
    ],
)
def test_caller_status_metadata_is_not_copied_or_treated_as_authority(
    tmp_path, self_asserted_field, value
):
    """Proposal-side status claims cannot contaminate the external request."""
    with WorldStore(tmp_path / "world.sqlite3") as store:
        proposal = _proposal(store)
        original_fingerprint = proposal_fingerprint(proposal)
        proposal[self_asserted_field] = value

        request = build_governance_request(proposal)

        assert request["proposal_fingerprint"] == original_fingerprint
        assert self_asserted_field not in request["proposal"]
        assert request["authorization_status"] == "NOT_EVALUATED"
        assert request["execution_status"] == "NOT_EXECUTED"
        assert request["execution_permitted"] is False
        assert request["mutates_world"] is False
        assert request["grants_authority"] is False

