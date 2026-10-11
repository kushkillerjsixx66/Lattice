"""Compose deterministic Valley rules into one revision-bound turn proposal.

This module deliberately previews a whole turn without committing it. Atomic
execution and authorization remain separate concerns; a preview is not consent.
"""
from __future__ import annotations

from typing import Any

from .store import ValidationError, WorldStore
from .valley import RULESET_ID, preview_turn


def preview_valley_turn(
    store: WorldStore, *, steps: int = 1, world_id: str = "valley"
) -> dict[str, Any]:
    """Return a complete, deterministic turn proposal without mutating state.

    The proposal combines the existing food/water simulation with an explicit
    simulation-time advance. It captures the current revision and world time so
    callers can detect drift before any separately governed execution.
    """
    if not isinstance(steps, int) or isinstance(steps, bool) or steps != 1:
        raise ValidationError("turn preview currently supports exactly one step")

    world = store.get_world(world_id)
    food = preview_turn(store, world_id)
    if food["expected_revision"] != world["revision"]:
        # Defensive consistency check if a concurrent writer changed state
        # between the reads. Never package a mixed-revision proposal.
        raise ValidationError("world changed while building turn preview")

    return {
        "world_id": world_id,
        "expected_revision": world["revision"],
        "world_time_before": world["world_time"],
        "time_steps": steps,
        "world_time_after": world["world_time"] + steps,
        "ruleset_id": RULESET_ID,
        "event_type": "VALLEY_TURN",
        "proposed_changes": food["proposed_changes"],
        "settlements": food["settlements"],
        "authorization_status": "NOT_EVALUATED",
        "execution_status": "NOT_EXECUTED",
        "mutates_world": False,
        "grants_authority": False,
    }
