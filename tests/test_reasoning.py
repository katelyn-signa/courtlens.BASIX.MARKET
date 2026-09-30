import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.reasoning_agent import reason_case
from app.main import app
from app.schemas.analysis import AnalysisSummary, CaseAnalysisResult
from app.schemas.case import CaseIntakeRequest
from app.schemas.conflict import Conflict, ConflictingValue
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact
from app.services.case_analysis_service import analyze_case
from app.services.case_intake_service import assemble_case

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def make_fact(
    fact_id: str,
    field: str,
    fact_type: str,
    value: str,
    normalized_value: str | int | float,
    document_id: str,
    *,
    page: int = 1,
    currency: str | None = None,
) -> ExtractedFact:
    return ExtractedFact(
        fact_id=fact_id,
        fact_type=fact_type,
        field=field,
        value=value,
        normalized_value=normalized_value,
        document_id=document_id,
        page=page,
        quote=f"{field.replace('_', ' ').title()}: {value}",
        confidence=0.98,
        currency=currency,
        extraction_method="text",
    )


def make_evidence(
    evidence_id: str,
    fact: ExtractedFact,
    evidence_type: str,
) -> Evidence:
    document_type = "payment_record" if evidence_type == "payment_record" else "contract"
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        document_id=fact.document_id,
        document_type=document_type,
        page=fact.page,
        quote=fact.quote,
        normalized_value=fact.normalized_value,
        fact_id=fact.fact_id,
        confidence=fact.confidence,
        extraction_method=fact.extraction_method,
    )


def make_claim(
    text: str,
    *,
    claim_id: str = "CL-001",
    document_id: str = "DOC-CLAIM",
    page: int = 1,
    claim_type: str = "payment_claim",
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        claimant="Buyer",
        claim_type=claim_type,
        claim_text=text,
        normalized_claim=text,
        document_id=document_id,
        document_type="claim_statement",
        page=page,
        quote=text,
        confidence=0.92,
    )


def make_conflict() -> Conflict:
    return Conflict(
        conflict_id="C001",
        conflict_type="date_conflict",
        fact_type="date",
        event_type="payment_date",
        description="Conflicting values for payment_date: 2026-08-10, 2026-08-12.",
        severity="high",
        conflicting_values=[
            ConflictingValue(
                value="10 August 2026", normalized_value="2026-08-10", fact_id="F-D1",
                evidence_id="E-D1", document_id="DOC-A", page=1,
                quote="Payment Date: 10 August 2026",
            ),
            ConflictingValue(
                value="12 August 2026", normalized_value="2026-08-12", fact_id="F-D2",
                evidence_id="E-D2", document_id="DOC-B", page=2,
                quote="Payment Date: 12 August 2026",
            ),
        ],
        evidence_ids=["E-D1", "E-D2"],
        document_ids=["DOC-A", "DOC-B"],
        source_pages=[1, 2],
        quotes=["Payment Date: 10 August 2026", "Payment Date: 12 August 2026"],
        confidence=0.96,
    )


def make_gap() -> EvidenceGap:
    return EvidenceGap(
        gap_id="G001",
        gap_type="missing_payment_proof",
        description="Payment proof is missing for the full-payment claim.",
        importance="high",
        related_claim_ids=["CL-001"],
        related_document_ids=["DOC-CLAIM"],
        source_pages=[1],
        quotes=["Buyer has paid the full amount."],
        reason="No verified payment record was supplied.",
        confidence=0.94,
    )


def make_case_analysis(
    *,
    facts: list[ExtractedFact] | None = None,
    evidence: list[Evidence] | None = None,
    claims: list[ExtractedClaim] | None = None,
    conflicts: list[Conflict] | None = None,
    gaps: list[EvidenceGap] | None = None,
    verified_evidence_ids: list[str] | None = None,
) -> CaseAnalysisResult:
    facts = facts or []
    evidence = evidence or []
    claims = claims or []
    conflicts = conflicts or []
    gaps = gaps or []
    intake = assemble_case(
        CaseIntakeRequest(
            case_id="C-REASONING",
            facts=facts,
            evidence=evidence,
            claims=claims,
            conflicts=conflicts,
            gaps=gaps,
        )
    )
    summary = AnalysisSummary(
        document_count=intake.counts.document_count,
        fact_count=len(facts),
        evidence_count=len(evidence),
        claim_count=len(claims),
        conflict_count=len(conflicts),
        evidence_gap_count=len(gaps),
        high_severity_conflict_count=sum(item.severity == "high" for item in conflicts),
        review_signal="no_review_signal",
    )
    return CaseAnalysisResult(
        case_intake=intake,
        documents=[],
        facts=facts,
        evidence=evidence,
        claims=claims,
        conflicts=conflicts,
        evidence_gaps=gaps,
        analysis_summary=summary,
        verified_evidence_ids=verified_evidence_ids or [],
    )


