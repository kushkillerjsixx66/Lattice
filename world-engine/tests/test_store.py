from __future__ import annotations

import pytest

from world_engine.engine.store import RevisionConflict, ValidationError, WorldStore


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
