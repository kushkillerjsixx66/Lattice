from __future__ import annotations

import pytest

from engine.store import RevisionConflict, ValidationError, WorldStore
from engine.transition_proposal import build_transition_proposal
from engine.valley import seed_valley


def _proposal(store, **overrides):
    args = {
        "world_id": "valley",
        "expected_revision": 1,
        "actor": "planner-agent",
        "intent": "transfer five grain units from north to south",
        "changes": [{
            "op": "update",
            "entity_id": "north",
            "attributes": {"grain": 77},
        }],
        "authority_reference": "authority-record:example-17",
        "constraints": ["trade-route-capacity<=10", "source-stock>=5"],
        "evidence": ["world-snapshot:valley:revision-1"],
        "effect_description": "Reduce north grain stock by five units",
        "reversibility": "CONDITIONALLY_REVERSIBLE",
        "recovery_plan": "Restore north grain only if no dependent transition has occurred",
        "lineage_reference": "planner-run:turn-1",
    }
    args.update(overrides)
    return build_transition_proposal(store, **args)


def test_proposal_envelope_is_exact_and_non_authorizing(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    before_world = store.get_world("valley")
    before_entities = store.list_entities("valley")
    before_events = store.list_events("valley")

    proposal = _proposal(store)

    assert proposal["proposal_schema"] == "world-transition-proposal-v0.1"
    assert proposal["expected_revision"] == 1
    assert proposal["proposed_state_change"][0]["entity_id"] == "north"
    assert proposal["authority_reference"] == "authority-record:example-17"
    assert proposal["authorization_status"] == "NOT_EVALUATED"
    assert proposal["execution_status"] == "NOT_EXECUTED"
    assert proposal["mutates_world"] is False
    assert proposal["grants_authority"] is False
    assert store.get_world("valley") == before_world
    assert store.list_entities("valley") == before_entities
    assert store.list_events("valley") == before_events
    store.close()


def test_stale_proposal_is_rejected(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    store.advance_world_time("valley", 1, 1, actor="clock", intent="advance time")

    with pytest.raises(RevisionConflict):
        _proposal(store)
    store.close()


@pytest.mark.parametrize("override", [
    {"authority_reference": ""},
    {"constraints": []},
    {"evidence": []},
    {"changes": []},
    {"reversibility": "MAGIC"},
    {"reversibility": "REVERSIBLE", "recovery_plan": None},
    {"expected_revision": True},
])
def test_incomplete_or_invalid_proposal_is_rejected(tmp_path, override):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(ValidationError):
        _proposal(store, **override)
    store.close()


def test_authority_reference_is_not_authorization(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    proposal = _proposal(store, authority_reference="signed-looking-but-unverified")
    assert proposal["authorization_status"] == "NOT_EVALUATED"
    assert proposal["execution_status"] == "NOT_EXECUTED"
    store.close()