def verified_payment_case(
    *,
    obligation: int = 500000,
    paid: int = 200000,
    claim_text: str = "Buyer has paid the full amount.",
) -> CaseAnalysisResult:
    obligation_fact = make_fact(
        "F-OBLIGATION", "contract_amount", "financial", f"INR {obligation}",
        obligation, "DOC-CONTRACT", currency="INR",
    )
    paid_fact = make_fact(
        "F-PAID", "amount_paid", "financial", f"INR {paid}",
        paid, "DOC-PAYMENT", currency="INR",
    )
    obligation_evidence = make_evidence("E-OBLIGATION", obligation_fact, "contract_term")
    payment_evidence = make_evidence("E-PAYMENT", paid_fact, "payment_record")
    claim = make_claim(claim_text)
    return make_case_analysis(
        facts=[obligation_fact, paid_fact],
        evidence=[obligation_evidence, payment_evidence],
        claims=[claim],
        verified_evidence_ids=[payment_evidence.evidence_id],
    )


def test_payment_gap_rule_triggers_with_verified_payment_evidence() -> None:
    result = reason_case(verified_payment_case())

    evaluation = next(item for item in result.rules_evaluated if item.rule_id == "R001")
    assert evaluation.triggered
    assert set(evaluation.evidence_ids) == {"E-OBLIGATION", "E-PAYMENT"}
    assert result.recommendation in {
        "Payment evidence conflict requires human verification.",
        "Potential payment shortfall identified.",
    }


def test_payment_gap_calculation_is_correct() -> None:
    result = reason_case(verified_payment_case(obligation=500000, paid=200000))
    evaluation = next(item for item in result.rules_evaluated if item.rule_id == "R001")

    assert evaluation.result == {
        "obligation_amount": 500000,
        "recorded_payment": 200000,
        "potential_shortfall": 300000,
        "currency": "INR",
    }


def test_unselected_payment_evidence_never_triggers_verified_payment_rule() -> None:
    case = verified_payment_case().model_copy(update={"verified_evidence_ids": []})

    result = reason_case(case)

    payment_gap = next(item for item in result.rules_evaluated if item.rule_id == "R001")
    assert not payment_gap.triggered
    assert "not available" in payment_gap.explanation


def test_payment_claim_conflict_triggers_against_verified_partial_payment() -> None:
    result = reason_case(verified_payment_case())

    evaluation = next(item for item in result.rules_evaluated if item.rule_id == "R002")
    assert evaluation.triggered
    assert "does not support" in evaluation.explanation
    assert "E-PAYMENT" in evaluation.evidence_ids
    assert result.human_review_required


def test_date_conflict_rule_uses_structured_event_and_provenance() -> None:
    result = reason_case(make_case_analysis(conflicts=[make_conflict()]))

    evaluation = next(item for item in result.rules_evaluated if item.rule_id == "R003")
    assert evaluation.triggered
    assert evaluation.result["event_type"] == "payment_date"
    assert set(evaluation.evidence_ids) == {"E-D1", "E-D2"}


def test_evidence_gap_rule_triggers() -> None:
    result = reason_case(make_case_analysis(gaps=[make_gap()]))

    evaluation = next(item for item in result.rules_evaluated if item.rule_id == "R004")
    assert evaluation.triggered
    assert evaluation.result["gap_ids"] == ["G001"]


def test_human_review_required_for_high_conflict_and_evidence_gap() -> None:
    for case in (
        make_case_analysis(conflicts=[make_conflict()]),
        make_case_analysis(gaps=[make_gap()]),
    ):
        result = reason_case(case)
        review_rule = next(item for item in result.rules_evaluated if item.rule_id == "R005")
        assert review_rule.triggered
        assert result.human_review_required
        assert result.reasoning_steps[-1].step_type == "human_review_required"


def test_rule_explanations_and_ids_are_deterministic() -> None:
    case = verified_payment_case()
    first = reason_case(case)
    second = reason_case(case)

    assert [(item.rule_id, item.rule_name, item.explanation) for item in first.rules_evaluated] == [
        (item.rule_id, item.rule_name, item.explanation) for item in second.rules_evaluated
    ]
    assert [item.rule_id for item in first.rules_evaluated] == [
        "R001", "R002", "R003", "R004", "R005"
    ]


