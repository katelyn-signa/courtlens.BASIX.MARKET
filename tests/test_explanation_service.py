"""Tests for the deterministic lawyer-facing explanation layer."""

import json

from backend.app.agents.reasoning.explanation_service import ExplanationService
from backend.app.agents.reasoning.reasoning_service import ReasoningService
from backend.app.agents.reasoning.schemas import ReasoningRequest


def evidence(evidence_id: str, document_id: str, value: str, confidence: float = 0.95) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": document_id,
        "page_number": 2,
        "fact_type": "hearing_date",
        "value": value,
        "source_quote": f"Hearing date: {value}.",
        "confidence": confidence,
        "evidence_type": "direct_documentary",
    }


def reasoning_result(**overrides):
    data = {
        "case_id": "case-explain",
        "analysis_version": 2,
        "question": "What is the hearing date?",
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
    request = ReasoningRequest.model_validate(data)
    return ReasoningService().analyze(request)


def all_reference_ids(explanation) -> set[str]:
    references = set()
    for collection in (explanation.key_findings, explanation.reasoning):
        for finding in collection:
            references.update(finding.references.fact_ids)
            references.update(finding.references.evidence_ids)
            references.update(finding.references.conflict_ids)
            references.update(finding.references.rule_ids)
            references.update(finding.references.evidence_gap_ids)
    for item in explanation.supporting_evidence:
        references.add(item.evidence_id)
    for conflict in explanation.conflicts:
        references.add(conflict.conflict_id)
        references.update(conflict.evidence_ids)
    for gap in explanation.evidence_gaps:
        references.add(gap.gap_id)
        references.update(gap.references.fact_ids)
        references.update(gap.references.evidence_ids)
        references.update(gap.references.conflict_ids)
        references.update(gap.references.rule_ids)
    for rule in explanation.rules_applied:
        references.add(rule.rule_id)
        references.update(rule.references.fact_ids)
        references.update(rule.references.evidence_ids)
        references.update(rule.references.conflict_ids)
        references.update(rule.references.evidence_gap_ids)
    return references


def input_reference_ids(result) -> set[str]:
    references = {
        fact.fact_id for fact in result.facts_considered if fact.fact_id is not None
    }
    references.update(item.evidence_id for item in result.supporting_evidence)
    references.update(item.evidence_id for item in result.contradicting_evidence)
    references.update(item.conflict_id for item in result.conflicts)
    references.update(result.rules_used)
    for step in result.reasoning_steps:
        references.update(step.fact_ids)
        references.update(step.evidence_ids)
        references.update(step.conflict_ids)
        references.update(step.evidence_gap_ids)
        references.update(step.rule_ids)
    for evaluation in result.rule_evaluations:
        references.update(evaluation.input_fact_ids)
        references.update(evaluation.input_evidence_ids)
        references.update(evaluation.input_conflict_ids)
        references.update(evaluation.input_gap_ids)
    return references


def test_strong_evidence_explanation_preserves_rules_references_and_review():
    result = reasoning_result()
    explanation = ExplanationService().explain(result)

    assert "strong documentary support" in explanation.summary
    assert "R003" in {rule.rule_id for rule in explanation.rules_applied}
    references = all_reference_ids(explanation)
    assert {"F-102", "E-27", "E-31", "R003"} <= references
    assert explanation.human_review.required is result.needs_human_review is False


def test_conflicting_evidence_remains_unresolved_and_review_is_preserved():
    result = reasoning_result(
        facts=[],
        evidence=[
            evidence("E-27", "doc-A", "2026-10-15"),
            evidence("E-31", "doc-B", "2026-10-20"),
        ],
        conflicts=[
            {
                "conflict_id": "C-14",
                "fact_type": "hearing_date",
                "evidence_ids": ["E-27", "E-31"],
                "description": "Two documents report different dates.",
                "severity": "high",
            }
        ],
    )
    explanation = ExplanationService().explain(result)

    assert explanation.conflicts[0].conflict_id == "C-14"
    assert explanation.conflicts[0].competing_values == ["2026-10-15", "2026-10-20"]
    assert "remains unresolved" in explanation.conflicts[0].explanation
    assert "not selected" in explanation.conflicts[0].explanation
    assert explanation.human_review.required is result.needs_human_review is True


def test_consistent_weak_evidence_mentions_r002_without_calling_it_strong():
    result = reasoning_result(
        evidence=[
            evidence("E-27", "doc-A", "2026-10-15", confidence=0.4),
            evidence("E-31", "doc-B", "2026-10-15", confidence=0.5),
        ]
    )
    explanation = ExplanationService().explain(result)

    fired_rule_ids = {item.rule_id for item in explanation.rules_applied}
    assert "R002" in fired_rule_ids
    assert "R003" not in fired_rule_ids
    assert "does not meet the strong-support threshold" in explanation.summary
    assert "strong documentary support" not in explanation.summary


def test_missing_critical_support_reports_r006_gap_and_review():
    result = reasoning_result(
        facts=[],
        evidence=[],
        evidence_gaps=[],
        critical_fact_types=["hearing_date"],
    )
    explanation = ExplanationService().explain(result)

    assert "R006" in {rule.rule_id for rule in explanation.rules_applied}
    assert any("Critical supporting evidence is missing" in item for item in explanation.limitations)
    assert explanation.human_review.required is result.needs_human_review is True


def test_evidence_gap_id_and_description_are_preserved():
    result = reasoning_result(
        facts=[],
        evidence=[evidence("E-27", "doc-A", "2026-10-15", confidence=0.4)],
        evidence_gaps=[
            {
                "gap_id": "G-03",
                "fact_type": "hearing_date",
                "description": "No official notice is available.",
                "required_evidence": "Official court notice stating the date.",
            }
        ],
    )
    explanation = ExplanationService().explain(result)

    gap = explanation.evidence_gaps[0]
    assert gap.gap_id == "G-03"
    assert "No official notice is available." in gap.description
    assert "G-03" in gap.references.evidence_gap_ids
    assert "R005" in {rule.rule_id for rule in explanation.rules_applied}


def test_explanation_references_are_subset_of_reasoning_result_ids():
    result = reasoning_result(
        evidence=[
            evidence("E-27", "doc-A", "2026-10-15"),
            evidence("E-31", "doc-B", "2026-10-20"),
        ],
        conflicts=[
            {
                "conflict_id": "C-14",
                "fact_type": "hearing_date",
                "evidence_ids": ["E-27", "E-31"],
                "description": "Two documents report different dates.",
                "severity": "high",
            }
        ],
    )
    explanation = ExplanationService().explain(result)

    assert all_reference_ids(explanation) <= input_reference_ids(result)


def test_explanation_is_deterministic_for_identical_result():
    result = reasoning_result()
    service = ExplanationService()

    first = service.explain(result).model_dump(mode="json")
    second = service.explain(result).model_dump(mode="json")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_result_without_conflicts_or_gaps_is_explicit_and_clean():
    explanation = ExplanationService().explain(reasoning_result())

    assert explanation.conflicts == []
    assert explanation.conflict_note == "No material conflicts are recorded in the current reasoning result."
    assert explanation.evidence_gaps == []