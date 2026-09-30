from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.case_agent import CaseAgent
from app.database import SQLiteDatabase
from app.main import app
from app.schemas.agent_state import (
    AgentStartRequest,
    AgentUpdateRequest,
    CaseChallengeRequest,
    CaseHumanReviewRequest,
    CaseOverrideRequest,
    CaseWhatIfRequest,
)
from app.schemas.analysis import CaseAnalysisDocumentInput
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.evidence import Evidence
from app.schemas.facts import ExtractedFact
from app.services.case_memory_service import CaseAlreadyExistsError, CaseMemoryService

client = TestClient(app)


def agreement(document_id: str, amount: int = 500000) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id=document_id,
        filename=f"{document_id}.pdf",
        page_count=1,
        pages=[DocumentPage(
            page=1,
            text=(
                "COMMERCIAL PAYMENT AGREEMENT\nSeller: ABC Industries\n"
                "Buyer: XYZ Traders\n"
                f"Contract Amount: INR {amount}\n"
                "Payment Due Date: 10 August 2026"
            ),
            extraction_method="text",
        )],
    )


def new_agent(path: Path) -> CaseAgent:
    return CaseAgent(CaseMemoryService(SQLiteDatabase(path)))


def start_request(*documents: CaseAnalysisDocumentInput) -> AgentStartRequest:
    return AgentStartRequest(
        case_title="SME Payment Dispute",
        case_type="commercial_dispute",
        documents=list(documents),
    )


def c104_start_request() -> AgentStartRequest:
    return AgentStartRequest(
        case_title="Hearing Date Conflict",
        documents=[
            CaseAnalysisDocumentInput(
                document_id=document_id,
                source_type=source_type,
                extracted_document=DocumentExtractionResult(
                    document_id=document_id,
                    filename=f"{document_id}.txt",
                    page_count=1,
                    pages=[DocumentPage(page=1, text=text, extraction_method="text")],
                ),
            )
            for document_id, source_type, text in (
                (
                    "DOC-001",
                    None,
                    "The matter is listed for hearing on 15 October 2026.",
                ),
                (
                    "DOC-002",
                    "advocate_note",
                    "Client has been informed that the next hearing is scheduled for 8 October 2026.",
                ),
                (
                    "DOC-003",
                    "party_document",
                    "Previous communication mentions an expected hearing during the second week of October 2026.",
                ),
            )
        ],
    )


def payment_document() -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id="DOC-PAYMENT",
        filename="payment-record.pdf",
        page_count=1,
        pages=[DocumentPage(
            page=1,
            text="BANK TRANSACTION\nTransaction ID: TXN-001\nPayment Date: 12 August 2026\nAmount Paid: INR 200000",
            extraction_method="text",
        )],
    )


def test_start_persists_version_one_and_refuses_overwrite(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "start.sqlite3")
    result = agent.start(
        "C-104",
        start_request(CaseAnalysisDocumentInput(extracted_document=agreement("DOC-CONTRACT"))),
    )

    assert result.state.version == 1
    assert result.state.metadata.case_title == "SME Payment Dispute"
    assert any(event.event_type == "CASE_CREATED" for event in result.state.agent_events)
    with pytest.raises(CaseAlreadyExistsError):
        agent.start("C-104", start_request())


def test_update_adds_new_payment_document_version_and_targeted_rules(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "update.sqlite3")
    first = agent.start(
        "C-UPDATE",
        start_request(CaseAnalysisDocumentInput(extracted_document=agreement("DOC-CONTRACT"))),
    ).state
    result = agent.update(
        "C-UPDATE",
        AgentUpdateRequest(
            documents=[CaseAnalysisDocumentInput(extracted_document=payment_document())],
            verified_evidence_ids=["E0002"],
        ),
    )

    assert first.version == 1
    assert result.state.version == 2
    assert result.changes["added_documents"] == ["DOC-PAYMENT"]
    assert result.affected_rule_ids == ["R001", "R003", "R005"]
    assert result.reasoning_recomputed
    assert any(
        rule.rule_id == "R001" and rule.triggered
        for rule in result.state.reasoning_results[-1].rules_evaluated
    )


