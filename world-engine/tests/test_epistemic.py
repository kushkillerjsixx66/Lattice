from __future__ import annotations

import sqlite3

import pytest

from engine.epistemic import observe_committed_world, read_epistemic_model, record_model_claim
from engine.store import ValidationError, WorldStore
from engine.valley import seed_valley


def test_observation_snapshot_is_revision_scoped_and_does_not_mutate_world(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    before_world = store.get_world("valley")
    before_entities = store.list_entities("valley")
    before_events = store.list_events("valley")

    result = observe_committed_world(store)

    assert result["world_revision"] == 1
    assert result["claim_count"] > 0
    assert all(c["epistemic_status"] == "OBSERVED" for c in result["claims"])
    assert all(c["source"] == "world-engine-committed-state" for c in result["claims"])
    assert store.get_world("valley") == before_world
    assert store.list_entities("valley") == before_entities
    assert store.list_events("valley") == before_events
    assert len(store.list_claims("valley", 1)) == result["claim_count"]
    store.close()


def test_conflicting_assertions_are_preserved_and_derived_not_adjudicated(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    common = {
        "world_id": "valley",
        "subject": "north",
        "predicate": "grain",
        "world_revision": 1,
    }
    first = record_model_claim(
        store, **common, value=80, epistemic_status="OBSERVED",
        source="world-engine", source_ref="entity:north@revision:1",
    )
    second = record_model_claim(
        store, **common, value=30, epistemic_status="HYPOTHESIS",
        source="planner-model", source_ref="hypothesis:grain-estimate-1",
    )

    claims = store.list_claims("valley", 1)
    pair = [c for c in claims if c["subject"] == "north" and c["predicate"] == "grain"]
    assert len(pair) == 2
    assert {c["claim_id"] for c in pair} == {first["claim_id"], second["claim_id"]}
    assert {c["effective_status"] for c in pair} == {"CONFLICTED"}
    assert {c["epistemic_status"] for c in pair} == {"OBSERVED", "HYPOTHESIS"}
    assert {c["value"] for c in pair} == {80, 30}
    store.close()


def test_conflict_scope_does_not_mix_different_world_revisions(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    record_model_claim(
        store, "valley", subject="north", predicate="grain", value=80,
        epistemic_status="OBSERVED", source="world-engine",
        source_ref="entity:north@revision:1", world_revision=1,
    )
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 70}}],
        actor="fixture", intent="advance grain state",
    )
    record_model_claim(
        store, "valley", subject="north", predicate="grain", value=70,
        epistemic_status="OBSERVED", source="world-engine",
        source_ref="entity:north@revision:2", world_revision=2,
    )
    assert store.list_claims("valley", 1)[0]["effective_status"] == "OBSERVED"
    assert store.list_claims("valley", 2)[0]["effective_status"] == "OBSERVED"
    store.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"epistemic_status": "CONFLICTED", "value": 1},
        {"epistemic_status": "UNKNOWN", "value": "unknown"},
        {"epistemic_status": "HYPOTHESIS", "value": None},
        {"epistemic_status": "OBSERVED", "value": 1, "source": ""},
        {"epistemic_status": "INFERRED", "value": 1, "source_ref": ""},
        {"epistemic_status": "OBSERVED", "value": 1, "world_revision": 999},
    ],
)
def test_invalid_claims_are_rejected(tmp_path, kwargs):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    args = {
        "subject": "north", "predicate": "grain", "value": 1,
        "epistemic_status": "OBSERVED", "source": "test",
        "source_ref": "test:1", "world_revision": 1,
    }
    args.update(kwargs)
    with pytest.raises(ValidationError):
        store.record_claim("valley", **args)
    assert store.list_claims("valley") == []
    store.close()


def test_unknown_claim_is_explicit_and_does_not_conflict_with_known_value(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    record_model_claim(
        store, "valley", subject="river", predicate="future_flood",
        value=None, epistemic_status="UNKNOWN", source="planner-model",
        source_ref="forecast:unavailable", world_revision=1,
    )
    record_model_claim(
        store, "valley", subject="river", predicate="future_flood",
        value=False, epistemic_status="HYPOTHESIS", source="planner-model",
        source_ref="forecast:baseline", world_revision=1,
    )
    pair = [c for c in store.list_claims("valley", 1) if c["predicate"] == "future_flood"]
    assert {c["effective_status"] for c in pair} == {"UNKNOWN", "HYPOTHESIS"}
    store.close()


def test_epistemic_claim_history_is_append_only_and_separate_from_events(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    claim = store.record_claim(
        "valley", subject="north", predicate="grain", value=80,
        epistemic_status="OBSERVED", source="test", source_ref="test:1",
        world_revision=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._connection.execute(
            "DELETE FROM epistemic_claims WHERE claim_id = ?", (claim["claim_id"],)
        )
    assert len(store.list_events("valley")) == 2
    assert len(store.list_claims("valley")) == 1
    store.close()


def test_read_model_is_non_mutating_and_reports_conflict_count(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    record_model_claim(
        store, "valley", subject="south", predicate="grain", value=64,
        epistemic_status="OBSERVED", source="world-engine",
        source_ref="entity:south@revision:1", world_revision=1,
    )
    record_model_claim(
        store, "valley", subject="south", predicate="grain", value=50,
        epistemic_status="INFERRED", source="model",
        source_ref="inference:1", world_revision=1,
    )
    before = store.get_world("valley")
    model = read_epistemic_model(store, "valley", 1)
    assert model["mutates_world"] is False
    assert model["conflicted_count"] == 2
    assert store.get_world("valley") == before
    store.close()
