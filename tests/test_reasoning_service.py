"""Integration tests for the reasoning-service to symbolic-engine bridge."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.reasoning import router
from backend.app.agents.reasoning.reasoning_service import ReasoningService
from backend.app.agents.reasoning.schemas import ReasoningRequest
from backend.app.rules.rule_engine import RuleEngine


def evidence(evidence_id: str, document_id: str, value: str, confidence: float = 0.95) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": document_id,
        "page_number": 1,
        "fact_type": "hearing_date",
        "value": value,
        "source_quote": f"Hearing date: {value}.",
        "confidence": confidence,
        "evidence_type": "direct_documentary",
    }


def request(**overrides) -> ReasoningRequest:
    data = {
        "case_id": "case-1",
        "analysis_version": 3,
        "question": "What is the listed hearing date?",
        "facts": [
            {
                "fact_id": "F-102",
                "fact_type": "hearing_date",
                "value": "2026-10-15",
                "evidence_ids": ["E-27", "E-31"],
            }
        ],
        "evidence": [
            evidence("E-27", "doc-A", "2026-10-15"),
            evidence("E-31", "doc-B", "2026-10-15"),
        ],
        "conflicts": [],
        "evidence_gaps": [],
        "rules": [],
    }
    data.update(overrides)
    return ReasoningRequest.model_validate(data)


def test_service_invokes_rule_engine_and_returns_grounded_reasoning():
    class CountingRuleEngine(RuleEngine):
        calls = 0

        def evaluate(self, engine_request):
            self.calls += 1
            return super().evaluate(engine_request)

    engine = CountingRuleEngine()
    result = ReasoningService(rule_engine=engine).analyze(request())

    assert engine.calls == 1
    assert result.analysis_version == 3
    assert result.status == "supported"
    assert result.needs_human_review is False
    assert {"R002", "R003"} <= set(result.rules_used)
    assert result.conclusion
    assert result.reasoning_steps
    for step in result.reasoning_steps:
        assert all(reference in {"F-102"} for reference in step.fact_ids)
        assert all(reference in {"E-27", "E-31"} for reference in step.evidence_ids)
        assert all(reference in {"R001", "R002", "R003", "R004", "R005", "R006"} for reference in step.rule_ids)


def test_conflicting_evidence_is_not_selected_and_requires_review():
    data = request(
        facts=[],
        evidence=[
            evidence("E-27", "doc-A", "2026-10-15"),
            evidence("E-31", "doc-B", "2026-10-20"),
        ],
        conflicts=[
            {
                "conflict_id": "C-9",
                "fact_type": "hearing_date",
                "evidence_ids": ["E-27", "E-31"],
                "description": "Two documents list different hearing dates.",
                "severity": "high",
            }
        ],
    )

    result = ReasoningService().analyze(data)

    assert result.status == "conflicting"
    assert result.needs_human_review is True
    assert result.inferences[0].selected_value is None
    assert result.conflicts[0].conflict_id == "C-9"
    r001_steps = [step for step in result.reasoning_steps if "R001" in step.rule_ids]
    assert r001_steps
    assert r001_steps[0].conflict_ids == ["C-9"]
    assert r001_steps[0].evidence_ids == ["E-27", "E-31"]


def test_weak_and_missing_support_is_visible_and_requires_review():
    data = request(
        facts=[],
        evidence=[evidence("E-27", "doc-A", "2026-10-15", confidence=0.4)],
        evidence_gaps=[
            {
                "gap_id": "G-2",
                "fact_type": "hearing_date",
                "description": "No official notice is available.",
                "required_evidence": "Official court notice stating the date.",
            }
        ],
    )

    result = ReasoningService().analyze(data)

    assert result.status == "insufficient_evidence"
    assert result.needs_human_review is True
    assert "R004" in result.rules_used
    assert "R005" in result.rules_used
    assert "Official court notice stating the date." in result.missing_evidence
    assert any(step.evidence_gap_ids == ["G-2"] for step in result.reasoning_steps)


def test_requested_rules_are_restricted_to_registered_ids():
    result = ReasoningService().analyze(request(rules=["R003"]))

    assert result.rules_used == ["R003"]
    assert {item.rule_id for item in result.rule_evaluations} == {
        "R001", "R003", "R004", "R005", "R006"
    }

    with pytest.raises(ValueError, match="unknown rule IDs"):
        ReasoningService().analyze(request(rules=["R999"]))


def test_rule_selection_cannot_disable_conflict_safeguard():
    result = ReasoningService().analyze(
        request(
            facts=[],
            evidence=[
                evidence("E-27", "doc-A", "2026-10-15"),
                evidence("E-31", "doc-B", "2026-10-20"),
            ],
            rules=["R003"],
        )
    )

    assert result.status == "conflicting"
    assert "R001" in result.rules_used
    assert all(assessment.selected_value is None for assessment in result.inferences)


def test_legacy_request_without_new_fields_still_validates():
    legacy = ReasoningRequest.model_validate(
        {
            "case_id": "legacy-case",
            "question": "What is the hearing date?",
            "evidence": [evidence("E-27", "doc-A", "2026-10-15")],
        }
    )

    result = ReasoningService().analyze(legacy)
    assert result.case_id == "legacy-case"
    assert result.analysis_version == 1


def test_existing_reasoning_route_returns_integrated_contract():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(
        "/api/reasoning/analyze",
        json=request().model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_version"] == 3
    assert body["status"] == "supported"
    assert body["rules_used"]
    assert body["reasoning_steps"]
    assert body["needs_human_review"] is False