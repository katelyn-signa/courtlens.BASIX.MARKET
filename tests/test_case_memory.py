import sqlite3
from pathlib import Path

import pytest

from app.database import SQLiteDatabase
from app.schemas.agent_state import CaseAgentState
from app.schemas.case import CaseMetadata
from app.schemas.facts import ExtractedFact
from app.services.case_memory_service import (
    CaseAlreadyExistsError,
    CaseMemoryService,
    CaseVersionConflictError,
)


def make_state(case_id: str = "C-MEMORY") -> CaseAgentState:
    return CaseAgentState(
        case_id=case_id,
        version=1,
        metadata=CaseMetadata(case_id=case_id, case_title="Memory Test"),
    )


def test_case_creation_persists_across_service_reinitialization(tmp_path: Path) -> None:
    database_path = tmp_path / "restart-test.sqlite3"
    first_service = CaseMemoryService(SQLiteDatabase(database_path))
    state = first_service.create_case(
        make_state(),
        change_summary="Initial version",
        event_specs=[
            {
                "event_type": "CASE_CREATED",
                "description": "Case created",
                "affected_ids": ["C-MEMORY"],
            }
        ],
    )
    assert state.version == 1

    del first_service
    restarted_service = CaseMemoryService(SQLiteDatabase(database_path))
    loaded = restarted_service.get_current_state("C-MEMORY")

    assert loaded.case_id == "C-MEMORY"
    assert loaded.version == 1
    assert loaded.metadata.case_title == "Memory Test"
    assert loaded.agent_events[0].event_type == "CASE_CREATED"


def test_new_version_is_immutable_and_preserves_old_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "versions.sqlite3"
    service = CaseMemoryService(SQLiteDatabase(database_path))
    original = service.create_case(make_state(), change_summary="Version one")
    added_fact = ExtractedFact(
        fact_id="F001",
        fact_type="party",
        field="seller",
        value="ABC Industries",
        normalized_value="ABC Industries",
        document_id="DOC-1",
        page=1,
        quote="Seller: ABC Industries",
        confidence=0.98,
        extraction_method="text",
    )
    new_state = original.model_copy(update={"facts": [added_fact]})
    saved = service.save_new_version(
        new_state,
        change_summary="Added seller fact",
        triggering_event="FACTS_EXTRACTED",
        event_specs=[
            {
                "event_type": "FACTS_EXTRACTED",
                "description": "Seller fact extracted",
                "affected_ids": ["F001"],
            }
        ],
        expected_version=1,
    )

    assert saved.version == 2
    assert service.get_version("C-MEMORY", 1).state.facts == []
    assert [fact.fact_id for fact in service.get_current_state("C-MEMORY").facts] == ["F001"]
    with service.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE case_versions SET change_summary = 'mutated' WHERE case_id = ? AND version = 1",
                ("C-MEMORY",),
            )


def test_agent_events_are_append_only_and_versioned(tmp_path: Path) -> None:
    service = CaseMemoryService(SQLiteDatabase(tmp_path / "events.sqlite3"))
    service.create_case(make_state(), change_summary="Initial")
    state = service.get_current_state("C-MEMORY")
    service.save_new_version(
        state,
        change_summary="State changed",
        triggering_event="CASE_STATE_UPDATED",
        event_specs=[
            {
                "event_type": "CASE_STATE_UPDATED",
                "description": "State updated",
                "affected_ids": ["C-MEMORY"],
            }
        ],
        expected_version=1,
    )

    events = service.list_events("C-MEMORY")
    assert [event.new_version for event in events] == [1, 2]
    assert events[1].previous_version == 1
    with service.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE agent_events SET description = 'mutated' WHERE event_id = ?",
                (events[0].event_id,),
            )


def test_duplicate_create_and_stale_version_are_rejected(tmp_path: Path) -> None:
    service = CaseMemoryService(SQLiteDatabase(tmp_path / "version-conflict.sqlite3"))
    initial = service.create_case(make_state(), change_summary="Initial")

    with pytest.raises(CaseAlreadyExistsError):
        service.create_case(make_state(), change_summary="Duplicate")
    with pytest.raises(CaseVersionConflictError):
        service.save_new_version(
            initial,
            change_summary="Stale write",
            triggering_event="CASE_STATE_UPDATED",
            event_specs=[],
            expected_version=0,
        )


def test_version_history_lists_all_immutable_snapshots(tmp_path: Path) -> None:
    service = CaseMemoryService(SQLiteDatabase(tmp_path / "history.sqlite3"))
    service.create_case(make_state(), change_summary="Initial", source="test")
    service.save_new_version(
        service.get_current_state("C-MEMORY"),
        change_summary="Added evidence",
        triggering_event="EVIDENCE_ADDED",
        event_specs=[],
        expected_version=1,
    )

    versions = service.list_versions("C-MEMORY")

    assert [item["version"] for item in versions] == [1, 2]
    assert versions[0]["triggering_event"] == "CASE_CREATED"
    assert versions[1]["change_summary"] == "Added evidence"