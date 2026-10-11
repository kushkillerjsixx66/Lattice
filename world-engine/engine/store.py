"""Persistent, revisioned world state with an append-only event history.

This module is a storage/domain primitive, not an authorization gateway and not
an MCP server. Consequential callers must be mediated by a separate governance
service before invoking transition methods.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


class WorldStoreError(Exception):
    """Base exception for world-store failures."""


class ValidationError(WorldStoreError):
    """Raised when a proposed world change violates the storage contract."""


class RevisionConflict(WorldStoreError):
    """Raised when a proposal targets a stale world revision."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class WorldStore:
    """SQLite-backed store for authoritative world state and event lineage.

    Each accepted transition is committed with its event record in one SQLite
    transaction. A failed transition leaves both world state and revision intact.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.database, isolation_level=None, check_same_thread=False, timeout=5.0
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "WorldStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS worlds (
                world_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                world_time INTEGER NOT NULL DEFAULT 0 CHECK (world_time >= 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entities (
                world_id TEXT NOT NULL REFERENCES worlds(world_id),
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                attributes_json TEXT NOT NULL,
                relationships_json TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                created_revision INTEGER NOT NULL,
                updated_revision INTEGER NOT NULL,
                provenance_event_id TEXT NOT NULL,
                PRIMARY KEY (world_id, entity_id)
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(world_id),
                event_type TEXT NOT NULL,
                pre_revision INTEGER,
                post_revision INTEGER NOT NULL,
                actor TEXT NOT NULL,
                intent TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                outcome TEXT NOT NULL,
                event_time TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_world_revision
                ON events(world_id, post_revision);
            CREATE TABLE IF NOT EXISTS epistemic_claims (
                claim_id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(world_id),
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_json TEXT,
                epistemic_status TEXT NOT NULL CHECK (
                    epistemic_status IN ('OBSERVED', 'INFERRED', 'HYPOTHESIS', 'UNKNOWN')
                ),
                source TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                world_revision INTEGER NOT NULL CHECK (world_revision >= 0),
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS predictions (
                prediction_id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(world_id),
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                expected_value_json TEXT NOT NULL,
                basis_revision INTEGER NOT NULL CHECK (basis_revision >= 0),
                evaluate_after_revision INTEGER NOT NULL CHECK (evaluate_after_revision > basis_revision),
                source TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_predictions_scope
                ON predictions(world_id, basis_revision, subject, predicate);
            CREATE TABLE IF NOT EXISTS prediction_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                prediction_id TEXT NOT NULL REFERENCES predictions(prediction_id),
                evaluated_revision INTEGER NOT NULL CHECK (evaluated_revision >= 0),
                observed_value_json TEXT,
                outcome TEXT NOT NULL CHECK (outcome IN ('CONFIRMED', 'REFUTED', 'INDETERMINATE')),
                evidence_ref TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                UNIQUE(prediction_id, evaluated_revision)
            );
            CREATE INDEX IF NOT EXISTS idx_prediction_evaluations_prediction
                ON prediction_evaluations(prediction_id, evaluated_revision);
            CREATE TRIGGER IF NOT EXISTS predictions_reject_update
            BEFORE UPDATE ON predictions
            BEGIN
                SELECT RAISE(ABORT, 'prediction history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS predictions_reject_delete
            BEFORE DELETE ON predictions
            BEGIN
                SELECT RAISE(ABORT, 'prediction history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS prediction_evaluations_reject_update
            BEFORE UPDATE ON prediction_evaluations
            BEGIN
                SELECT RAISE(ABORT, 'prediction evaluation history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS prediction_evaluations_reject_delete
            BEFORE DELETE ON prediction_evaluations
            BEGIN
                SELECT RAISE(ABORT, 'prediction evaluation history is append-only');
            END;
            CREATE INDEX IF NOT EXISTS idx_epistemic_claims_scope
                ON epistemic_claims(world_id, world_revision, subject, predicate);
            CREATE TRIGGER IF NOT EXISTS epistemic_claims_reject_update
            BEFORE UPDATE ON epistemic_claims
            BEGIN
                SELECT RAISE(ABORT, 'epistemic claim history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS epistemic_claims_reject_delete
            BEFORE DELETE ON epistemic_claims
            BEGIN
                SELECT RAISE(ABORT, 'epistemic claim history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS events_reject_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT RAISE(ABORT, 'event history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS events_reject_delete
            BEFORE DELETE ON events
            BEGIN
                SELECT RAISE(ABORT, 'event history is append-only');
            END;
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def create_world(self, name: str, world_id: str | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("world name must be a non-empty string")
        identifier = world_id or str(uuid.uuid4())
        timestamp = _now()
        event_id = str(uuid.uuid4())
        with self._transaction() as db:
            db.execute(
                "INSERT INTO worlds(world_id, name, revision, world_time, created_at) VALUES (?, ?, 0, 0, ?)",
                (identifier, name.strip(), timestamp),
            )
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, NULL, 0, ?, ?, ?, ?, ?)",
                (event_id, identifier, "WORLD_CREATED", "system", "initialize world", _json({"name": name.strip()}), "COMMITTED", timestamp),
            )
        return self.get_world(identifier)

    def create_world_with_entities(
        self,
        name: str,
        entities: Sequence[Mapping[str, Any]],
        world_id: str | None = None,
        *,
        actor: str,
        intent: str,
        event_type: str = "SCENARIO_SEEDED",
    ) -> dict[str, Any]:
        """Create a world and its initial entities in one transaction.

        The creation event is revision 0 and the initialization event is
        revision 1. If any entity or event write fails, the world, entities,
        and both events roll back together. This is a storage primitive only:
        it does not evaluate authority or authorize scenario initialization.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("world name must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise ValidationError("actor must be a non-empty string")
        if not isinstance(intent, str) or not intent.strip():
            raise ValidationError("intent must be a non-empty string")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValidationError("event_type must be a non-empty string")
        if not entities:
            raise ValidationError("initial entities must not be empty")

        normalized = [self._validate_change(change) for change in entities]
        if any(change["op"] != "create" for change in normalized):
            raise ValidationError("initial entities may contain create operations only")

        identifier = world_id or str(uuid.uuid4())
        created_at = _now()
        world_event_id = str(uuid.uuid4())
        seed_event_id = str(uuid.uuid4())
        with self._transaction() as db:
            db.execute(
                "INSERT INTO worlds(world_id, name, revision, world_time, created_at) VALUES (?, ?, 0, 0, ?)",
                (identifier, name.strip(), created_at),
            )
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, NULL, 0, ?, ?, ?, ?, ?)",
                (world_event_id, identifier, "WORLD_CREATED", "system",
                 "initialize world", _json({"name": name.strip()}), "COMMITTED", created_at),
            )

            for change in normalized:
                entity_id = change["entity_id"]
                exists = db.execute(
                    "SELECT 1 FROM entities WHERE world_id = ? AND entity_id = ?",
                    (identifier, entity_id),
                ).fetchone()
                if exists is not None:
                    raise ValidationError(f"entity already exists: {entity_id}")
                db.execute(
                    "INSERT INTO entities(world_id, entity_id, entity_type, attributes_json, relationships_json, lifecycle_state, created_revision, updated_revision, provenance_event_id) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)",
                    (identifier, entity_id, change["entity_type"],
                     _json(change["attributes"]), _json(change["relationships"]),
                     change["lifecycle_state"], seed_event_id),
                )

            db.execute(
                "UPDATE worlds SET revision = 1 WHERE world_id = ?", (identifier,)
            )
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, 0, 1, ?, ?, ?, ?, ?)",
                (seed_event_id, identifier, event_type, actor.strip(), intent.strip(),
                 _json({"changes": [
                     {"op": "create", "entity_id": change["entity_id"],
                      "after": change} for change in normalized
                 ]}), "COMMITTED", _now()),
            )
        return self.get_world(identifier)

    def get_world(self, world_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT world_id, name, revision, world_time, created_at FROM worlds WHERE world_id = ?",
            (world_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"unknown world: {world_id}")
        return dict(row)

    def get_entity(self, world_id: str, entity_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM entities WHERE world_id = ? AND entity_id = ?",
            (world_id, entity_id),
        ).fetchone()
        return self._entity_dict(row) if row else None

    def list_entities(self, world_id: str) -> list[dict[str, Any]]:
        self.get_world(world_id)
        rows = self._connection.execute(
            "SELECT * FROM entities WHERE world_id = ? ORDER BY entity_id", (world_id,)
        ).fetchall()
        return [self._entity_dict(row) for row in rows]

    @staticmethod
    def _entity_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["attributes"] = json.loads(result.pop("attributes_json"))
        result["relationships"] = json.loads(result.pop("relationships_json"))
        return result

    def advance_world_time(
        self,
        world_id: str,
        expected_revision: int,
        steps: int,
        *,
        actor: str,
        intent: str,
    ) -> dict[str, Any]:
        """Advance simulation time as an explicit, revisioned state transition.

        This storage primitive enforces positive bounded input, revision
        consistency, and atomic event lineage. It does not evaluate authority;
        callers must enforce the applicable governance boundary first.
        """
        if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
            raise ValidationError("steps must be a positive integer")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValidationError("expected_revision must be a non-negative integer")
        if not isinstance(actor, str) or not actor.strip():
            raise ValidationError("actor must be a non-empty string")
        if not isinstance(intent, str) or not intent.strip():
            raise ValidationError("intent must be a non-empty string")

        event_id = str(uuid.uuid4())
        with self._transaction() as db:
            world = db.execute(
                "SELECT revision, world_time FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ValidationError(f"unknown world: {world_id}")
            actual_revision = int(world["revision"])
            if actual_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, current revision is {actual_revision}"
                )
            post_revision = actual_revision + 1
            pre_time = int(world["world_time"])
            post_time = pre_time + steps
            db.execute(
                "UPDATE worlds SET revision = ?, world_time = ? WHERE world_id = ?",
                (post_revision, post_time, world_id),
            )
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, world_id, "WORLD_TIME_ADVANCED", actual_revision, post_revision,
                 actor.strip(), intent.strip(),
                 _json({"steps": steps, "pre_world_time": pre_time, "post_world_time": post_time}),
                 "COMMITTED", _now()),
            )
        return {
            "event_id": event_id,
            "world_id": world_id,
            "pre_revision": actual_revision,
            "post_revision": post_revision,
            "pre_world_time": pre_time,
            "post_world_time": post_time,
            "outcome": "COMMITTED",
        }

    def commit_turn_transition(
        self,
        world_id: str,
        expected_revision: int,
        changes: Sequence[Mapping[str, Any]],
        *,
        actor: str,
        intent: str,
        ruleset_id: str,
        steps: int = 1,
    ) -> dict[str, Any]:
        """Atomically commit one turn's entity updates and simulation time.

        This is a storage primitive, not a governance gateway. It checks exact
        revision, turn shape, and data integrity, but does not authenticate a
        receipt, evaluate policy, or grant execution authority. Runtime callers
        must not expose this method until the required governance boundary exists.
        """
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValidationError("expected_revision must be a non-negative integer")
        if not isinstance(steps, int) or isinstance(steps, bool) or steps != 1:
            raise ValidationError("committed Valley turns currently require exactly one step")
        for label, value in (("actor", actor), ("intent", intent), ("ruleset_id", ruleset_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{label} must be a non-empty string")
        if not changes:
            raise ValidationError("turn must contain at least one entity update")

        normalized = [self._validate_change(change) for change in changes]
        if any(change["op"] != "update" for change in normalized):
            raise ValidationError("turn transitions may contain update operations only")
        if any(set(change) != {"op", "entity_id", "attributes"} for change in normalized):
            raise ValidationError("turn updates may change attributes only")
        entity_ids = [change["entity_id"] for change in normalized]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValidationError("turn may update each entity at most once")
        try:
            for change in normalized:
                _json(change["attributes"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("turn attributes must be JSON-serializable") from exc

        event_id = str(uuid.uuid4())
        with self._transaction() as db:
            world = db.execute(
                "SELECT revision, world_time FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ValidationError(f"unknown world: {world_id}")
            actual_revision = int(world["revision"])
            if actual_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, current revision is {actual_revision}"
                )
            pre_time = int(world["world_time"])
            post_time = pre_time + steps
            post_revision = actual_revision + 1
            before_after: list[dict[str, Any]] = []

            for change in normalized:
                entity_id = change["entity_id"]
                current = db.execute(
                    "SELECT * FROM entities WHERE world_id = ? AND entity_id = ?",
                    (world_id, entity_id),
                ).fetchone()
                if current is None:
                    raise ValidationError(f"cannot update missing entity: {entity_id}")
                old = self._entity_dict(current)
                new_attributes = change["attributes"]
                db.execute(
                    "UPDATE entities SET attributes_json = ?, updated_revision = ? "
                    "WHERE world_id = ? AND entity_id = ?",
                    (_json(new_attributes), post_revision, world_id, entity_id),
                )
                before_after.append({
                    "op": "update",
                    "entity_id": entity_id,
                    "before": old,
                    "after": {
                        "entity_type": old["entity_type"],
                        "attributes": new_attributes,
                        "relationships": old["relationships"],
                        "lifecycle_state": old["lifecycle_state"],
                    },
                })

            db.execute(
                "UPDATE worlds SET revision = ?, world_time = ? WHERE world_id = ?",
                (post_revision, post_time, world_id),
            )
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, world_id, "VALLEY_TURN_COMMITTED",
                    actual_revision, post_revision, actor.strip(), intent.strip(),
                    _json({
                        "ruleset_id": ruleset_id.strip(),
                        "steps": steps,
                        "pre_world_time": pre_time,
                        "post_world_time": post_time,
                        "changes": before_after,
                    }),
                    "COMMITTED", _now(),
                ),
            )

        return {
            "event_id": event_id,
            "world_id": world_id,
            "pre_revision": actual_revision,
            "post_revision": post_revision,
            "pre_world_time": pre_time,
            "post_world_time": post_time,
            "ruleset_id": ruleset_id.strip(),
            "outcome": "COMMITTED",
            "authorization_evaluated": False,
            "execution_authorized": False,
        }

    def apply_transition(
        self,
        world_id: str,
        expected_revision: int,
        changes: Sequence[Mapping[str, Any]],
        *,
        actor: str,
        intent: str,
        event_type: str = "STATE_TRANSITION",
    ) -> dict[str, Any]:
        """Apply a bounded batch of entity operations atomically.

        Each change is one of:
          {"op":"create", "entity_id":..., "entity_type":..., "attributes":..., "relationships":..., "lifecycle_state":...}
          {"op":"update", "entity_id":..., "attributes":..., "relationships":..., "lifecycle_state":...}
          {"op":"delete", "entity_id":...}

        This method checks data integrity and revision consistency only. It does
        not grant or evaluate execution authority; that boundary must be enforced
        by the service that calls it.
        """
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValidationError("expected_revision must be a non-negative integer")
        if not isinstance(actor, str) or not actor.strip():
            raise ValidationError("actor must be a non-empty string")
        if not isinstance(intent, str) or not intent.strip():
            raise ValidationError("intent must be a non-empty string")
        if not changes:
            raise ValidationError("transition must contain at least one change")

        normalized = [self._validate_change(change) for change in changes]
        event_id = str(uuid.uuid4())
        with self._transaction() as db:
            world = db.execute(
                "SELECT revision FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ValidationError(f"unknown world: {world_id}")
            actual_revision = int(world["revision"])
            if actual_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, current revision is {actual_revision}"
                )
            post_revision = actual_revision + 1
            before_after: list[dict[str, Any]] = []
            for change in normalized:
                entity_id = change["entity_id"]
                current = db.execute(
                    "SELECT * FROM entities WHERE world_id = ? AND entity_id = ?",
                    (world_id, entity_id),
                ).fetchone()
                op = change["op"]
                if op == "create":
                    if current is not None:
                        raise ValidationError(f"entity already exists: {entity_id}")
                    db.execute(
                        "INSERT INTO entities(world_id, entity_id, entity_type, attributes_json, relationships_json, lifecycle_state, created_revision, updated_revision, provenance_event_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (world_id, entity_id, change["entity_type"], _json(change["attributes"]), _json(change["relationships"]), change["lifecycle_state"], post_revision, post_revision, event_id),
                    )
                    before_after.append({"op": op, "entity_id": entity_id, "before": None, "after": change})
                elif op == "update":
                    if current is None:
                        raise ValidationError(f"cannot update missing entity: {entity_id}")
                    old = self._entity_dict(current)
                    new_type = change.get("entity_type", old["entity_type"])
                    new_attributes = change.get("attributes", old["attributes"])
                    new_relationships = change.get("relationships", old["relationships"])
                    new_lifecycle = change.get("lifecycle_state", old["lifecycle_state"])
                    db.execute(
                        "UPDATE entities SET entity_type = ?, attributes_json = ?, relationships_json = ?, lifecycle_state = ?, updated_revision = ? WHERE world_id = ? AND entity_id = ?",
                        (new_type, _json(new_attributes), _json(new_relationships), new_lifecycle, post_revision, world_id, entity_id),
                    )
                    before_after.append({"op": op, "entity_id": entity_id, "before": old, "after": {"entity_type": new_type, "attributes": new_attributes, "relationships": new_relationships, "lifecycle_state": new_lifecycle}})
                else:
                    if current is None:
                        raise ValidationError(f"cannot delete missing entity: {entity_id}")
                    old = self._entity_dict(current)
                    db.execute("DELETE FROM entities WHERE world_id = ? AND entity_id = ?", (world_id, entity_id))
                    before_after.append({"op": op, "entity_id": entity_id, "before": old, "after": None})
            db.execute("UPDATE worlds SET revision = ? WHERE world_id = ?", (post_revision, world_id))
            db.execute(
                "INSERT INTO events(event_id, world_id, event_type, pre_revision, post_revision, actor, intent, payload_json, outcome, event_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, world_id, event_type, actual_revision, post_revision, actor.strip(), intent.strip(), _json({"changes": before_after}), "COMMITTED", _now()),
            )
        return {"event_id": event_id, "world_id": world_id, "pre_revision": actual_revision, "post_revision": post_revision, "outcome": "COMMITTED"}

    @staticmethod
    def _validate_change(change: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(change, Mapping):
            raise ValidationError("each change must be an object")
        op = change.get("op")
        entity_id = change.get("entity_id")
        if op not in {"create", "update", "delete"}:
            raise ValidationError(f"unsupported operation: {op!r}")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise ValidationError("entity_id must be a non-empty string")
        normalized: dict[str, Any] = {"op": op, "entity_id": entity_id.strip()}
        if op == "create":
            entity_type = change.get("entity_type")
            if not isinstance(entity_type, str) or not entity_type.strip():
                raise ValidationError("create requires a non-empty entity_type")
            normalized.update({
                "entity_type": entity_type.strip(),
                "attributes": change.get("attributes", {}),
                "relationships": change.get("relationships", {}),
                "lifecycle_state": change.get("lifecycle_state", "ACTIVE"),
            })
        elif op == "update":
            for key in ("entity_type", "attributes", "relationships", "lifecycle_state"):
                if key in change:
                    normalized[key] = change[key]
            if len(normalized) == 2:
                raise ValidationError("update requires at least one field to change")
        if "attributes" in normalized and not isinstance(normalized["attributes"], dict):
            raise ValidationError("attributes must be an object")
        if "relationships" in normalized and not isinstance(normalized["relationships"], dict):
            raise ValidationError("relationships must be an object")
        if "lifecycle_state" in normalized and (not isinstance(normalized["lifecycle_state"], str) or not normalized["lifecycle_state"].strip()):
            raise ValidationError("lifecycle_state must be a non-empty string")
        return normalized

    def record_claim(
        self,
        world_id: str,
        *,
        subject: str,
        predicate: str,
        value: Any,
        epistemic_status: str,
        source: str,
        source_ref: str,
        world_revision: int,
    ) -> dict[str, Any]:
        """Append an epistemic claim without changing authoritative world state.

        CONFLICTED is derived when multiple distinct non-UNKNOWN values exist
        for the same subject, predicate, and source world revision. It is not an
        input status and conflict detection does not adjudicate which claim wins.
        """
        allowed = {"OBSERVED", "INFERRED", "HYPOTHESIS", "UNKNOWN"}
        if not isinstance(subject, str) or not subject.strip():
            raise ValidationError("claim subject must be a non-empty string")
        if not isinstance(predicate, str) or not predicate.strip():
            raise ValidationError("claim predicate must be a non-empty string")
        if not isinstance(epistemic_status, str) or epistemic_status not in allowed:
            raise ValidationError(f"unsupported epistemic status: {epistemic_status!r}")
        if not isinstance(source, str) or not source.strip():
            raise ValidationError("claim source must be a non-empty string")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValidationError("claim source_ref must be a non-empty string")
        if not isinstance(world_revision, int) or isinstance(world_revision, bool) or world_revision < 0:
            raise ValidationError("world_revision must be a non-negative integer")
        if epistemic_status == "UNKNOWN" and value is not None:
            raise ValidationError("UNKNOWN claims must have a null value")
        if epistemic_status != "UNKNOWN" and value is None:
            raise ValidationError("non-UNKNOWN claims require a value")
        try:
            value_json = None if value is None else _json(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("claim value must be JSON-serializable") from exc

        claim_id = str(uuid.uuid4())
        with self._transaction() as db:
            world = db.execute(
                "SELECT revision FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ValidationError(f"unknown world: {world_id}")
            if world_revision > int(world["revision"]):
                raise ValidationError(
                    f"claim revision {world_revision} exceeds current world revision {world['revision']}"
                )
            db.execute(
                "INSERT INTO epistemic_claims(claim_id, world_id, subject, predicate, value_json, epistemic_status, source, source_ref, world_revision, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, world_id, subject.strip(), predicate.strip(), value_json,
                 epistemic_status, source.strip(), source_ref.strip(), world_revision, _now()),
            )
        return {
            "claim_id": claim_id,
            "world_id": world_id,
            "subject": subject.strip(),
            "predicate": predicate.strip(),
            "value": value,
            "epistemic_status": epistemic_status,
            "effective_status": epistemic_status,
            "source": source.strip(),
            "source_ref": source_ref.strip(),
            "world_revision": world_revision,
        }

    def list_claims(self, world_id: str, world_revision: int | None = None) -> list[dict[str, Any]]:
        """Read claims, deriving conflicts without overwriting original status."""
        self.get_world(world_id)
        if world_revision is not None:
            if not isinstance(world_revision, int) or isinstance(world_revision, bool) or world_revision < 0:
                raise ValidationError("world_revision must be a non-negative integer")
            rows = self._connection.execute(
                "SELECT * FROM epistemic_claims WHERE world_id = ? AND world_revision = ? ORDER BY recorded_at, claim_id",
                (world_id, world_revision),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM epistemic_claims WHERE world_id = ? ORDER BY world_revision, recorded_at, claim_id",
                (world_id,),
            ).fetchall()

        decoded = []
        values_by_key: dict[tuple[str, int, str], set[str]] = {}
        for row in rows:
            item = dict(row)
            raw_value = item.pop("value_json")
            item["value"] = json.loads(raw_value) if raw_value is not None else None
            item["epistemic_status"] = item.pop("epistemic_status")
            item["effective_status"] = item["epistemic_status"]
            if item["epistemic_status"] != "UNKNOWN":
                key = (item["subject"], int(item["world_revision"]), item["predicate"])
                values_by_key.setdefault(key, set()).add(_json(item["value"]))
            decoded.append(item)

        for item in decoded:
            key = (item["subject"], int(item["world_revision"]), item["predicate"])
            if len(values_by_key.get(key, set())) > 1:
                item["effective_status"] = "CONFLICTED"
        return decoded

    def record_prediction(
        self,
        world_id: str,
        *,
        subject: str,
        predicate: str,
        expected_value: Any,
        basis_revision: int,
        evaluate_after_revision: int,
        source: str,
        source_ref: str,
    ) -> dict[str, Any]:
        """Register an immutable, falsifiable prediction before its target revision."""
        for field_name, value in (("subject", subject), ("predicate", predicate),
                                  ("source", source), ("source_ref", source_ref)):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"prediction {field_name} must be a non-empty string")
        for field_name, value in (("basis_revision", basis_revision),
                                  ("evaluate_after_revision", evaluate_after_revision)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationError(f"{field_name} must be a non-negative integer")
        if evaluate_after_revision <= basis_revision:
            raise ValidationError("evaluate_after_revision must be later than basis_revision")
        try:
            expected_json = _json(expected_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("expected_value must be JSON-serializable") from exc

        prediction_id = str(uuid.uuid4())
        created_at = _now()
        with self._transaction() as db:
            world = db.execute(
                "SELECT revision FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ValidationError(f"unknown world: {world_id}")
            current_revision = int(world["revision"])
            if basis_revision != current_revision:
                raise RevisionConflict(
                    f"prediction basis revision {basis_revision} is not current revision {current_revision}"
                )
            db.execute(
                "INSERT INTO predictions(prediction_id, world_id, subject, predicate, expected_value_json, basis_revision, evaluate_after_revision, source, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (prediction_id, world_id, subject.strip(), predicate.strip(), expected_json,
                 basis_revision, evaluate_after_revision, source.strip(), source_ref.strip(), created_at),
            )
        return {
            "prediction_id": prediction_id, "world_id": world_id,
            "subject": subject.strip(), "predicate": predicate.strip(),
            "expected_value": expected_value, "basis_revision": basis_revision,
            "evaluate_after_revision": evaluate_after_revision,
            "source": source.strip(), "source_ref": source_ref.strip(),
            "created_at": created_at,
        }

    def list_predictions(self, world_id: str) -> list[dict[str, Any]]:
        """Read immutable prediction registrations and preserve their original values."""
        self.get_world(world_id)
        rows = self._connection.execute(
            "SELECT * FROM predictions WHERE world_id = ? ORDER BY basis_revision, created_at, prediction_id",
            (world_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["expected_value"] = json.loads(item.pop("expected_value_json"))
            result.append(item)
        return result

    def evaluate_prediction(
        self, prediction_id: str, *, evaluated_revision: int, evidence_ref: str
    ) -> dict[str, Any]:
        """Evaluate only from unambiguous OBSERVED claims at a later world revision."""
        if not isinstance(evaluated_revision, int) or isinstance(evaluated_revision, bool) or evaluated_revision < 0:
            raise ValidationError("evaluated_revision must be a non-negative integer")
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise ValidationError("evidence_ref must be a non-empty string")
        evaluation_id = str(uuid.uuid4())
        evaluated_at = _now()
        with self._transaction() as db:
            prediction = db.execute(
                "SELECT * FROM predictions WHERE prediction_id = ?", (prediction_id,)
            ).fetchone()
            if prediction is None:
                raise ValidationError(f"unknown prediction: {prediction_id}")
            world = db.execute(
                "SELECT revision FROM worlds WHERE world_id = ?", (prediction["world_id"],)
            ).fetchone()
            if evaluated_revision <= int(prediction["basis_revision"]):
                raise ValidationError("prediction cannot be evaluated at or before its basis revision")
            if evaluated_revision < int(prediction["evaluate_after_revision"]):
                raise ValidationError("prediction is not yet eligible for evaluation")
            if evaluated_revision > int(world["revision"]):
                raise ValidationError("evaluation revision exceeds current world revision")

            claims = db.execute(
                "SELECT value_json FROM epistemic_claims WHERE world_id = ? AND subject = ? AND predicate = ? AND world_revision = ? AND epistemic_status = 'OBSERVED'",
                (prediction["world_id"], prediction["subject"], prediction["predicate"], evaluated_revision),
            ).fetchall()
            observed_values = {row["value_json"] for row in claims}
            if len(observed_values) != 1:
                outcome = "INDETERMINATE"
                observed_json = None
            else:
                observed_json = next(iter(observed_values))
                outcome = "CONFIRMED" if observed_json == prediction["expected_value_json"] else "REFUTED"
            db.execute(
                "INSERT INTO prediction_evaluations(evaluation_id, prediction_id, evaluated_revision, observed_value_json, outcome, evidence_ref, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (evaluation_id, prediction_id, evaluated_revision, observed_json, outcome,
                 evidence_ref.strip(), evaluated_at),
            )
        return {
            "evaluation_id": evaluation_id, "prediction_id": prediction_id,
            "world_id": prediction["world_id"], "evaluated_revision": evaluated_revision,
            "observed_value": json.loads(observed_json) if observed_json is not None else None,
            "outcome": outcome, "evidence_ref": evidence_ref.strip(),
            "evaluated_at": evaluated_at,
        }

    def list_prediction_evaluations(self, prediction_id: str) -> list[dict[str, Any]]:
        """Return append-only evaluations for one prediction."""
        rows = self._connection.execute(
            "SELECT e.* FROM prediction_evaluations e JOIN predictions p ON p.prediction_id = e.prediction_id WHERE p.prediction_id = ? ORDER BY e.evaluated_revision, e.evaluated_at, e.evaluation_id",
            (prediction_id,),
        ).fetchall()
        if not rows:
            exists = self._connection.execute(
                "SELECT 1 FROM predictions WHERE prediction_id = ?", (prediction_id,)
            ).fetchone()
            if exists is None:
                raise ValidationError(f"unknown prediction: {prediction_id}")
        result = []
        for row in rows:
            item = dict(row)
            raw_value = item.pop("observed_value_json")
            item["observed_value"] = json.loads(raw_value) if raw_value is not None else None
            result.append(item)
        return result

    def list_events(self, world_id: str) -> list[dict[str, Any]]:
        self.get_world(world_id)
        rows = self._connection.execute(
            "SELECT * FROM events WHERE world_id = ? ORDER BY post_revision, event_time, event_id",
            (world_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result
