from __future__ import annotations

import sqlite3

import pytest

from engine.store import RevisionConflict, ValidationError, WorldStore


def create_store(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    world = store.create_world("The Valley", world_id="valley")
    return store, world


def create_settlement(store, revision=0, entity_id="north"):
    return store.apply_transition(
        "valley",
        revision,
        [{"op": "create", "entity_id": entity_id, "entity_type": "settlement", "attributes": {"population": 100}, "relationships": {}, "lifecycle_state": "ACTIVE"}],
        actor="test-operator",
        intent="seed test settlement",
    )


def test_world_initialization_rolls_back_world_entities_and_events_atomically(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    entities = [
        {"op": "create", "entity_id": "north", "entity_type": "settlement",
         "attributes": {"population": 100}, "relationships": {},
         "lifecycle_state": "ACTIVE"},
        {"op": "create", "entity_id": "north", "entity_type": "settlement",
         "attributes": {"population": 200}, "relationships": {},
         "lifecycle_state": "ACTIVE"},
    ]

    with pytest.raises(ValidationError, match="entity already exists"):
        store.create_world_with_entities(
            "Atomic fixture", entities, world_id="atomic-fixture",
            actor="test-seeder", intent="test atomic initialization",
        )

    with pytest.raises(ValidationError, match="unknown world"):
        store.get_world("atomic-fixture")
    assert store._connection.execute(
        "SELECT COUNT(*) FROM events WHERE world_id = ?", ("atomic-fixture",)
    ).fetchone()[0] == 0
    assert store._connection.execute(
        "SELECT COUNT(*) FROM entities WHERE world_id = ?", ("atomic-fixture",)
    ).fetchone()[0] == 0
    store.close()


def test_world_state_persists_across_store_instances(tmp_path):
    store, _ = create_store(tmp_path)
    create_settlement(store)
    store.close()

    reopened = WorldStore(tmp_path / "world.sqlite3")
    assert reopened.get_world("valley")["revision"] == 1
    assert reopened.get_entity("valley", "north")["attributes"]["population"] == 100
    assert [event["post_revision"] for event in reopened.list_events("valley")] == [0, 1]
    reopened.close()


def test_successful_transition_increments_revision_and_appends_event(tmp_path):
    store, _ = create_store(tmp_path)
    result = create_settlement(store)

    assert result["pre_revision"] == 0
    assert result["post_revision"] == 1
    assert store.get_world("valley")["revision"] == 1
    events = store.list_events("valley")
    assert len(events) == 2
    assert events[-1]["event_id"] == result["event_id"]
    assert events[-1]["pre_revision"] == 0
    assert events[-1]["post_revision"] == 1
    assert events[-1]["outcome"] == "COMMITTED"
    store.close()


def test_stale_revision_is_rejected_without_mutation(tmp_path):
    store, _ = create_store(tmp_path)
    create_settlement(store)

    with pytest.raises(RevisionConflict):
        create_settlement(store, revision=0, entity_id="south")

    assert store.get_world("valley")["revision"] == 1
    assert store.get_entity("valley", "south") is None
    assert len(store.list_events("valley")) == 2
    store.close()


def test_invalid_second_change_rolls_back_first_change(tmp_path):
    store, _ = create_store(tmp_path)
    changes = [
        {"op": "create", "entity_id": "north", "entity_type": "settlement", "attributes": {"population": 100}},
        {"op": "update", "entity_id": "missing", "attributes": {"population": 200}},
    ]

    with pytest.raises(ValidationError, match="missing entity"):
        store.apply_transition("valley", 0, changes, actor="test", intent="test rollback")

    assert store.get_world("valley")["revision"] == 0
    assert store.get_entity("valley", "north") is None
    assert len(store.list_events("valley")) == 1
    store.close()


def test_duplicate_entity_creation_is_rejected_atomically(tmp_path):
    store, _ = create_store(tmp_path)
    create_settlement(store)

    with pytest.raises(ValidationError, match="already exists"):
        create_settlement(store, revision=1)

    assert store.get_world("valley")["revision"] == 1
    assert len(store.list_events("valley")) == 2
    store.close()


def test_empty_transition_is_rejected(tmp_path):
    store, _ = create_store(tmp_path)
    with pytest.raises(ValidationError, match="at least one change"):
        store.apply_transition("valley", 0, [], actor="test", intent="empty")
    assert store.get_world("valley")["revision"] == 0
    assert len(store.list_events("valley")) == 1
    store.close()


def test_event_history_rejects_update_and_delete(tmp_path):
    store, _ = create_store(tmp_path)
    event_id = store.list_events("valley")[0]["event_id"]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._connection.execute("UPDATE events SET outcome = 'REWRITTEN' WHERE event_id = ?", (event_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._connection.execute("DELETE FROM events WHERE event_id = ?", (event_id,))

    assert len(store.list_events("valley")) == 1
    store.close()


def test_advance_world_time_is_revisioned_and_appends_lineage(tmp_path):
    store, world = create_store(tmp_path)

    result = store.advance_world_time(
        "valley", world["revision"], 3, actor="test-operator", intent="advance test clock"
    )

    assert result["pre_world_time"] == 0
    assert result["post_world_time"] == 3
    assert result["pre_revision"] == 0
    assert result["post_revision"] == 1
    assert store.get_world("valley")["world_time"] == 3
    event = store.list_events("valley")[-1]
    assert event["event_type"] == "WORLD_TIME_ADVANCED"
    assert event["payload"] == {"steps": 3, "pre_world_time": 0, "post_world_time": 3}
    store.close()


def test_advance_world_time_rejects_invalid_or_stale_requests(tmp_path):
    store, _ = create_store(tmp_path)

    for steps in (0, -1, True, 1.5):
        with pytest.raises(ValidationError, match="steps"):
            store.advance_world_time(
                "valley", 0, steps, actor="test-operator", intent="invalid clock change"
            )

    store.advance_world_time("valley", 0, 1, actor="test-operator", intent="advance clock")
    with pytest.raises(RevisionConflict):
        store.advance_world_time("valley", 0, 1, actor="test-operator", intent="stale clock change")
    assert store.get_world("valley")["world_time"] == 1
    assert store.get_world("valley")["revision"] == 1
    assert len(store.list_events("valley")) == 2
    store.close()
