# External Governance Verifier Contract v0.1

**Status:** Proposed integration contract; not canonical Lattice law and not an authorization implementation.

## Purpose

Define the minimum boundary required before the World Engine may treat an externally supplied governance receipt as an authenticated decision. The current receipt validator establishes structural binding only. A receipt's self-reported decision, authority source, reference, signature metadata, or `verified` flag is not proof of authenticity or permission.

This contract does not select or invent a trust provider, key infrastructure, signing format, policy evaluator, or execution gateway. Those dependencies must be identified and independently configured before implementation.

## Trust boundary

1. Trust anchors and verifier configuration must originate from an explicitly configured, independently controlled source. They must not be accepted from the proposal, receipt, model output, MCP arguments, or the actor requesting the transition.
2. Missing, unavailable, malformed, expired, revoked, ambiguous, or unsupported trust configuration fails closed.
3. The verifier must not bootstrap trust from a receipt's `authority_source`, `decision_reference`, `key_id`, `verified`, or equivalent caller-controlled field.
4. The verifier authenticates provenance and integrity only. It does not by itself establish that the signer had authority for this action, that policy was correctly evaluated, or that the transition may execute.
5. No verifier result may directly execute a transition or mutate world state.

## Required verification dimensions

An implementation must independently establish and report each applicable dimension:

- **Authenticity:** the decision artifact was produced by an accepted issuer using a configured verification mechanism.
- **Integrity:** the authenticated content covers the exact decision-relevant receipt fields, including decision, proposal ID, world ID, expected revision, proposal fingerprint, issuer identity, decision reference, and any validity/scope fields required by the chosen protocol.
- **Issuer trust:** issuer identity resolves to a configured trust record; identity asserted by the artifact is not itself a trust record.
- **Scope:** the trusted issuer's configured scope covers the relevant world, action class, and requested transition.
- **Decision semantics:** only explicitly recognized decision values are accepted. An authenticated `DENIED`, `UNRESOLVED`, or `STALE` decision remains non-authorizing.
- **Validity and revocation:** applicable validity windows, key/issuer status, and revocation information are checked according to the selected trust protocol. If required status cannot be established, verification is unresolved, not successful.
- **Replay resistance:** a valid artifact cannot be reused for a different proposal, world, revision, or scope. Any nonce, expiry, unique receipt identifier, or consumed-decision policy must be specified by the chosen protocol.
- **Freshness:** the current world revision and all relevant authority/policy versions are rechecked at the eventual execution boundary. A prior successful verification is not a permanent execution permit.
- **Audit lineage:** record the verifier implementation/version, trust-record identifier/version, authenticated artifact digest, verification time, result dimensions, and unresolved limitations without storing secrets.

The concrete signature scheme, canonical serialization, key distribution, rotation, revocation protocol, and trusted policy authority remain explicit integration decisions. Do not infer them from this contract.

## Result contract

The verifier should return a structured, non-authorizing result with at least:

- `verification_status`: `VERIFIED`, `REJECTED`, or `UNRESOLVED`
- `authenticity_status`
- `integrity_status`
- `issuer_trust_status`
- `scope_status`
- `validity_status`
- `replay_status`
- `receipt_id` and authenticated artifact digest when available
- `verifier_id` and `verifier_version`
- `trust_record_ref` and trust-record version when available
- `limitations` and machine-readable failure reasons
- `execution_permitted: false`
- `mutates_world: false`
- `grants_authority: false`

`VERIFIED` means only that the configured verifier established the defined authenticity/integrity conditions. It is not equivalent to an authorization decision and must not be surfaced as a general permission boolean.

## Required fail-closed tests before implementation is considered conformant

- A receipt containing `verified: true` without valid verification evidence is not verified.
- Caller-supplied keys, trust anchors, issuer allowlists, or verifier configuration cannot change the trusted configuration.
- Unknown issuer, unknown key, unsupported algorithm, malformed signature, altered signed field, or incomplete signed payload cannot yield `VERIFIED`.
- Missing or unavailable trust configuration yields `UNRESOLVED` or a typed failure, never success.
- Expired or revoked credentials and stale authority records do not yield `VERIFIED`.
- A valid artifact bound to a different proposal, world, revision, or scope is rejected.
- A valid authenticated denial is authenticated as a denial and never treated as approval.
- Duplicate/replayed receipts follow an explicit, persisted replay policy and cannot silently authorize a new transition.
- Verification has no world-state, event-history, prediction-ledger, or model side effects.
- Even a `VERIFIED` result cannot directly execute a transition or set `execution_permitted` to true.
- Drift between verification and any future execution attempt forces fresh checks; no cached result is an execution token.
- Failures and uncertainty remain distinguishable in audit output; neither is converted to approval.

## Integration gates

Do not implement a production verifier until all of the following are named and testable:

1. The actual external governance decision issuer and authoritative identity source.
2. The source and owner of trusted issuer/key configuration.
3. The signed payload format and exact field coverage.
4. Key lifecycle, revocation, expiry, and rotation behavior.
5. Replay policy and persistence requirements.
6. The policy authority that determines whether the issuer may approve this specific transition.
7. The audit and failure-recovery contract.
8. Independent adversarial tests for the complete integration.

Until these dependencies are established, the existing World Engine receipt path must remain `UNVERIFIED`, non-authorizing, and incapable of execution.

## Relationship to Lattice Canon

This document is a project-level proposed interface contract only. It neither amends Canonical Vault state nor redefines canonical governance gates. Applicable Lattice Canon remains authoritative. Technical verification capability must not be treated as execution authority, and uncertainty must not be converted into permission.
