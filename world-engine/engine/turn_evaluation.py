"""Read-only report joining preregistered predictions to observed outcomes.

The report is descriptive bookkeeping. It neither evaluates predictions nor
infers causation, grants authority, or changes world/model state.
"""
from __future__ import annotations

from typing import Any

from .epistemic import read_epistemic_model
from .outcomes import compare_world_revisions
from .store import ValidationError, WorldStore


def build_turn_evaluation_report(
    store: WorldStore,
    *,
    baseline_revision: int,
    outcome_revision: int,
    world_id: str = "valley",
) -> dict[str, Any]:
    """Join predictions, recorded evaluations, relevant evidence, and state deltas.

    Predictions are included when registered against the exact baseline
    revision. An evaluation is attached only when it was explicitly recorded
    for the exact requested outcome revision. Missing evaluations remain
    NOT_EVALUATED; this function never evaluates a prediction on the caller's
    behalf.
    """
    comparison = compare_world_revisions(
        store,
        world_id=world_id,
        baseline_revision=baseline_revision,
        outcome_revision=outcome_revision,
    )
    world = store.get_world(world_id)
    if outcome_revision > world["revision"]:
        # compare_world_revisions normally raises first; retain a local contract
        # guard if that implementation changes.
        raise ValidationError("outcome_revision exceeds current world revision")

    claims = read_epistemic_model(
        store, world_id=world_id, world_revision=outcome_revision
    )["claims"]
    predictions = [
        prediction
        for prediction in store.list_predictions(world_id)
        if prediction["basis_revision"] == baseline_revision
        and prediction["evaluate_after_revision"] <= outcome_revision
    ]

    rows: list[dict[str, Any]] = []
    counts = {
        "CONFIRMED": 0,
        "REFUTED": 0,
        "INDETERMINATE": 0,
        "NOT_EVALUATED": 0,
    }
    for prediction in predictions:
        evaluations = [
            item
            for item in store.list_prediction_evaluations(prediction["prediction_id"])
            if item["evaluated_revision"] == outcome_revision
        ]
        evaluation = evaluations[0] if evaluations else None
        status = evaluation["outcome"] if evaluation else "NOT_EVALUATED"
        counts[status] += 1
        relevant_claims = [
            {
                "claim_id": claim["claim_id"],
                "subject": claim["subject"],
                "predicate": claim["predicate"],
                "value": claim["value"],
                "epistemic_status": claim["epistemic_status"],
                "effective_status": claim["effective_status"],
                "source": claim["source"],
                "source_ref": claim["source_ref"],
                "world_revision": claim["world_revision"],
            }
            for claim in claims
            if claim["subject"] == prediction["subject"]
            and claim["predicate"] == prediction["predicate"]
        ]
        rows.append({
            "prediction_id": prediction["prediction_id"],
            "subject": prediction["subject"],
            "predicate": prediction["predicate"],
            "expected_value": prediction["expected_value"],
            "basis_revision": prediction["basis_revision"],
            "evaluate_after_revision": prediction["evaluate_after_revision"],
            "prediction_source": prediction["source"],
            "prediction_source_ref": prediction["source_ref"],
            "evaluation_status": status,
            "evaluation_id": evaluation["evaluation_id"] if evaluation else None,
            "observed_value": evaluation["observed_value"] if evaluation else None,
            "evidence_ref": evaluation["evidence_ref"] if evaluation else None,
            "relevant_claims": relevant_claims,
        })

    evaluated = counts["CONFIRMED"] + counts["REFUTED"]
    return {
        "world_id": world_id,
        "baseline_revision": baseline_revision,
        "outcome_revision": outcome_revision,
        "revision_distance": outcome_revision - baseline_revision,
        "predictions": rows,
        "prediction_count": len(rows),
        "evaluation_counts": counts,
        "resolved_evaluation_count": evaluated,
        "empirical_confirmation_rate": (
            counts["CONFIRMED"] / evaluated if evaluated else None
        ),
        "revision_comparison": comparison,
        "causal_conclusion": False,
        "interpretation": (
            "Prediction outcomes and revision differences are descriptive. "
            "They do not establish that a particular action caused the outcome."
        ),
        "mutates_world": False,
        "mutates_model": False,
        "performs_evaluation": False,
    }