def test_state_survives_new_memory_service_and_old_version_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    agent = new_agent(path)
    first = agent.start(
        "C-RESTART",
        start_request(CaseAnalysisDocumentInput(extracted_document=agreement("DOC-1"))),
    ).state
    second = agent.update(
        "C-RESTART",
        AgentUpdateRequest(facts=[ExtractedFact(
            fact_id="F-MANUAL", fact_type="identity", field="transaction_id",
            value="TXN-X", normalized_value="TXN-X", document_id="DOC-EXTRA",
            page=1, quote="Transaction ID: TXN-X", confidence=0.98,
        )]),
    ).state
    restarted = new_agent(path)

    assert first.version == 1 and second.version == 2
    assert restarted.memory.get_current_state("C-RESTART").version == 2
    assert any(item.fact_id == "F-MANUAL" for item in restarted.memory.get_current_state("C-RESTART").facts)
    assert all(item.fact_id != "F-MANUAL" for item in restarted.memory.get_version("C-RESTART", 1).state.facts)


def test_duplicate_structured_evidence_does_not_create_a_version(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "dedupe.sqlite3")
    agent.start("C-DUPE", start_request(CaseAnalysisDocumentInput(extracted_document=agreement("DOC-1"))))
    evidence = Evidence(
        evidence_id="E-MANUAL", evidence_type="identity_record", document_id="DOC-1",
        document_type="contract", page=1, quote="Agreement ID: A-1",
        normalized_value="A-1", confidence=0.9,
    )

    first = agent.update("C-DUPE", AgentUpdateRequest(evidence=[evidence]))
    duplicate = agent.update("C-DUPE", AgentUpdateRequest(evidence=[evidence]))

    assert first.state.version == 2
    assert duplicate.state.version == 2
    assert not duplicate.reasoning_recomputed
    assert sum(item.evidence_id == "E-MANUAL" for item in duplicate.state.evidence) == 1


def test_changed_document_resolves_conflict_and_diff_reports_it(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "resolve.sqlite3")
    agent.start(
        "C-RESOLVE",
        start_request(
            CaseAnalysisDocumentInput(extracted_document=agreement("DOC-A", 500000)),
            CaseAnalysisDocumentInput(extracted_document=agreement("DOC-B", 400000)),
        ),
    )
    before = agent.memory.get_current_state("C-RESOLVE")
    assert len(before.conflicts) == 1
    conflict_id = before.conflicts[0].conflict_id
    update = agent.update(
        "C-RESOLVE",
        AgentUpdateRequest(documents=[CaseAnalysisDocumentInput(extracted_document=agreement("DOC-B", 500000))]),
    )
    diff = agent.diff("C-RESOLVE", 1, 2)

    assert update.changes["resolved_conflicts"] == [conflict_id]
    assert diff.resolved_conflicts == [conflict_id]
    assert diff.changed_documents == ["DOC-B"]
    assert agent.memory.get_version("C-RESOLVE", 1).state.conflicts[0].conflict_id == conflict_id

def test_new_delivery_evidence_resolves_delivery_gap(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "gap-resolution.sqlite3")
    claim_document = DocumentExtractionResult(
        document_id="DOC-CLAIM",
        filename="claim.pdf",
        page_count=1,
        pages=[DocumentPage(
            page=1,
            text="STATEMENT OF CLAIM\nBuyer claims that goods were delivered.",
            extraction_method="text",
        )],
    )
    first = agent.start(
        "C-GAP",
        start_request(CaseAnalysisDocumentInput(extracted_document=claim_document)),
    )
    assert any(gap.gap_type == "missing_delivery_proof" for gap in first.state.evidence_gaps)
    delivery_document = DocumentExtractionResult(
        document_id="DOC-DELIVERY",
        filename="delivery-receipt.pdf",
        page_count=1,
        pages=[DocumentPage(
            page=1,
            text="DELIVERY RECEIPT\nDelivery Date: 5 August 2026\nReceived By: XYZ Traders",
            extraction_method="text",
        )],
    )

    updated = agent.update(
        "C-GAP",
        AgentUpdateRequest(documents=[CaseAnalysisDocumentInput(extracted_document=delivery_document)]),
    )

    assert updated.state.version == 2
    assert updated.changes["resolved_gaps"]
    assert not any(gap.gap_type == "missing_delivery_proof" for gap in updated.state.evidence_gaps)
    assert any(event.event_type == "EVIDENCE_GAP_RESOLVED" for event in updated.state.agent_events)


