import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.database import SQLiteDatabase
from app.schemas.agent_state import (
    AgentEvent,
    CaseAgentState,
    CaseVersionResponse,
)


class CaseAlreadyExistsError(ValueError):
    pass


class CaseNotFoundError(LookupError):
    pass


class CaseVersionNotFoundError(LookupError):
    pass


class CaseVersionConflictError(RuntimeError):
    pass


class CaseMemoryService:
    def __init__(self, database: SQLiteDatabase | None = None) -> None:
        self.database = database or SQLiteDatabase()
        self.database.initialize()

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AgentEvent:
        return AgentEvent(
            event_id=row["event_id"],
            case_id=row["case_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            source=row["source"],
            description=row["description"],
            affected_ids=json.loads(row["affected_ids_json"]),
            previous_version=row["previous_version"],
            new_version=row["new_version"],
        )

    def case_exists(self, case_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return row is not None

    def _events_for_version(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        version: int,
    ) -> list[AgentEvent]:
        rows = connection.execute(
            "SELECT * FROM agent_events WHERE case_id = ? AND new_version <= ? "
            "ORDER BY timestamp, rowid",
            (case_id, version),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        case_id: str,
        event_type: str,
        source: str,
        description: str,
        affected_ids: list[str],
        previous_version: int,
        new_version: int,
    ) -> None:
        event = AgentEvent(
            event_id=str(uuid4()),
            case_id=case_id,
            timestamp=CaseMemoryService._timestamp(),
            event_type=event_type,
            source=source,
            description=description,
            affected_ids=affected_ids,
            previous_version=previous_version,
            new_version=new_version,
        )
        connection.execute(
            "INSERT INTO agent_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.case_id,
                event.timestamp.isoformat(),
                event.event_type,
                event.source,
                event.description,
                json.dumps(event.affected_ids),
                event.previous_version,
                event.new_version,
            ),
        )

    def _persist_snapshot(
        self,
        connection: sqlite3.Connection,
        state: CaseAgentState,
        version: int,
        change_summary: str,
        triggering_event: str,
    ) -> CaseAgentState:
        timestamp = self._timestamp()
        state = state.model_copy(update={"version": version})
        events = self._events_for_version(connection, state.case_id, version)
        state = state.model_copy(update={"agent_events": events})
        connection.execute(
            "INSERT INTO case_versions "
            "(case_id, version, timestamp, change_summary, triggering_event, state_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                state.case_id,
                version,
                timestamp.isoformat(),
                change_summary,
                triggering_event,
                state.model_dump_json(),
            ),
        )
        return state

    def create_case(
        self,
        state: CaseAgentState,
        *,
        change_summary: str,
        source: str = "case_agent",
        event_specs: list[dict[str, Any]] | None = None,
    ) -> CaseAgentState:
        timestamp = self._timestamp().isoformat()
        specs = event_specs or [
            {
                "event_type": "CASE_CREATED",
                "description": "Persistent case created from initial analysis.",
                "affected_ids": [state.case_id],
            }
        ]
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO cases (case_id, current_version, created_at) VALUES (?, 1, ?)",
                    (state.case_id, timestamp),
                )
                for spec in specs:
                    self._insert_event(
                        connection,
                        case_id=state.case_id,
                        event_type=spec["event_type"],
                        source=spec.get("source", source),
                        description=spec["description"],
                        affected_ids=spec.get("affected_ids", []),
                        previous_version=0,
                        new_version=1,
                    )
                saved = self._persist_snapshot(
                    connection,
                    state,
                    1,
                    change_summary,
                    "CASE_CREATED",
                )
                connection.commit()
                return saved
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise CaseAlreadyExistsError(
                    f"Case '{state.case_id}' already exists. Use the update operation."
                ) from exc
            except Exception:
                connection.rollback()
                raise

    def save_new_version(
        self,
        state: CaseAgentState,
        *,
        change_summary: str,
        triggering_event: str,
        source: str = "case_agent",
        event_specs: list[dict[str, Any]],
        expected_version: int,
    ) -> CaseAgentState:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT current_version FROM cases WHERE case_id = ?",
                    (state.case_id,),
                ).fetchone()
                if row is None:
                    raise CaseNotFoundError(f"Case '{state.case_id}' was not found.")
                current_version = row["current_version"]
                if current_version != expected_version:
                    raise CaseVersionConflictError(
                        f"Case version changed from expected {expected_version} to {current_version}."
                    )
                new_version = current_version + 1
                for spec in event_specs:
                    self._insert_event(
                        connection,
                        case_id=state.case_id,
                        event_type=spec["event_type"],
                        source=spec.get("source", source),
                        description=spec["description"],
                        affected_ids=spec.get("affected_ids", []),
                        previous_version=current_version,
                        new_version=new_version,
                    )
                connection.execute(
                    "UPDATE cases SET current_version = ? WHERE case_id = ?",
                    (new_version, state.case_id),
                )
                saved = self._persist_snapshot(
                    connection,
                    state,
                    new_version,
                    change_summary,
                    triggering_event,
                )
                connection.commit()
                return saved
            except Exception:
                connection.rollback()
                raise

    def get_current_state(self, case_id: str) -> CaseAgentState:
        with self.database.connect() as connection:
            case_row = connection.execute(
                "SELECT current_version FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if case_row is None:
                raise CaseNotFoundError(f"Case '{case_id}' was not found.")
            return self._load_version(connection, case_id, case_row["current_version"])

    def _load_version(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        version: int,
    ) -> CaseAgentState:
        row = connection.execute(
            "SELECT state_json FROM case_versions WHERE case_id = ? AND version = ?",
            (case_id, version),
        ).fetchone()
        if row is None:
            raise CaseVersionNotFoundError(
                f"Version {version} for case '{case_id}' was not found."
            )
        state = CaseAgentState.model_validate_json(row["state_json"])
        return state.model_copy(
            update={"agent_events": self._events_for_version(connection, case_id, version)}
        )

    def get_version(self, case_id: str, version: int) -> CaseVersionResponse:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT timestamp, change_summary, triggering_event FROM case_versions "
                "WHERE case_id = ? AND version = ?",
                (case_id, version),
            ).fetchone()
            if row is None:
                raise CaseVersionNotFoundError(
                    f"Version {version} for case '{case_id}' was not found."
                )
            state = self._load_version(connection, case_id, version)
            return CaseVersionResponse(
                case_id=case_id,
                version=version,
                timestamp=row["timestamp"],
                change_summary=row["change_summary"],
                triggering_event=row["triggering_event"],
                state=state,
            )

    def list_versions(self, case_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone() is None:
                raise CaseNotFoundError(f"Case '{case_id}' was not found.")
            rows = connection.execute(
                "SELECT version, timestamp, change_summary, triggering_event "
                "FROM case_versions WHERE case_id = ? ORDER BY version",
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, case_id: str, limit: int = 100) -> list[AgentEvent]:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone() is None:
                raise CaseNotFoundError(f"Case '{case_id}' was not found.")
            rows = connection.execute(
                "SELECT * FROM agent_events WHERE case_id = ? "
                "ORDER BY timestamp DESC, rowid DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        return [self._event_from_row(row) for row in reversed(rows)]