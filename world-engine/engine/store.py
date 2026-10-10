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