def test_unrelated_party_fact_does_not_refresh_payment_rules(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "targeted.sqlite3")
    initial = agent.start("C-TARGET", start_request(CaseAnalysisDocumentInput(extracted_document=agreement("DOC-1")))).state
    previous_reasoning_id = initial.reasoning_results[-1].reasoning_id
    unrelated_fact = ExtractedFact(
        fact_id="F-RECIPIENT", fact_type="party", field="recipient",
        value="North Freight", normalized_value="North Freight", document_id="DOC-FREIGHT",
        page=1, quote="Recipient: North Freight", confidence=0.98,
    )

    updated = agent.update("C-TARGET", AgentUpdateRequest(facts=[unrelated_fact]))

    assert updated.state.version == 2
    assert updated.affected_rule_ids == []
    assert not updated.reasoning_recomputed
    assert updated.state.reasoning_results[-1].reasoning_id == previous_reasoning_id


def test_challenge_is_persisted_and_triggers_verification_gap(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "challenge.sqlite3")
    agent.start(
        "C-CHALLENGE",
        start_request(
            CaseAnalysisDocumentInput(extracted_document=agreement("DOC-CONTRACT")),
            CaseAnalysisDocumentInput(extracted_document=payment_document()),
        ),
    )
    payment_record = next(
        item
        for item in agent.memory.get_current_state("C-CHALLENGE").evidence
        if item.document_id == "DOC-PAYMENT" and item.evidence_type == "payment_record"
    )
    agent.update("C-CHALLENGE", AgentUpdateRequest(verified_evidence_ids=[payment_record.evidence_id]))

    challenged = agent.challenge(
        "C-CHALLENGE",
        CaseChallengeRequest(
            target_id=payment_record.evidence_id,
            target_document_id="DOC-PAYMENT",
            challenge_type="evidence_disputed",
            message="Payment amount needs verification.",
        ),
    )

    assert challenged.state.version == 3
    assert challenged.state.challenges[-1].target_id == payment_record.evidence_id
    assert payment_record.evidence_id not in challenged.state.verified_evidence_ids
    assert any(gap.gap_type == "missing_verification" for gap in challenged.state.evidence_gaps)
    assert challenged.state.reasoning_results[-1].human_review_required
    assert any(event.event_type == "HUMAN_CHALLENGE_RECEIVED" for event in challenged.state.agent_events)


def test_c104_challenge_review_override_what_if_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "c104-human-review.sqlite3"
    agent = new_agent(path)
    initial = agent.start("C-104", c104_start_request()).state
    assert initial.reasoning_results[-1].recommendation.endswith(
        "15 October 2026. Human confirmation is required."
    )
    court_evidence = next(
        item for item in initial.evidence
        if item.document_id == "DOC-001" and item.document_type == "court_order"
    )

    what_if = agent.what_if(
        "C-104",
        CaseWhatIfRequest(excluded_document_ids=["DOC-001"]),
    )
    assert what_if.base_version == 1
    assert what_if.state_persisted is False
    assert not any(
        item.rule_id == "R006" and item.triggered
        for item in what_if.simulated_reasoning.rules_evaluated
    )
    assert agent.memory.get_current_state("C-104").version == 1

    challenged = agent.challenge(
        "C-104",
        CaseChallengeRequest(
            target_id=court_evidence.evidence_id,
            target_document_id="DOC-001",
            challenge_type="hearing_date_disputed",
            message="Please verify the official order against the court docket.",
        ),
    )
    assert challenged.state.version == 2
    assert challenged.state.reasoning_results[-1].human_review_required
    assert any(gap.gap_type == "missing_verification" for gap in challenged.state.evidence_gaps)

    reviewed = agent.review(
        "C-104",
        CaseHumanReviewRequest(
            decision="needs_more_evidence",
            notes="Confirm the date against the court docket.",
        ),
    )
    assert reviewed.state.version == 3
    assert reviewed.state.human_reviews[-1].decision == "needs_more_evidence"

    overridden = agent.override(
        "C-104",
        CaseOverrideRequest(
            recommendation="Use the hearing date confirmed by the assigned judge.",
            reason="The judge confirmed the operative hearing date during human review.",
        ),
    )
    assert overridden.state.version == 4
    assert overridden.state.overrides[-1].previous_recommendation == initial.reasoning_results[-1].recommendation
    assert overridden.state.human_reviews[-1].decision == "overridden"
    assert overridden.state.agent_events[-1].event_type == "HUMAN_OVERRIDE_APPLIED"

    restarted = new_agent(path)
    persisted = restarted.memory.get_current_state("C-104")
    assert persisted.version == 4
    assert persisted.overrides[-1].recommendation == overridden.state.overrides[-1].recommendation
    assert len(persisted.challenges) == 1
    assert any(event.event_type == "HUMAN_REVIEW_RECORDED" for event in persisted.agent_events)
    assert restarted.state_response("C-104").reasoning_summary["effective_recommendation"] == persisted.overrides[-1].recommendation


