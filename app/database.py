import os
import sqlite3
from pathlib import Path


class SQLiteDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent.parent / ".courtlens" / "cases.sqlite3"
        self.path = Path(path or os.environ.get("COURTLENS_SQLITE_PATH", default_path))

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    current_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS case_versions (
                    case_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    triggering_event TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    PRIMARY KEY (case_id, version),
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                );

                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    description TEXT NOT NULL,
                    affected_ids_json TEXT NOT NULL,
                    previous_version INTEGER NOT NULL,
                    new_version INTEGER NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                );

                CREATE INDEX IF NOT EXISTS idx_agent_events_case_version
                    ON agent_events(case_id, new_version, timestamp);

                CREATE TRIGGER IF NOT EXISTS immutable_case_versions_update
                BEFORE UPDATE ON case_versions
                BEGIN
                    SELECT RAISE(ABORT, 'case versions are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS immutable_case_versions_delete
                BEFORE DELETE ON case_versions
                BEGIN
                    SELECT RAISE(ABORT, 'case versions are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS append_only_agent_events_update
                BEFORE UPDATE ON agent_events
                BEGIN
                    SELECT RAISE(ABORT, 'agent events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS append_only_agent_events_delete
                BEFORE DELETE ON agent_events
                BEGIN
                    SELECT RAISE(ABORT, 'agent events are append-only');
                END;
                """
            )