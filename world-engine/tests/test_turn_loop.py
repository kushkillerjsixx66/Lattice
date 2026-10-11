from __future__ import annotations

import pytest

from engine.store import ValidationError, WorldStore
from engine.turn_loop import preview_valley_turn
from engine.valley import seed_valley


def test_preview_valley_turn_composes_food_and_time_without_mutation(tmp_path):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        before_world = store.get_world("valley")
        before_entities = store.list_entities("valley")
        before_events = store.list_events("valley")

        first = preview_valley_turn(store)
        second = preview_valley_turn(store)

        assert first == second
        assert first["expected_revision"] == 1
        assert first["world_time_before"] == 0
        assert first["time_steps"] == 1
        assert first["world_time_after"] == 1
        assert first["settlements"][0]["grain_end"] == 82
        assert first["settlements"][1]["grain_end"] == 64
        assert first["authorization_status"] == "NOT_EVALUATED"
        assert first["execution_status"] == "NOT_EXECUTED"
        assert first["mutates_world"] is False
        assert first["grants_authority"] is False
        assert store.get_world("valley") == before_world
        assert store.list_entities("valley") == before_entities
        assert store.list_events("valley") == before_events


@pytest.mark.parametrize("steps", [0, -1, 2, True, 1.5, "1", None])
def test_preview_valley_turn_rejects_invalid_time_steps(tmp_path, steps):
    with WorldStore(tmp_path / "world.sqlite3") as store:
        seed_valley(store)
        with pytest.raises(ValidationError, match="exactly one step"):
            preview_valley_turn(store, steps=steps)
        assert store.get_world("valley")["revision"] == 1
        assert store.get_world("valley")["world_time"] == 0
