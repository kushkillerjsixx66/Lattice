"""Deterministic, read-only rules for the initial Valley scenario.

Scenario seeding is an explicit initialization operation. Turn evaluation is
pure with respect to the store: it returns proposed entity updates and never
commits them. Authorization and execution remain outside this module.
"""
from __future__ import annotations

from math import ceil
from typing import Any

from .store import ValidationError, WorldStore

RULESET_ID = "valley-rules-v0.1"

SEED_ENTITIES: tuple[dict[str, Any], ...] = (
    {
        "entity_id": "river",
        "entity_type": "river",
        "attributes": {"water_units": 1000, "flow_state": "NORMAL"},
        "relationships": {},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "north",
        "entity_type": "settlement",
        "attributes": {"population": 100, "grain": 80, "unmet_food_last_turn": 0},
        "relationships": {"water_source": "river", "farm": "north-farm"},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "south",
        "entity_type": "settlement",
        "attributes": {"population": 80, "grain": 64, "unmet_food_last_turn": 0},
        "relationships": {"water_source": "river", "farm": "south-farm"},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "north-farm",
        "entity_type": "farmland",
        "attributes": {"grain_yield_per_turn": 12},
        "relationships": {"serves": "north"},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "south-farm",
        "entity_type": "farmland",
        "attributes": {"grain_yield_per_turn": 8},
        "relationships": {"serves": "south"},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "forest",
        "entity_type": "forest",
        "attributes": {"timber_units": 80},
        "relationships": {},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "north-south-trade",
        "entity_type": "trade_route",
        "attributes": {"capacity_per_turn": 10, "open": True},
        "relationships": {"origin": "north", "destination": "south"},
        "lifecycle_state": "ACTIVE",
    },
    {
        "entity_id": "valley-council",
        "entity_type": "governing_institution",
        "attributes": {"policy_status": "UNSPECIFIED"},
        "relationships": {"jurisdiction": ["north", "south"]},
        "lifecycle_state": "ACTIVE",
    },
)


def seed_valley(store: WorldStore, world_id: str = "valley") -> dict[str, Any]:
    """Create The Valley and its fixed initial entities exactly once.

    This is an explicit initialization helper, not an authorization gateway.
    Callers must not expose it as an ungoverned runtime mutation tool.
    """
    try:
        store.get_world(world_id)
    except ValidationError:
        pass
    else:
        raise ValidationError(f"world already exists: {world_id}")

    world = store.create_world("The Valley", world_id=world_id)
    store.apply_transition(
        world_id,
        world["revision"],
        [{"op": "create", **entity} for entity in SEED_ENTITIES],
        actor="scenario-seeder",
        intent="initialize deterministic Valley scenario v0.1",
        event_type="SCENARIO_SEEDED",
    )
    return store.get_world(world_id)


def preview_turn(store: WorldStore, world_id: str = "valley") -> dict[str, Any]:
    """Return deterministic next-turn updates without changing stored state.

    Rule: each 10 residents require one grain unit per turn, rounded up.
    Farms produce their configured yield. Available grain is consumed first;
    any deficit is reported as unmet food demand and grain cannot go negative.
    Water access is reported from the settlement's explicit river relationship.
    """
    world = store.get_world(world_id)
    entities = {entity["entity_id"]: entity for entity in store.list_entities(world_id)}

    required = {
        "river": "river",
        "north": "settlement",
        "south": "settlement",
        "north-farm": "farmland",
        "south-farm": "farmland",
    }
    for entity_id, expected_type in required.items():
        entity = entities.get(entity_id)
        if entity is None or entity["entity_type"] != expected_type:
            raise ValidationError(
                f"Valley rules require {entity_id!r} of type {expected_type!r}"
            )

    river_active = entities["river"]["lifecycle_state"] == "ACTIVE"
    updates: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []

    for settlement_id, farm_id in (("north", "north-farm"), ("south", "south-farm")):
        settlement = entities[settlement_id]
        farm = entities[farm_id]
        population = settlement["attributes"].get("population")
        grain = settlement["attributes"].get("grain")
        yield_units = farm["attributes"].get("grain_yield_per_turn")
        if not isinstance(population, int) or population < 0:
            raise ValidationError(f"{settlement_id} population must be a non-negative integer")
        if not isinstance(grain, int) or grain < 0:
            raise ValidationError(f"{settlement_id} grain must be a non-negative integer")
        if not isinstance(yield_units, int) or yield_units < 0:
            raise ValidationError(f"{farm_id} grain_yield_per_turn must be a non-negative integer")

        demand = ceil(population / 10)
        available = grain + yield_units
        consumed = min(available, demand)
        ending_grain = available - consumed
        unmet_food = demand - consumed
        water_access = (
            river_active
            and settlement["relationships"].get("water_source") == "river"
        )

        attributes = dict(settlement["attributes"])
        attributes["grain"] = ending_grain
        attributes["unmet_food_last_turn"] = unmet_food
        updates.append({
            "op": "update",
            "entity_id": settlement_id,
            "attributes": attributes,
        })
        reports.append({
            "settlement_id": settlement_id,
            "population": population,
            "grain_start": grain,
            "grain_produced": yield_units,
            "food_demand": demand,
            "food_consumed": consumed,
            "grain_end": ending_grain,
            "unmet_food": unmet_food,
            "water_access": water_access,
        })

    return {
        "world_id": world_id,
        "expected_revision": world["revision"],
        "ruleset_id": RULESET_ID,
        "mutates_world": False,
        "proposed_changes": updates,
        "settlements": reports,
    }
