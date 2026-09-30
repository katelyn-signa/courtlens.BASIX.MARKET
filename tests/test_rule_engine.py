"""Focused tests for deterministic and auditable symbolic rules."""

import json

import pytest

from backend.app.rules.rule_engine import RuleEngine
from backend.app.rules.schemas import RuleEngineRequest


def evidence(
    evidence_id: str,
    document_id: str,
    value: str,
    *,
    confidence: float = 0.95,
    evidence_type: str = "direct_documentary",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": document_id,
        "page_number": 1,
        "fact_type": "hearing_date",
        "value": value,
        "source_quote": f"The hearing is listed for {value}.",
        "confidence": confidence,
        "evidence_type": evidence_type,
    }


def analyze(**overrides):
    request_data = {
        "facts": [],
        "evidence": [evidence("E1", "doc_A", "2026-10-15")],
        "conflicts": [],
        "evidence_gaps": [],
        "critical_fact_types": [],
    }
    request_data.update(overrides)
    request = RuleEngineRequest.model_validate(request_data)
    return RuleEngine().evaluate(request)


def test_strong_direct_support_fires_deterministic_rules():
    result = analyze()

    assessment = result.assessments[0]
    assert assessment.status == "strongly_supported"
    assert assessment.selected_value == "2026-10-15"
    assert {"R003"} <= set(assessment.rule_ids)
    assert len(result.rules_evaluated) == 6
    assert all(item.rule_id for item in result.rules_evaluated)


def test_consistent_independent_documents_are_supported():
    result = analyze(
        evidence=[
            evidence("E1", "doc_A", "2026-10-15"),
            evidence("E2", "doc_B", "2026-10-15"),
        ]
    )

    assert result.assessments[0].status == "strongly_supported"
    assert "R002" in result.assessments[0].rule_ids
    r002 = next(item for item in result.rules_evaluated if item.rule_id == "R002")
    assert r002.input_evidence_ids == ["E1", "E2"]


def test_conflicting_values_retain_supplied_conflict_and_evidence_ids():
    conflict = {
        "conflict_id": "C1",
        "fact_type": "hearing_date",
        "evidence_ids": ["E1", "E2"],
        "description": "Two documents give different dates.",
        "severity": "high",
    }
    result = analyze(
        evidence=[
            evidence("E1", "doc_A", "2026-10-15"),
            evidence("E2", "doc_B", "2026-10-20"),
        ],
        conflicts=[conflict],
    )

    assert result.assessments[0].status == "conflicting"
    assert result.assessments[0].selected_value is None
    assert result.assessments[0].conflict_ids == ["C1"]
    r001 = next(item for item in result.rules_evaluated if item.rule_id == "R001")
    assert r001.input_conflict_ids == ["C1"]
    assert r001.input_evidence_ids == ["E1", "E2"]
    assert "C1" in r001.explanation


def test_detected_disagreement_does_not_invent_conflict_ids():
    result = analyze(
        evidence=[
            evidence("E1", "doc_A", "2026-10-15"),
            evidence("E2", "doc_B", "2026-10-20"),
        ]
    )

    r001 = next(item for item in result.rules_evaluated if item.rule_id == "R001")
    assert r001.fired
    assert r001.input_conflict_ids == []
    assert r001.input_evidence_ids == ["E1", "E2"]
    assert result.conflicts == []


def test_low_confidence_or_indirect_evidence_is_uncertain():
    result = analyze(
        evidence=[
            evidence("E1", "doc_A", "2026-10-15", confidence=0.4, evidence_type="indirect")
        ]
    )

    assert result.assessments[0].status == "uncertain"
    assert "R004" in result.assessments[0].rule_ids
    assert any("does not meet" in item for item in result.uncertainties)


def test_consistency_does_not_turn_low_confidence_evidence_into_strong_support():
    result = analyze(
        evidence=[
            evidence("E1", "doc_A", "2026-10-15", confidence=0.4),
            evidence("E2", "doc_B", "2026-10-15", confidence=0.5),
        ]
    )

    assert "R002" in result.assessments[0].rule_ids
    assert "R003" not in result.assessments[0].rule_ids
    assert result.assessments[0].status == "uncertain"
    assert result.assessments[0].selected_value is None


def test_explicit_evidence_gap_preserves_gap_id_and_requirement():
    gap = {
        "gap_id": "G1",
        "fact_type": "hearing_date",
        "description": "No official notice was supplied.",
        "required_evidence": "Official court hearing notice identifying the date.",
    }
    result = analyze(evidence=[], evidence_gaps=[gap])

    assert result.assessments[0].status == "insufficient_evidence"
    assert "Official court hearing notice identifying the date." in result.missing_evidence
    r005 = next(item for item in result.rules_evaluated if item.rule_id == "R005")
    assert r005.input_gap_ids == ["G1"]
    assert r005.fired


def test_missing_critical_fact_is_reported_without_fabricated_ids():
    result = analyze(evidence=[], critical_fact_types=["hearing_date"])

    assert result.assessments[0].status == "insufficient_evidence"
    r006 = next(item for item in result.rules_evaluated if item.rule_id == "R006")
    assert r006.fired
    assert r006.input_fact_ids == []
    assert r006.input_evidence_ids == []
    assert r006.input_conflict_ids == []
    assert result.missing_evidence


def test_unlinked_fact_does_not_count_as_support_for_critical_conclusion():
    result = analyze(
        facts=[{"fact_id": "F1", "fact_type": "hearing_date", "value": "2026-10-15"}],
        evidence=[],
        critical_fact_types=["hearing_date"],
    )

    r006 = next(item for item in result.rules_evaluated if item.rule_id == "R006")
    assert r006.fired
    assert r006.input_fact_ids == ["F1"]
    assert result.assessments[0].status == "insufficient_evidence"


def test_fact_and_conflict_references_are_validated():
    with pytest.raises(ValueError, match="unknown evidence"):
        RuleEngineRequest.model_validate(
            {
                "facts": [{"fact_id": "F1", "fact_type": "hearing_date", "value": "date", "evidence_ids": ["E404"]}],
                "evidence": [],
            }
        )


def test_identical_input_produces_deterministic_json_serializable_results():
    request = RuleEngineRequest.model_validate(
        {
            "facts": [{"fact_id": "F1", "fact_type": "hearing_date", "value": "2026-10-15", "evidence_ids": ["E1"]}],
            "evidence": [evidence("E1", "doc_A", "2026-10-15")],
            "critical_fact_types": ["hearing_date"],
        }
    )
    engine = RuleEngine()

    first = engine.evaluate(request).model_dump(mode="json")
    second = engine.evaluate(request).model_dump(mode="json")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