def test_evidence_and_document_page_provenance_are_preserved() -> None:
    result = reason_case(verified_payment_case())

    references = {item.evidence_id: item for item in result.evidence_used}
    payment_reference = references["E-PAYMENT"]
    assert payment_reference.document_id == "DOC-PAYMENT"
    assert payment_reference.page == 1
    assert payment_reference.quote == "Amount Paid: INR 200000"
    assert payment_reference.relevance == 0.98


def test_reasoning_trace_is_ordered_and_links_rules_and_evidence() -> None:
    result = reason_case(verified_payment_case())
    step_types = [step.step_type for step in result.reasoning_steps]

    assert step_types.index("evidence_observed") < step_types.index("rule_evaluated")
    assert step_types.index("rule_evaluated") < step_types.index("rule_triggered")
    assert step_types.index("recommendation_generated") < step_types.index("human_review_required")
    assert any("E-PAYMENT" in step.evidence_ids for step in result.reasoning_steps)
    assert any("R001" in step.rule_ids for step in result.reasoning_steps)


def test_confidence_category_and_score_are_deterministic() -> None:
    case = verified_payment_case()
    first = reason_case(case)
    second = reason_case(case)

    assert first.confidence == second.confidence == "medium"
    assert first.evidence_support_score == second.evidence_support_score
    assert 0 <= first.evidence_support_score <= 1


def test_reasoning_does_not_generate_legal_conclusion() -> None:
    result = reason_case(verified_payment_case())
    prohibited = ("legally liable", "buyer is lying", "court should rule", "seller will win")
    combined_text = " ".join(
        [result.recommendation]
        + [step.description for step in result.reasoning_steps]
        + [item.explanation for item in result.rules_evaluated]
    ).casefold()

    assert all(phrase not in combined_text for phrase in prohibited)
    assert "Potential payment shortfall identified." in result.recommendation or "human verification" in result.recommendation


def test_api_accepts_case_analysis_result() -> None:
    case = verified_payment_case()
    response = client.post("/api/cases/reason", json=case.model_dump(mode="json"))

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reasoning_id"]
    assert result["rules_evaluated"]
    assert result["reasoning_steps"]
    assert result["recommendation"]
    assert result["confidence"] in {"low", "medium", "high"}
    assert result["human_review_required"] is True


def test_api_rejects_invalid_case_analysis() -> None:
    response = client.post("/api/cases/reason", json={"facts": []})

    assert response.status_code == 422


def test_phase10_synthetic_pdf_runs_through_reasoning_agent() -> None:
    encoded = base64.b64encode(SAMPLE_PDF.read_bytes()).decode("ascii")
    from app.schemas.analysis import CaseAnalysisDocumentInput, CaseAnalysisRequest
    from app.services.case_analysis_service import analyze_case

    phase10_result = analyze_case(
        CaseAnalysisRequest(
            case_id="C-104",
            case_title="SME Payment Dispute",
            documents=[
                CaseAnalysisDocumentInput(
                    filename=SAMPLE_PDF.name,
                    document_id="DOC-SYNTHETIC",
                    content_base64=encoded,
                )
            ],
        )
    )
    result = reason_case(phase10_result)

    assert phase10_result.documents[0].classification.document_type == "contract"
    assert any(item.field == "contract_amount" for item in phase10_result.facts)
    assert phase10_result.evidence
    assert result.reasoning_id
    assert result.rules_evaluated
    assert result.semantic_observations
    assert all(ref.document_id == "DOC-SYNTHETIC" for ref in result.evidence_used)
    assert not next(item for item in result.rules_evaluated if item.rule_id == "R001").triggered


def test_verified_evidence_ids_must_reference_payment_record() -> None:
    case = verified_payment_case()
    with pytest.raises(ValueError, match="payment_record"):
        CaseAnalysisResult.model_validate(
            case.model_dump(mode="python") | {"verified_evidence_ids": ["E-OBLIGATION"]}
        )


def test_no_mechanical_assumption_that_unverified_records_are_verified() -> None:
    case = verified_payment_case().model_copy(update={"verified_evidence_ids": []})

    result = reason_case(case)

    payment_observations = [
        item for item in result.semantic_observations if item.observation_type == "payment_record"
    ]
    assert payment_observations
    assert all(not item.source_supported for item in payment_observations)