# Lattice World Engine

A persistent hybrid world-building simulation designed as an experimental environment for AI world modeling, causal exploration, scenario planning, and governed state transitions.

## Status

**Prototype implementation in progress.** The SQLite state store and deterministic Valley scenario rules are implemented with tests. Valley initialization creates the world, initial entities, and seed-event lineage in one transaction, preventing failed initialization from leaving a partial world; this is storage integrity, not authorization. A read-only full-turn preview now composes food/water outcomes with the proposed simulation-time advance, pinned to one expected revision; it does not execute or authorize the turn. The SQLite-backed epistemic claim ledger records source-scoped claims and derives revision-scoped conflicts without adjudicating them. The prediction ledger registers immutable expectations against the current world revision and evaluates them later against unambiguous observed claims. A read-only revision comparison reconstructs committed entity state from event history and reports descriptive differences without claiming causation. A read-only turn-evaluation report joins preregistered predictions, explicit evaluations, relevant revision-scoped claims, and state differences without evaluating predictions or inferring causation. A validated transition-proposal envelope binds a proposed change to an expected revision, actor, intent, authority reference, constraints, evidence, effect, reversibility, recovery plan, and lineage. A governance-receipt validator checks proposal binding but leaves authenticity and policy evaluation unresolved. A read-only governance-request contract packages a proposal and its fingerprint for external review; it does not decide whether the proposal may execute. A receipt revalidation contract detects whether the proposal's expected revision has drifted, while leaving receipt authenticity, policy evaluation, and authorization unresolved. The store now has a revision-checked atomic turn-commit primitive that applies attribute updates, advances one step of simulation time, and appends one combined event in a single transaction. It is a low-level storage primitive only and is not wired to a runtime or MCP tool; authorization is not evaluated and execution is not enabled. The MCP server and execution gateway remain unimplemented. No deployment or autonomous execution is enabled.

## Core separation

1. **World engine:** sole authority for committed simulated-world state.
2. **AI world model:** a separate, evidence-backed and potentially incomplete representation of that state.
3. **Governance boundary:** evaluates authority, constraints, lineage, uncertainty, and reversibility before consequential transitions.
4. **Event history:** records proposals, decisions, committed transitions, observations, and recovery events.

MCP is the intended typed interface to these capabilities; it is not the source of truth and does not itself grant authority.

## Initial scenario: The Valley

The seeded scenario contains a river, two settlements, farmland, a forest, a trade route, and a governing institution. The deterministic Valley rules evaluate grain production and food demand, report unmet food demand, derive water access from an explicit river relationship, and preview bounded grain transfers over the seeded trade route. Simulation time advances only through an explicit revisioned store transition.

Run this from the repository root after setting PYTHONPATH=world-engine in your environment:

```python
from engine.store import WorldStore
from engine.valley import preview_grain_transfer, preview_turn, seed_valley
from engine.turn_loop import preview_valley_turn
from engine.epistemic import observe_committed_world, read_epistemic_model

with WorldStore("valley.sqlite3") as store:
    seed_valley(store)  # Explicit initialization; do not expose as an ungoverned tool.
    proposal = preview_turn(store)  # Pure preview; does not mutate world state.
    print(proposal)
    full_turn = preview_valley_turn(store)  # One turn only; preview, not execution.
    print(full_turn)
    trade = preview_grain_transfer(store, amount=5)  # Pure proposal; still not execution.
    print(trade)
    observe_committed_world(store)  # Records claims about simulated state, not external reality.
    model = read_epistemic_model(store)
    print(model["conflicted_count"])
```

The preview returns an expected revision and exact proposed entity updates. Applying those updates is a separate operation and must remain behind the applicable governance boundary. Previewing is not execution, because verbs should mean things.

## Validation

Run the world-engine suite:

```bash
python -m pytest world-engine/tests -q
```

Tests cover full-turn preview composition and invalid-step rejection, atomic turn commit and event-lineage replay, stale-revision rejection and rollback, invalid turn-shape rejection, atomic world initialization and rollback, persistent state, revision/event lineage, stale-write rejection, transaction rollback, append-only histories, explicit simulation-time advancement, Valley seeding, deterministic previews, food-shortage accounting, bounded non-mutating trade proposals, revision-scoped epistemic claims and conflict detection, preregistered prediction evaluation, read-only outcome comparisons, read-only turn-evaluation reports, non-authorizing transition proposal validation, governance receipt binding, read-only external governance request construction, and governance-receipt freshness checks that remain non-authorizing.

## Governance

This project is subordinate to applicable Lattice Canon. Project-level requirements in this directory are proposals, not canonical amendments. The state store, scenario rules, proposal-envelope builder, receipt validator, governance-request builder, and receipt revalidator are domain/integration primitives, not an authorization gateway. Proposal validation establishes structural completeness and revision freshness only. Receipt validation establishes proposal binding only; it does not authenticate the receipt, evaluate policy, or grant permission. A governance request is pending external evaluation, not approval. Receipt revalidation reports revision freshness only; even a FRESH result does not authenticate a receipt or permit execution, and a stale revision must not be reused. The Ed25519 signed-receipt verifier now checks exact payload binding, configured issuer/key trust, scope, validity, current world revision, and persistent replay state; it remains non-authorizing and is not wired to a production trust source or execution gateway. Its review categories are interface prompts, not definitions or replacements for canonical policy. Missing or unverified governance state must not be treated as approval. Changes to canonical governance remain outside this project's scope.

The proposed [External Governance Verifier Contract v0.1](specs/WE-SPEC-002-external-governance-verifier-contract-v0.1.md) defines fail-closed requirements for a future verifier without selecting a trust provider or enabling authorization or execution.

See [World Engine Specification v0.1](specs/WE-SPEC-001-world-engine-v0.1.md).
