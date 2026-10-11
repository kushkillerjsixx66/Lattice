from __future__ import annotations

import pytest

from engine.outcomes import compare_world_revisions
from engine.store import ValidationError, WorldStore
from engine.valley import seed_valley


def test_revision_comparison_reports_committed_differences_without_mutation(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    baseline_world = store.get_world("valley")
    baseline_events = store.list_events("valley")

    store.apply_transition(
        "valley", 1,
        [
            {"op": "update", "entity_id": "north", "attributes": {
                "population": 100, "grain": 82, "unmet_food_last_turn": 0
            }},
            {"op": "delete", "entity_id": "forest"},
            {"op": "create", "entity_id": "quarry", "entity_type": "resource_site",
             "attributes": {"stone_units": 20}, "relationships": {},
             "lifecycle_state": "ACTIVE"},
        ],
        actor="fixture", intent="apply a controlled outcome",
    )
    before_analysis_world = store.get_world("valley")
    before_analysis_events = store.list_events("valley")

    result = compare_world_revisions(
        store, world_id="valley", baseline_revision=1, outcome_revision=2
    )

    assert result["difference_count"] == 3
    assert result["causal_conclusion"] is False
    assert result["mutates_world"] is False
    changes = {item["entity_id"]: item for item in result["differences"]}
    assert changes["north"]["change_kind"] == "CHANGED"
    assert changes["north"]["before"]["attributes"]["grain"] == 80
    assert changes["north"]["after"]["attributes"]["grain"] == 82
    assert changes["forest"]["change_kind"] == "DELETED"
    assert changes["quarry"]["change_kind"] == "CREATED"
    assert store.get_world("valley") == before_analysis_world
    assert store.list_events("valley") == before_analysis_events
    assert baseline_world["revision"] == 1
    assert len(baseline_events) == 2
    store.close()


def test_same_revision_has_no_differences(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    result = compare_world_revisions(
        store, baseline_revision=1, outcome_revision=1
    )
    assert result["differences"] == []
    assert result["difference_count"] == 0
    assert result["revision_distance"] == 0
    store.close()


@pytest.mark.parametrize(
    "baseline,outcome",
    [(-1, 1), (1, -1), (2, 1), (1, 99)],
)
def test_invalid_revision_ranges_are_rejected(tmp_path, baseline, outcome):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(ValidationError):
        compare_world_revisions(
            store, baseline_revision=baseline, outcome_revision=outcome
        )
    store.close()


def test_revision_comparison_rejects_boolean_revisions(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(ValidationError):
        compare_world_revisions(
            store, baseline_revision=True, outcome_revision=1
        )
    store.close()