def test_human_review_override_and_what_if_http_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COURTLENS_SQLITE_PATH", str(tmp_path / "review-http.sqlite3"))
    started = client.post(
        "/api/cases/C-104-HTTP/agent/start",
        json=c104_start_request().model_dump(mode="json"),
    )
    assert started.status_code == 201, started.text

    review = client.post(
        "/api/cases/C-104-HTTP/agent/review",
        json={"decision": "needs_more_evidence", "notes": "Check the docket."},
    )
    assert review.status_code == 200, review.text
    assert review.json()["state"]["version"] == 2

    what_if = client.post(
        "/api/cases/C-104-HTTP/agent/what-if",
        json={"excluded_document_ids": ["DOC-001"]},
    )
    assert what_if.status_code == 200, what_if.text
    assert what_if.json()["state_persisted"] is False
    assert what_if.json()["base_version"] == 2
    assert client.get("/api/cases/C-104-HTTP/state").json()["version"] == 2

    override = client.post(
        "/api/cases/C-104-HTTP/agent/override",
        json={"recommendation": "Use the docket-confirmed date.", "reason": "Human verified."},
    )
    assert override.status_code == 200, override.text
    assert override.json()["state"]["version"] == 3
    assert override.json()["state"]["overrides"][-1]["recommendation"] == "Use the docket-confirmed date."


def test_conflict_resolution_event_and_diff_keep_history(tmp_path: Path) -> None:
    agent = new_agent(tmp_path / "events.sqlite3")
    agent.start(
        "C-EVENTS",
        start_request(
            CaseAnalysisDocumentInput(extracted_document=agreement("DOC-A", 500000)),
            CaseAnalysisDocumentInput(extracted_document=agreement("DOC-B", 400000)),
        ),
    )
    agent.update("C-EVENTS", AgentUpdateRequest(documents=[CaseAnalysisDocumentInput(extracted_document=agreement("DOC-B", 500000))]))
    events = agent.memory.list_events("C-EVENTS")
    diff = agent.diff("C-EVENTS", 1, 2)

    assert any(event.event_type == "CONFLICT_DETECTED" and event.new_version == 1 for event in events)
    assert any(event.event_type == "CONFLICT_RESOLVED" and event.new_version == 2 for event in events)
    assert any(event.previous_version == 1 and event.new_version == 2 for event in events)
    assert len(diff.resolved_conflicts) == 1


def test_case_agent_http_lifecycle_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COURTLENS_SQLITE_PATH", str(tmp_path / "http.sqlite3"))
    initial = client.post(
        "/api/cases/C-HTTP/agent/start",
        json={"case_title": "SME Payment Dispute", "documents": [{"extracted_document": agreement("DOC-HTTP").model_dump(mode="json")}]},
    )
    assert initial.status_code == 201, initial.text
    assert initial.json()["state"]["version"] == 1
    duplicate = client.post("/api/cases/C-HTTP/agent/start", json={})
    assert duplicate.status_code == 409
    assert client.get("/api/cases/C-HTTP/state").status_code == 200
    assert client.get("/api/cases/C-HTTP/versions").status_code == 200
    assert client.get("/api/cases/C-HTTP/events").status_code == 200


def test_update_unknown_case_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="not found"):
        new_agent(tmp_path / "not-found.sqlite3").update("MISSING", AgentUpdateRequest())