# Lattice World Engine

A persistent hybrid world-building simulation designed as an experimental environment for AI world modeling, causal exploration, scenario planning, and governed state transitions.

## Status

**Design phase — specification draft v0.1.** This directory is an isolated project area. No runtime implementation, MCP server, deployment, or canonical governance mutation is implied by this document.

## Core separation

1. **World engine:** sole authority for committed simulated-world state.
2. **AI world model:** a separate, evidence-backed and potentially incomplete representation of that state.
3. **Governance boundary:** evaluates authority, constraints, lineage, uncertainty, and reversibility before consequential transitions.
4. **Event history:** records proposals, decisions, committed transitions, observations, and recovery events.

MCP is the typed interface to these capabilities; it is not the source of truth and does not itself grant authority.

## Initial scenario: The Valley

The first prototype will contain a river, two settlements, farmland, forest, resource stores, a trade route, and a governing institution. Deterministic rules and recorded parameters come first so experiments can be reproduced and tested.

## First milestone

Establish and validate the authoritative world-state contract, monotonic revisions, transactional state transitions, and append-only event history before implementing the MCP surface.

## Governance

This project is subordinate to applicable Lattice Canon. Project-level requirements in this directory are proposals, not canonical amendments. Changes to canonical governance remain outside the scope of this project.

See [World Engine Specification v0.1](specs/WE-SPEC-001-world-engine-v0.1.md).
