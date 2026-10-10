# WE-SPEC-001: Lattice World Engine

- **Version:** 0.1.0-draft
- **Status:** Proposed; not ratified
- **Scope:** Foundational design contract
- **Authority:** Subordinate to applicable Lattice Canon
- **Implementation status:** Not yet implemented or validated

## 1. Purpose

Define a persistent hybrid world simulation in which an AI can construct and revise a model of its environment, explore unknowns, predict outcomes, run controlled experiments, and propose state transitions that pass applicable governance requirements.

The system must preserve the distinction between:

1. **Authoritative world state:** committed facts maintained by the simulation engine.
2. **Epistemic model:** the AI's evidence-backed, potentially incomplete representation of the world.
3. **Governed transition:** an exact proposed change evaluated for authority, constraints, evidence, lineage, uncertainty, and reversibility.
4. **Audit evidence:** records of what was proposed, evaluated, executed, and observed.

## 2. Scope

### Included

- Physical geography and resources.
- Settlements, populations, institutions, economies, and trade.
- Abstract entities, typed relationships, dependencies, and causal hypotheses.
- Persistent state, event history, snapshots, and revisions.
- Explicit simulation time.
- AI claims, hypotheses, predictions, uncertainty, and discrepancy tracking.
- MCP tools for observation, modeling, simulation, proposal, authorized execution, and audit.
- Automated behavioral tests for state integrity and governance boundaries.

### Excluded from v0.1

- Unrestricted autonomous modification of the world.
- Direct AI writes to the authoritative database.
- Self-granted permissions or implicit authority inheritance.
- Changes to canonical Lattice governance.
- A full graphical game client.
- Claims of learning or intelligence improvement without measurement.

## 3. Architectural boundaries

### 3.1 World engine

The world engine is the sole authority for committed simulated-world state. It validates domain rules, maintains revision consistency, and commits accepted transitions transactionally.

### 3.2 AI world model

The model is stored separately from authoritative world state. It may be incomplete, uncertain, stale, or wrong. It must not gain unrestricted access to hidden engine state when a scenario is intended to test exploration or inference.

### 3.3 Governance gateway

The gateway evaluates consequential transitions against applicable canonical requirements and current state. It cannot infer authorization from tool availability, actor identity, declared intent, past permission, or audit history.

### 3.4 MCP server

MCP exposes typed application operations. It must not provide direct database-write tools that bypass engine validation or required governance checks.

### 3.5 Event history

Committed transitions and governance decisions must retain traceable lineage. Snapshots may optimize reads but do not replace event history. Historical records are not silently rewritten to make recovery appear successful.

## 4. Project invariants

These are proposed project-level requirements, not new canonical Lattice invariants.

| ID | Requirement |
|---|---|
| WE-01 | Only the world engine can commit authoritative world-state changes. |
| WE-02 | Each committed transition has a unique event identity and traceable lineage. |
| WE-03 | World revisions increase monotonically. |
| WE-04 | Stale mutations cannot silently overwrite newer state. |
| WE-05 | Model claims distinguish observation, inference, hypothesis, conflict, and unknown. |
| WE-06 | Predictions are recorded before the corresponding outcome is disclosed to the model. |
| WE-07 | Hypothetical simulations cannot mutate the live world. |
| WE-08 | Technical capability and declared intent do not confer authorization. |
| WE-09 | Consequential execution requires applicable governance evaluation and valid execution permission. |
| WE-10 | Recovery is an explicit transition with its own lineage. |
| WE-11 | Missing evidence, unresolved conflicts, or unavailable governance state cannot be reported as successful validation. |
| WE-12 | An unsuccessful simulation step must not leave a partially committed world state. |

## 5. World-state contract

An entity minimally contains:

- `entity_id`: stable identifier.
- `entity_type`: validated domain type.
- `attributes`: type-validated state.
- `relationships`: typed references to other entities.
- `lifecycle_state`: explicit status.
- `created_revision` and `updated_revision`.
- `provenance`: originating event or seed record.

A committed event minimally contains:

- `event_id`, `world_id`, and event type.
- `pre_revision` and `post_revision`.
- Actor and declared intent.
- Exact transition target and proposed change.
- Before/after state references or canonical state deltas.
- Evidence and authorization references, where applicable.
- Outcome and event time.
- Recovery relationship, where applicable.

Identifiers are stable. Relationships must resolve to valid entities unless the domain explicitly supports unresolved references. Mutations validate against the current revision and commit atomically.

## 6. Time and persistence

The system distinguishes:

- **World time:** simulated climate, production, travel, and population processes.
- **Action time:** proposal, evaluation, authorization, and execution chronology.
- **Observation time:** when evidence became available to the AI.

The initial engine uses deterministic rules and explicitly recorded parameters. Any later randomized behavior must record its seed and relevant parameters. Time advances only through a defined simulation operation.

