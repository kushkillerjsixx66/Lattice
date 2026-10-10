# Lattice World Engine

A persistent hybrid world-building simulation designed as an experimental environment for AI world modeling, causal exploration, scenario planning, and governed state transitions.

## Status

**Prototype implementation in progress.** The SQLite state store and deterministic Valley scenario rules are implemented with tests. The MCP server, separate epistemic model, prediction ledger, and governance gateway are not implemented by this increment. No deployment or autonomous execution is enabled.

## Core separation

1. **World engine:** sole authority for committed simulated-world state.
2. **AI world model:** a separate, evidence-backed and potentially incomplete representation of that state.
3. **Governance boundary:** evaluates authority, constraints, lineage, uncertainty, and reversibility before consequential transitions.
4. **Event history:** records proposals, decisions, committed transitions, observations, and recovery events.

MCP is the intended typed interface to these capabilities; it is not the source of truth and does not itself grant authority.

## Initial scenario: The Valley

The seeded scenario contains a river, two settlements, farmland, a forest, a trade route, and a governing institution. The first deterministic rule evaluates per-turn grain production and food demand, reports unmet food demand, and derives water access from an explicit river relationship.

From the repository root, set PYTHONPATH so Python can import the package inside the hyphenated project directory:

```bash
export PYTHONPATH=world-engine
python
from engine.store import WorldStore
from engine.valley import preview_turn, seed_valley

with WorldStore("valley.sqlite3") as store:
    seed_valley(store)  # Explicit initialization; do not expose as an ungoverned tool.
    proposal = preview_turn(store)  # Pure preview; does not mutate world state.
    print(proposal)
```

The preview returns an expected revision and exact proposed entity updates. Applying those updates is a separate operation and must remain behind the applicable governance boundary. Previewing is not execution, because verbs should mean things.

## Validation

Run the world-engine suite:

```bash
python -m pytest world-engine/tests -q
```

Tests cover persistent state, revision/event lineage, stale-write rejection, transaction rollback, append-only history, Valley seeding, deterministic previews, and food-shortage accounting.

## Governance

This project is subordinate to applicable Lattice Canon. Project-level requirements in this directory are proposals, not canonical amendments. The state store and scenario rules are domain primitives, not an authorization gateway. Changes to canonical governance remain outside this project's scope.

See [World Engine Specification v0.1](specs/WE-SPEC-001-world-engine-v0.1.md).
