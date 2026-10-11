from __future__ import annotations

import pytest

from engine.store import RevisionConflict, ValidationError, WorldStore
from engine.turn_loop import preview_valley_turn
from engine.valley import RULESET_ID, seed_valley


def test_committed_turn_updates_resources_and_time_in_one_revision(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        proposal = preview_valley_turn(store)
        before_events = store.list_events("valley")

        result = store.commit_turn_transition(
            "valley",
            proposal["expected_revision"],
            proposal["proposed_changes"],
            actor="test-governed-caller",
            intent="commit reviewed Valley turn fixture",
            ruleset_id=proposal["ruleset_id"],
        )

        world = store.get_world("valley")
        assert world["revision"] == 2
        assert world["world_time"] == 1
        assert store.get_entity("valley", "north")["attributes"]["grain"] == 82
        assert store.get_entity("valley", "south")["attributes"]["grain"] == 64

        events = store.list_events("valley")
        assert len(events) == len(before_events) + 1
        event = events[-1]
        assert event["event_id"] == result["event_id"]
        assert event["event_type"] == "VALLEY_TURN_COMMITTED"
        assert event["pre_revision"] == 1
        assert event["post_revision"] == 2
        assert event["payload"]["ruleset_id"] == RULESET_ID
        assert event["payload"]["steps"] == 1
        assert event["payload"]["pre_world_time"] == 0
        assert event["payload"]["post_world_time"] == 1
        assert len(event["payload"]["changes"]) == 2
        assert result["authorization_evaluated"] is False
        assert result["execution_authorized"] is False


def test_committed_turn_rolls_back_entity_updates_if_any_update_fails(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        before_world = store.get_world("valley")
        before_entities = store.list_entities("valley")
        before_events = store.list_events("valley")

        with pytest.raises(ValidationError, match="missing entity"):
            store.commit_turn_transition(
                "valley",
                expected_revision=1,
                changes=[
                    {"op": "update", "entity_id": "north", "attributes": {
                        "population": 100, "grain": 999, "unmet_food_last_turn": 0
                    }},
                    {"op": "update", "entity_id": "missing", "attributes": {"value": 1}},
                ],
                actor="test-caller",
                intent="exercise transaction rollback",
                ruleset_id=RULESET_ID,
            )

        assert store.get_world("valley") == before_world
        assert store.list_entities("valley") == before_entities
        assert store.list_events("valley") == before_events


def test_committed_turn_rejects_stale_revision_without_mutation(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        proposal = preview_valley_turn(store)
        store.advance_world_time(
            "valley", 1, 1, actor="fixture", intent="force revision drift"
        )
        before_world = store.get_world("valley")
        before_entities = store.list_entities("valley")
        before_events = store.list_events("valley")

        with pytest.raises(RevisionConflict):
            store.commit_turn_transition(
                "valley",
                proposal["expected_revision"],
                proposal["proposed_changes"],
                actor="test-caller",
                intent="attempt stale turn",
                ruleset_id=RULESET_ID,
            )

        assert store.get_world("valley") == before_world
        assert store.list_entities("valley") == before_entities
        assert store.list_events("valley") == before_events


@pytest.mark.parametrize("steps", [0, -1, 2, True, 1.5, "1", None])
def test_committed_turn_rejects_invalid_step_count(tmp_path, steps):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        proposal = preview_valley_turn(store)
        with pytest.raises(ValidationError, match="exactly one step"):
            store.commit_turn_transition(
                "valley",
                proposal["expected_revision"],
                proposal["proposed_changes"],
                actor="test-caller",
                intent="invalid step fixture",
                ruleset_id=RULESET_ID,
                steps=steps,
            )
        assert store.get_world("valley")["revision"] == 1
        assert store.get_world("valley")["world_time"] == 0
        assert len(store.list_events("valley")) == 2


def test_committed_turn_rejects_non_update_duplicate_and_non_attribute_changes(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        invalid_changes = [
            [{"op": "delete", "entity_id": "north"}],
            [
                {"op": "update", "entity_id": "north", "attributes": {"grain": 1}},
                {"op": "update", "entity_id": "north", "attributes": {"grain": 2}},
            ],
            [{"op": "update", "entity_id": "north", "attributes": {"grain": 1},
              "lifecycle_state": "INACTIVE"}],
        ]
        for changes in invalid_changes:
            with pytest.raises(ValidationError):
                store.commit_turn_transition(
                    "valley", 1, changes, actor="test-caller",
                    intent="invalid turn shape fixture", ruleset_id=RULESET_ID,
                )
            assert store.get_world("valley")["revision"] == 1
            assert store.get_world("valley")["world_time"] == 0
            assert len(store.list_events("valley")) == 2
