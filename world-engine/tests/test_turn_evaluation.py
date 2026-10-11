from __future__ import annotations

from engine.epistemic import observe_committed_world
from engine.store import WorldStore
from engine.turn_evaluation import build_turn_evaluation_report
from engine.valley import seed_valley


def _setup_prediction(store: WorldStore, expected: int = 82):
    return store.record_prediction(
        "valley",
        subject="north",
        predicate="grain",
        expected_value=expected,
        basis_revision=1,
        evaluate_after_revision=2,
        source="planner-model",
        source_ref="prediction:north-grain-turn",
    )


def _advance_and_observe(store: WorldStore, grain: int = 82):
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {
            "population": 100, "grain": grain, "unmet_food_last_turn": 0
        }}],
        actor="fixture", intent="apply deterministic outcome",
    )
    observe_committed_world(store)


def test_report_joins_prediction_evaluation_evidence_and_revision_deltas(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _setup_prediction(store)
    _advance_and_observe(store)
    evaluation = store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="snapshot:valley:revision-2",
    )
    before_world = store.get_world("valley")
    before_events = store.list_events("valley")
    before_claims = store.list_claims("valley")
    before_predictions = store.list_predictions("valley")
    before_evaluations = store.list_prediction_evaluations(prediction["prediction_id"])

    report = build_turn_evaluation_report(
        store, baseline_revision=1, outcome_revision=2
    )

    assert report["prediction_count"] == 1
    assert report["evaluation_counts"]["CONFIRMED"] == 1
    assert report["empirical_confirmation_rate"] == 1.0
    row = report["predictions"][0]
    assert row["prediction_id"] == prediction["prediction_id"]
    assert row["evaluation_id"] == evaluation["evaluation_id"]
    assert row["evidence_ref"] == "snapshot:valley:revision-2"
    assert any(
        claim["claim_id"] for claim in row["relevant_claims"]
        if claim["epistemic_status"] == "OBSERVED"
    )
    assert report["revision_comparison"]["revision_distance"] == 1
    assert report["causal_conclusion"] is False
    assert report["mutates_world"] is False
    assert report["mutates_model"] is False
    assert report["performs_evaluation"] is False
    assert store.get_world("valley") == before_world
    assert store.list_events("valley") == before_events
    assert store.list_claims("valley") == before_claims
    assert store.list_predictions("valley") == before_predictions
    assert store.list_prediction_evaluations(prediction["prediction_id"]) == before_evaluations
    store.close()


def test_report_marks_missing_evaluation_without_evaluating_it(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _setup_prediction(store)
    _advance_and_observe(store)

    report = build_turn_evaluation_report(
        store, baseline_revision=1, outcome_revision=2
    )

    assert report["evaluation_counts"]["NOT_EVALUATED"] == 1
    assert report["predictions"][0]["evaluation_status"] == "NOT_EVALUATED"
    assert report["predictions"][0]["evaluation_id"] is None
    assert store.list_prediction_evaluations(prediction["prediction_id"]) == []
    store.close()


def test_report_does_not_count_indeterminate_as_resolved_accuracy(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    prediction = _setup_prediction(store)
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="advance without observation",
    )
    store.evaluate_prediction(
        prediction["prediction_id"], evaluated_revision=2,
        evidence_ref="no-observation",
    )

    report = build_turn_evaluation_report(
        store, baseline_revision=1, outcome_revision=2
    )

    assert report["evaluation_counts"]["INDETERMINATE"] == 1
    assert report["resolved_evaluation_count"] == 0
    assert report["empirical_confirmation_rate"] is None
    store.close()


def test_report_excludes_predictions_from_other_baselines(tmp_path):
    store = WorldStore(tmp_path / "world.sqlite3")
    seed_valley(store)
    store.record_prediction(
        "valley", subject="north", predicate="grain", expected_value=82,
        basis_revision=1, evaluate_after_revision=2,
        source="planner", source_ref="prediction:one",
    )
    store.apply_transition(
        "valley", 1,
        [{"op": "update", "entity_id": "north", "attributes": {"grain": 82}}],
        actor="fixture", intent="advance revision",
    )
    store.record_prediction(
        "valley", subject="north", predicate="grain", expected_value=83,
        basis_revision=2, evaluate_after_revision=3,
        source="planner", source_ref="prediction:two",
    )

    report = build_turn_evaluation_report(
        store, baseline_revision=1, outcome_revision=2
    )

    assert report["prediction_count"] == 1
    assert report["predictions"][0]["expected_value"] == 82
    store.close()