Corrections and reversals are new events. A snapshot may restore a known state for an isolated experiment, but a recovery operation on the persistent world must remain auditable.

## 7. Initial scenario: The Valley

The initial scenario includes:

- One river.
- Two settlements.
- Farmland and forest.
- Resource stores.
- One trade route.
- One governing institution.

Initial rules should cover resource production and consumption, river-dependent water access, trade transfers, and explicitly defined effects of resource scarcity. The engine must not introduce an outcome merely because it sounds narratively plausible; each outcome must follow implemented rules.

## 8. Epistemic model contract

A model claim minimally records:

- Claim identifier and model revision.
- Subject, predicate, and object/value.
- Epistemic status: `OBSERVED`, `INFERRED`, `HYPOTHESIS`, `CONFLICTED`, or `UNKNOWN`.
- Supporting and contradicting evidence references.
- Observation time and source.
- Confidence representation, if available.
- Revision history and supersession links.

Confidence is not proof. A hypothesis must not be silently promoted to an authoritative world fact. Unknown or unexplored areas must not be represented as empty merely because no entity has been observed there.

Predictions must be recorded with their target event or experiment before outcome disclosure. Validation compares predictions with engine observations, records discrepancies, and preserves corrections and prior model revisions.

## 9. MCP capability groups

The initial tool surface is organized into these namespaces. Exact schemas must be finalized alongside the implementation.

| Namespace | Responsibilities | Live world mutation |
|---|---|---|
| `world.*` | Observe state, inspect entities, query relationships | No |
| `model.*` | Record claims, compare model, list unknowns | Model records only |
| `simulation.*` | Preview outcomes, compare scenarios, advance simulation time | Preview: no; advance: governed domain operation |
| `transition.*` | Propose and apply exact changes | Proposal: no; apply: yes |
| `governance.*` | Evaluate requests and inspect decision status | No world mutation |
| `history.*` | Inspect events, snapshots, lineage, and audits | No |

Every tool must declare side effects, validation requirements, expected revision behavior, and structured failure modes. No tool may directly bypass engine validation or applicable governance requirements.

## 10. Governed transition lifecycle

For consequential changes:

1. Observe relevant state and evidence.
2. Submit an exact proposal against a specified world revision.
3. Evaluate authority, scope, constraints, lineage, uncertainty, and reversibility under applicable governance.
4. Record the bounded decision and its evidence.
5. Recheck authorization and material state drift at the execution boundary.
6. Apply only the exact authorized transition, atomically.
7. Record resulting state, event lineage, and audit evidence.

Proposal, authorization, and execution are distinct. A successful evaluation does not itself mean execution occurred. Audit history cannot retroactively authorize an action. If required canonical state is unavailable or conflicting, execution must fail closed or remain explicitly blocked pending resolution.

## 11. Recovery semantics

Recovery must not be inferred from a request's acceptance. A recovery plan identifies the prior state, compensating transition, constraints, and expected postconditions. The engine verifies the actual result and records any mismatch. Recovery may itself be impossible or partial; the audit must state that honestly.

## 12. Acceptance criteria

The first implementation is not accepted merely because the application starts or MCP tools return responses. Tests must demonstrate:

1. State persists across independent sessions.
2. Entity and relationship queries return consistent, revisioned state.
3. A committed transition increments the revision and emits a traceable event.
4. Invalid transitions leave no partial changes.
5. Stale proposals are rejected or reevaluated when material assumptions change.
6. Hypothetical experiments cannot mutate live state.
7. Predictions can be inspected as having been recorded before outcome disclosure.
8. Unauthorized mutations are blocked even when the caller can invoke the tool.
9. Missing or conflicting governance evidence is not reported as approval.
10. Model discrepancies and revisions remain traceable.
11. Recovery is verified against actual postconditions.
12. Audit records cannot authorize execution retroactively.

## 13. Implementation sequence

1. Finalize domain contracts and invariants.
2. Implement the authoritative state store, revision model, transaction boundary, and append-only event history.
3. Build deterministic Valley rules and test fixtures.
4. Implement the separate epistemic model and prediction ledger.
5. Add MCP tools over application services.
6. Integrate the governance gateway and adversarial boundary tests.
7. Add adaptive roles and scenario-specific objectives.
8. Add a graphical client only after the engine contracts are stable.

## 14. Non-goals and change control

This specification does not ratify or amend Lattice Canon. Project-specific invariants remain subordinate to applicable canonical requirements. Any conflict must be surfaced and resolved through the established governance process, not silently redefined in application code.

Changes to this specification should identify the affected requirements, rationale, compatibility implications, tests, and lineage. Implementation, deployment, and enabling autonomous execution are separate decisions requiring their own review.
