from __future__ import annotations

import sqlite3

import pytest

from engine.epistemic import observe_committed_world
from engine.store import RevisionConflict, ValidationError, WorldStore
from engine.valley import seed_valley


def _register(store: WorldStore, expected: int = 82):
    return store.record_prediction(
        "valley",
        subject="north",
        predicate="grain",
        expected_value=expected,
        basis_revision=1,
        evaluate_after_revision=2,
        source="planner-model",
        source_ref="prediction:next-turn-grain",
    )


def test_prediction_is_preregistered_and_evaluated_against_later_observation(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _register(store)
    assert prediction["basis_revision"] == 1
    assert store.get_world("valley")["revision"] == 1

    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="apply deterministic grain outcome",
    )
    snapshot = observe_committed_world(store)
    assert snapshot["world_revision"] == 2

    result = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="snapshot:world-revision-2",
    )
    assert result["outcome"] == "CONFIRMED"
    assert result["observed_value"] == 82
    assert store.list_predictions("valley")[0]["expected_value"] == 82
    assert store.list_prediction_evaluations(prediction["prediction_id"])[0]["outcome"] == "CONFIRMED"
    store.close()


def test_prediction_can_be_refuted_without_rewriting_registration(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _register(store, expected=999)
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="apply deterministic grain outcome",
    )
    observe_committed_world(store)

    result = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="snapshot:world-revision-2",
    )
    assert result["outcome"] == "REFUTED"
    assert store.list_predictions("valley")[0]["expected_value"] == 999
    store.close()


def test_prediction_is_indeterminate_without_unambiguous_observed_evidence(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _register(store)
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="advance world revision without recording observations",
    )

    result = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="no-observation",
    )
    assert result["outcome"] == "INDETERMINATE"
    assert result["observed_value"] is None
    store.close()


def test_conflicting_observations_make_prediction_indeterminate(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _register(store)
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="advance to outcome revision",
    )
    observe_committed_world(store)
    store.record_claim(
        "valley", subject="north", predicate="grain", value=81,
        epistemic_status="OBSERVED", source="independent-observer",
        source_ref="observer:conflicting", world_revision=2,
    )

    result = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="observations:revision-2",
    )
    assert result["outcome"] == "INDETERMINATE"
    assert result["observed_value"] is None
    store.close()


@pytest.mark.parametrize(
    "basis,target",
    [(2, 2), (2, 1), (1, 1)],
)
def test_prediction_requires_strictly_later_evaluation_revision(tmp_path, basis, target):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(ValidationError):
        store.record_prediction(
            "valley", subject="north", predicate="grain", expected_value=82,
            basis_revision=basis, evaluate_after_revision=target,
            source="model", source_ref="prediction:invalid",
        )
    store.close()


def test_prediction_basis_must_match_current_revision(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    with pytest.raises(RevisionConflict):
        store.record_prediction(
            "valley", subject="north", predicate="grain", expected_value=82,
            basis_revision=0, evaluate_after_revision=2,
            source="model", source_ref="prediction:stale",
        )
    store.close()


def test_prediction_and_evaluation_histories_are_append_only(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _register(store)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._connection.execute(
            "DELETE FROM predictions WHERE prediction_id = ?",
            (prediction["prediction_id"],),
        )
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="advance revision",
    )
    observe_committed_world(store)
    evaluation = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="snapshot:revision-2",
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._connection.execute(
            "DELETE FROM prediction_evaluations WHERE evaluation_id = ?",
            (evaluation["evaluation_id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.evaluate_prediction(
            prediction["prediction_id"], evaluated_revision=2,
            evidence_ref="duplicate-evaluation",
        )
    store.close()
