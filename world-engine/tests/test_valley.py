from __future__ import annotations

import pytest

from engine.store import ValidationError, WorldStore
from engine.valley import RULESET_ID, preview_grain_transfer, preview_turn, seed_valley


def test_seed_valley_creates_expected_entities_and_lineage(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    world = seed_valley(store)

    assert world["world_id"] == "valley"
    assert world["revision"] == 1
    entities = {item["entity_id"]: item for item in store.list_entities("valley")}
    assert {
        "river", "north", "south", "north-farm", "south-farm",
        "forest", "north-south-trade", "valley-council",
    } == set(entities)
    events = store.list_events("valley")
    assert [event["event_type"] for event in events] == [
        "WORLD_CREATED", "SCENARIO_SEEDED"
    ]
    assert events[-1]["pre_revision"] == 0
    assert events[-1]["post_revision"] == 1
    store.close()


def test_seed_valley_refuses_to_overwrite_existing_world(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)

    with pytest.raises(ValidationError, match="already exists"):
        seed_valley(store)

    assert store.get_world("valley")["revision"] == 1
    assert len(store.list_events("valley")) == 2
    store.close()


def test_preview_turn_is_deterministic_and_does_not_mutate_world(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    before_world = store.get_world("valley")
    before_entities = store.list_entities("valley")
    before_events = store.list_events("valley")

    first = preview_turn(store)
    second = preview_turn(store)

    assert first == second
    assert first["ruleset_id"] == RULESET_ID
    assert first["expected_revision"] == 1
    assert first["mutates_world"] is False
    assert first["settlements"] == [
        {
            "settlement_id": "north",
            "population": 100,
            "grain_start": 80,
            "grain_produced": 12,
            "food_demand": 10,
            "food_consumed": 10,
            "grain_end": 82,
            "unmet_food": 0,
            "water_access": True,
        },
        {
            "settlement_id": "south",
            "population": 80,
            "grain_start": 64,
            "grain_produced": 8,
            "food_demand": 8,
            "food_consumed": 8,
            "grain_end": 64,
            "unmet_food": 0,
            "water_access": True,
        },
    ]
    assert store.get_world("valley") == before_world
    assert store.list_entities("valley") == before_entities
    assert store.list_events("valley") == before_events
    store.close()


def test_preview_reports_food_shortage_without_negative_grain(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    store.apply_transition(
        "valley",
        1,
        [{"op": "update", "entity_id": "north", "attributes": {
            "population": 300, "grain": 0, "unmet_food_last_turn": 0
        }}],
        actor="test-fixture",
        intent="set deterministic scarcity fixture",
    )

    preview = preview_turn(store)
    north = preview["settlements"][0]
    assert north["food_demand"] == 30
    assert north["food_consumed"] == 12
    assert north["grain_end"] == 0
    assert north["unmet_food"] == 18
    assert store.get_entity("valley", "north")["attributes"]["grain"] == 0
    assert store.get_world("valley")["revision"] == 2
    store.close()


def test_preview_requires_the_valley_domain_entities(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    store.create_world("Incomplete", world_id="incomplete")

    with pytest.raises(ValidationError, match="Valley rules require"):
        preview_turn(store, "incomplete")

    assert store.get_world("incomplete")["revision"] == 0
    assert len(store.list_events("incomplete")) == 1
    store.close()


def test_preview_grain_transfer_is_bounded_and_non_mutating(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    before_world = store.get_world("valley")
    before_entities = store.list_entities("valley")
    before_events = store.list_events("valley")

    proposal = preview_grain_transfer(store, amount=5)

    assert proposal["expected_revision"] == 1
    assert proposal["mutates_world"] is False
    assert proposal["transfer"] == {
        "resource": "grain", "amount": 5, "origin": "north", "destination": "south"
    }
    assert proposal["proposed_changes"][0]["attributes"]["grain"] == 75
    assert proposal["proposed_changes"][1]["attributes"]["grain"] == 69
    assert store.get_world("valley") == before_world
    assert store.list_entities("valley") == before_entities
    assert store.list_events("valley") == before_events
    store.close()


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, 11])
def test_preview_grain_transfer_rejects_invalid_or_over_capacity_amounts(tmp_path, amount):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(ValidationError):
        preview_grain_transfer(store, amount=amount)
    assert store.get_world("valley")["revision"] == 1
    assert len(store.list_events("valley")) == 2
    store.close()


def test_preview_grain_transfer_rejects_insufficient_origin_stock(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 2}}],
        actor="test-fixture", intent="reduce origin stock",
    )
    with pytest.raises(ValidationError, match="available grain"):
        preview_grain_transfer(store, amount=3)
    assert store.get_world("valley")["revision"] == 2
    store.close()
