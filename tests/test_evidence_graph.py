from fastapi.testclient import TestClient

from app.agents.case_agent import CaseAgent
from app.database import SQLiteDatabase
from app.main import app
from app.schemas.agent_state import AgentStartRequest
from app.schemas.analysis import CaseAnalysisDocumentInput
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.services.case_memory_service import CaseMemoryService
from app.services.evidence_graph_service import build_evidence_graph

client = TestClient(app)


def c104_request() -> AgentStartRequest:
    demo_documents = (
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
    )
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
            for document_id, source_type, text in demo_documents
        ],
    )


def test_evidence_graph_links_c104_nodes_and_preserves_provenance(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "graph.sqlite3"
    monkeypatch.setenv("COURTLENS_SQLITE_PATH", str(database_path))
    state = CaseAgent(CaseMemoryService(SQLiteDatabase(database_path))).start(
        "C-104", c104_request()
    ).state

    graph = build_evidence_graph(state)
    nodes = {node.node_id: node for node in graph.nodes}
    edges = {(edge.source_id, edge.target_id, edge.relationship) for edge in graph.edges}
    court_fact = next(
        fact for fact in state.facts
        if fact.document_id == "DOC-001" and fact.field == "hearing_date"
    )
    court_evidence = next(
        evidence for evidence in state.evidence
        if evidence.document_id == "DOC-001" and evidence.fact_id == court_fact.fact_id
    )
    fact_node_id = f"fact:DOC-001:{court_fact.fact_id}"
    evidence_node_id = f"evidence:DOC-001:{court_evidence.evidence_id}"
    conflict_node_id = f"conflict:{state.conflicts[0].conflict_id}"
    reasoning = state.reasoning_results[-1]
    recommendation_node_id = f"recommendation:{reasoning.reasoning_id}"

    assert graph.case_id == "C-104"
    assert ("document:DOC-001", fact_node_id, "contains_fact") in edges
    assert (fact_node_id, evidence_node_id, "supports_evidence") in edges
    assert any(
        source == evidence_node_id and target == conflict_node_id
        and relationship == "participates_in_conflict"
        for source, target, relationship in edges
    )
    assert (conflict_node_id, "rule:R003", "evaluated_by") in edges
    assert ("rule:R003", recommendation_node_id, "informs_recommendation") in edges
    assert nodes[fact_node_id].provenance == {
        "document_id": "DOC-001",
        "page": 1,
        "quote": court_fact.quote,
        "confidence": court_fact.confidence,
        "extraction_method": "text",
    }
    assert nodes[evidence_node_id].provenance["normalized_value"] == "2026-10-15"
    assert nodes[conflict_node_id].provenance["document_ids"] == ["DOC-001", "DOC-002"]
    assert nodes[recommendation_node_id].attributes["human_review_required"] is True

    response = client.get("/api/cases/C-104/evidence-graph")
    assert response.status_code == 200, response.text
    assert response.json()["version"] == graph.version