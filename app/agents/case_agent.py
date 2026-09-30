import base64
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.reasoning_agent import reason_case
from app.database import SQLiteDatabase
from app.schemas.agent_state import (
    AgentOperationResult,
    AgentStartRequest,
    AgentUpdateRequest,
    CaseAgentState,
    CaseChallenge,
    CaseChallengeRequest,
    CaseCounts,
    CaseEventsResponse,
    CaseHumanReview,
    CaseHumanReviewRequest,
    CaseOverride,
    CaseOverrideRequest,
    CaseStateDiff,
    CaseStateResponse,
    CaseVersionResponse,
    CaseVersionsResponse,
    CaseWhatIfRequest,
    CaseWhatIfResponse,
)
from app.schemas.analysis import (
    AnalysisSummary,
    CaseAnalysisDocumentInput,
    CaseAnalysisRequest,
    CaseAnalysisResult,
)
from app.schemas.case import CaseDocumentReference, CaseIntakeRequest, CaseMetadata
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.reasoning import ReasoningResult
from app.services.case_analysis_service import analyze_case
from app.services.case_intake_service import assemble_case
from app.services.case_memory_service import (
    CaseAlreadyExistsError,
    CaseMemoryService,
    CaseNotFoundError,
    CaseVersionNotFoundError,
)
from app.services.conflict_detection_service import detect_conflicts
from app.services.evidence_gap_service import detect_evidence_gaps

PAYMENT_FIELDS = {
    "contract_amount",
    "total_contract_amount",
    "total_amount",
    "amount_due",
    "amount_paid",
    "payment_amount",
}
DATE_FIELDS = {
    "contract_date",
    "effective_date",
    "delivery_date",
    "payment_due_date",
    "due_date",
    "payment_date",
    "invoice_date",
    "order_date",
    "hearing_date",
}


def _model_json(value: Any) -> str:
    return value.model_dump_json(exclude_none=False)


def _fingerprint(document_input: CaseAnalysisDocumentInput) -> str:
    if document_input.content_base64 is not None:
        try:
            raw = base64.b64decode(document_input.content_base64, validate=True)
        except ValueError:
            raw = document_input.content_base64.encode("utf-8")
    else:
        raw = (document_input.extracted_document.model_dump_json() if document_input.extracted_document else "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identified_documents(
    documents: list[CaseAnalysisDocumentInput],
) -> list[CaseAnalysisDocumentInput]:
    identified = []
    for item in documents:
        if item.document_id:
            identified.append(item)
        elif item.extracted_document is not None:
            identified.append(item.model_copy(update={"document_id": item.extracted_document.document_id}))
        else:
            identified.append(item.model_copy(update={"document_id": str(uuid4())}))
    return identified


def _case_analysis_from_state(state: CaseAgentState) -> CaseAnalysisResult:
    intake = assemble_case(
        CaseIntakeRequest(
            case_id=state.case_id,
            case_title=state.metadata.case_title,
            case_type=state.metadata.case_type,
            parties=state.metadata.parties,
            created_at=state.metadata.created_at,
            source=state.metadata.source,
            documents=state.documents,
            facts=state.facts,
            evidence=state.evidence,
            claims=state.claims,
            conflicts=state.conflicts,
            gaps=state.evidence_gaps,
        )
    )
    review_signal = (
        "conflicts_require_attention"
        if any(item.severity == "high" for item in state.conflicts)
        else "evidence_gaps_require_attention"
        if state.evidence_gaps
        else "review_recommended"
        if state.conflicts or any(item.status == "unverified" for item in state.claims)
        else "no_review_signal"
    )
    summary = AnalysisSummary(
        document_count=len(state.documents),
        fact_count=len(state.facts),
        evidence_count=len(state.evidence),
        claim_count=len(state.claims),
        conflict_count=len(state.conflicts),
        evidence_gap_count=len(state.evidence_gaps),
        high_severity_conflict_count=sum(item.severity == "high" for item in state.conflicts),
        review_signal=review_signal,
    )
    return CaseAnalysisResult(
        case_intake=intake,
        documents=state.document_analyses,
        facts=state.facts,
        evidence=state.evidence,
        claims=state.claims,
        conflicts=state.conflicts,
        evidence_gaps=state.evidence_gaps,
        analysis_summary=summary,
        verified_evidence_ids=state.verified_evidence_ids,
        challenged_evidence_ids=[
            item for item in state.challenged_ids
            if any(evidence.evidence_id == item for evidence in state.evidence)
        ],
    )


def _state_from_analysis(
    analysis: CaseAnalysisResult,
    *,
    verified_evidence_ids: list[str],
    fingerprints: dict[str, str],
    challenges: list[CaseChallenge] | None = None,
) -> CaseAgentState:
    metadata = analysis.case_intake.case.metadata
    return CaseAgentState(
        case_id=metadata.case_id,
        version=1,
        metadata=metadata,
        documents=analysis.case_intake.case.documents,
        document_analyses=analysis.documents,
        document_fingerprints=fingerprints,
        facts=analysis.facts,
        evidence=analysis.evidence,
        claims=analysis.claims,
        conflicts=analysis.conflicts,
        evidence_gaps=analysis.evidence_gaps,
        reasoning_results=[],
        rules_triggered=[],
        unresolved_questions=[],
        verified_evidence_ids=verified_evidence_ids,
        challenges=challenges or [],
        challenged_ids=[challenge.target_id for challenge in challenges or []],
    )


def _analysis_change_events(analysis: CaseAnalysisResult, source: str) -> list[dict]:
    events = []
    for document in analysis.documents:
        events.append(
            {
                "event_type": "DOCUMENT_ADDED",
                "description": (
                    f"Document '{document.filename}' was analyzed."
                    if document.status == "processed"
                    else f"Document '{document.filename}' was submitted but failed analysis: {document.error.message if document.error else 'unknown error'}"
                ),
                "affected_ids": [document.document_id],
                "source": source,
            }
        )
    if analysis.facts:
        events.append({
            "event_type": "FACTS_EXTRACTED",
            "description": f"Extracted {len(analysis.facts)} structured facts.",
            "affected_ids": [item.fact_id for item in analysis.facts],
            "source": source,
        })
    if analysis.evidence:
        events.append({
            "event_type": "EVIDENCE_ADDED",
            "description": f"Added {len(analysis.evidence)} evidence records.",
            "affected_ids": [item.evidence_id for item in analysis.evidence],
            "source": source,
        })
    return events


def _record_key(item: Any) -> tuple[str, str]:
    return (getattr(item, "document_id", "") or "", getattr(item, "fact_id", None) or getattr(item, "evidence_id", None) or getattr(item, "claim_id", None) or "")


def _merge_records(existing: list, incoming: list) -> tuple[list, list[str], list[str]]:
    records = list(existing)
    positions = {_record_key(item): index for index, item in enumerate(records)}
    added = []
    changed = []
    for item in incoming:
        key = _record_key(item)
        if key not in positions:
            positions[key] = len(records)
            records.append(item)
            added.append(key[1])
            continue
        index = positions[key]
        if _model_json(records[index]) != _model_json(item):
            records[index] = item
            changed.append(key[1])
    return records, added, changed


def _conflict_signature(item) -> tuple:
    return (
        item.conflict_type,
        item.fact_type,
        item.event_type,
        tuple(sorted(item.document_ids)),
        tuple(sorted((
            source.document_id,
            str(source.normalized_value),
            source.quote,
        ) for source in item.conflicting_values)),
        tuple(sorted(item.claim_ids)),
    )


def _gap_signature(item) -> tuple:
    return (
        item.gap_type,
        tuple(sorted(item.related_claim_ids)),
        tuple(sorted(item.related_conflict_ids)),
        tuple(sorted(item.related_document_ids)),
        tuple(sorted(item.related_evidence_ids)),
    )


def _preserve_conflict_ids(previous: list, current: list) -> list:
    old_by_signature = {_conflict_signature(item): item for item in previous}
    used_ids = {item.conflict_id for item in previous}
    next_number = 1
    merged = []
    for item in current:
        old = old_by_signature.get(_conflict_signature(item))
        if old is not None:
            merged.append(item.model_copy(update={"conflict_id": old.conflict_id}))
            continue
        while f"C{next_number:03d}" in used_ids:
            next_number += 1
        new_id = f"C{next_number:03d}"
        used_ids.add(new_id)
        next_number += 1
        merged.append(item.model_copy(update={"conflict_id": new_id}))
    return merged


def _preserve_gap_ids(previous: list, current: list) -> list:
    old_by_signature = {_gap_signature(item): item for item in previous}
    used_ids = {item.gap_id for item in previous}
    next_number = 1
    merged = []
    for item in current:
        old = old_by_signature.get(_gap_signature(item))
        if old is not None:
            merged.append(item.model_copy(update={"gap_id": old.gap_id}))
            continue
        while f"G{next_number:03d}" in used_ids:
            next_number += 1
        new_id = f"G{next_number:03d}"
        used_ids.add(new_id)
        next_number += 1
        merged.append(item.model_copy(update={"gap_id": new_id}))
    return merged


def _changes(previous: CaseAgentState, current: CaseAgentState) -> dict[str, list[str]]:
    old_documents = {item.document_id: item for item in previous.documents}
    new_documents = {item.document_id: item for item in current.documents}
    old_facts = {_record_key(item): item for item in previous.facts}
    new_facts = {_record_key(item): item for item in current.facts}
    old_evidence = {_record_key(item): item for item in previous.evidence}
    new_evidence = {_record_key(item): item for item in current.evidence}
    old_claims = {_record_key(item): item for item in previous.claims}
    new_claims = {_record_key(item): item for item in current.claims}
    old_conflicts = {item.conflict_id: item for item in previous.conflicts}
    new_conflicts = {item.conflict_id: item for item in current.conflicts}
    old_gaps = {item.gap_id: item for item in previous.evidence_gaps}
    new_gaps = {item.gap_id: item for item in current.evidence_gaps}
    return {
        "added_documents": sorted(set(new_documents) - set(old_documents)),
        "removed_documents": sorted(set(old_documents) - set(new_documents)),
        "changed_documents": sorted(
            key for key in set(old_documents) & set(new_documents)
            if _model_json(old_documents[key]) != _model_json(new_documents[key])
            or previous.document_fingerprints.get(key) != current.document_fingerprints.get(key)
        ),
        "added_facts": sorted(new_facts[key].fact_id for key in set(new_facts) - set(old_facts)),
        "changed_facts": sorted(
            new_facts[key].fact_id
            for key in set(old_facts) & set(new_facts)
            if _model_json(old_facts[key]) != _model_json(new_facts[key])
        ),
        "added_evidence": sorted(new_evidence[key].evidence_id for key in set(new_evidence) - set(old_evidence)),
        "changed_evidence": sorted(
            new_evidence[key].evidence_id
            for key in set(old_evidence) & set(new_evidence)
            if _model_json(old_evidence[key]) != _model_json(new_evidence[key])
        ),
        "added_claims": sorted(new_claims[key].claim_id for key in set(new_claims) - set(old_claims)),
        "changed_claims": sorted(
            new_claims[key].claim_id
            for key in set(old_claims) & set(new_claims)
            if _model_json(old_claims[key]) != _model_json(new_claims[key])
        ),
        "new_conflicts": sorted(set(new_conflicts) - set(old_conflicts)),
        "resolved_conflicts": sorted(set(old_conflicts) - set(new_conflicts)),
        "new_gaps": sorted(set(new_gaps) - set(old_gaps)),
        "resolved_gaps": sorted(set(old_gaps) - set(new_gaps)),
        "verification_changes": sorted(
            set(previous.verified_evidence_ids) ^ set(current.verified_evidence_ids)
        ),
        "human_review_changes": sorted(
            {item.review_id for item in current.human_reviews}
            - {item.review_id for item in previous.human_reviews}
        ),
        "override_changes": sorted(
            {item.override_id for item in current.overrides}
            - {item.override_id for item in previous.overrides}
        ),
        "reasoning_changes": [],
    }


def _ensure_document_references(
    documents: list[CaseDocumentReference],
    facts,
    evidence,
    claims,
    conflicts,
    gaps,
) -> list[CaseDocumentReference]:
    by_id = {item.document_id: item for item in documents}
    type_by_id = {item.document_id: item.document_type for item in evidence}
    type_by_id.update({item.document_id: item.document_type for item in claims})
    document_ids = [
        fact.document_id for fact in facts if fact.document_id
    ] + [item.document_id for item in evidence] + [
        item.document_id for item in claims
    ] + [
        document_id for conflict in conflicts for document_id in conflict.document_ids
    ] + [
        document_id for gap in gaps for document_id in gap.related_document_ids
    ]
    for document_id in document_ids:
        if document_id not in by_id:
            by_id[document_id] = CaseDocumentReference(
                document_id=document_id,
                document_type=type_by_id.get(document_id),
            )
    return list(by_id.values())


def _affected_rules(
    changes: dict[str, list[str]],
    facts: list,
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
    conflicts: list,
) -> set[str]:
    changed_fact_ids = set(changes["added_facts"] + changes["changed_facts"])
    changed_facts = [item for item in facts if item.fact_id in changed_fact_ids]
    fields = {item.field for item in changed_facts}
    rule_ids = set()
    changed_evidence_ids = set(changes["added_evidence"] + changes["changed_evidence"])
    changed_evidence = [item for item in evidence if item.evidence_id in changed_evidence_ids]
    evidence_fact_ids = {item.fact_id for item in changed_evidence if item.fact_id}
    evidence_fields = {item.field for item in facts if item.fact_id in evidence_fact_ids}
    relevant_payment_fields = fields | evidence_fields
    if relevant_payment_fields & PAYMENT_FIELDS or changes["verification_changes"]:
        rule_ids.add("R001")
    if (
        relevant_payment_fields & PAYMENT_FIELDS
        or changes["verification_changes"]
        or changes["added_claims"]
        or changes["changed_claims"]
    ):
        if any(item.claim_type in {"payment_claim", "non_payment_claim"} for item in claims):
            rule_ids.add("R002")
    if fields & DATE_FIELDS or any(item.conflict_type == "date_conflict" for item in conflicts) and (
        changes["new_conflicts"] or changes["resolved_conflicts"]
    ):
        rule_ids.add("R003")
    if changes["new_gaps"] or changes["resolved_gaps"]:
        rule_ids.add("R004")
    if rule_ids or changes["new_conflicts"] or changes["new_gaps"]:
        rule_ids.add("R005")
    return rule_ids


class CaseAgent:
    def __init__(self, memory: CaseMemoryService | None = None) -> None:
        self.memory = memory or CaseMemoryService()

    def start(self, case_id: str, request: AgentStartRequest) -> AgentOperationResult:
        if self.memory.case_exists(case_id):
            raise CaseAlreadyExistsError(
                f"Case '{case_id}' already exists. Use /agent/update instead."
            )
        identified_inputs = _identified_documents(request.documents)
        analysis = analyze_case(
            CaseAnalysisRequest(
                case_id=case_id,
                case_title=request.case_title,
                case_type=request.case_type,
                parties=request.parties,
                documents=identified_inputs,
            )
        )
        if request.verified_evidence_ids:
            analysis = CaseAnalysisResult.model_validate(
                analysis.model_dump(mode="python")
                | {"verified_evidence_ids": request.verified_evidence_ids}
            )
        reasoning = reason_case(analysis)
        state = _state_from_analysis(
            analysis,
            verified_evidence_ids=request.verified_evidence_ids,
            fingerprints={
                item.document_id: _fingerprint(item)
                for item in identified_inputs
                if item.document_id
            },
        )
        state = state.model_copy(update={
            "reasoning_results": [reasoning],
            "rules_triggered": [item.rule_id for item in reasoning.rules_evaluated if item.triggered],
            "unresolved_questions": reasoning.unresolved_questions,
        })
        event_specs = _analysis_change_events(analysis, request.source or "case_agent")
        event_specs.extend(
            {
                "event_type": "CONFLICT_DETECTED",
                "description": "An initial structured conflict was detected.",
                "affected_ids": [item.conflict_id],
                "source": request.source or "case_agent",
            }
            for item in analysis.conflicts
        )
        event_specs.extend(
            {
                "event_type": "EVIDENCE_GAP_DETECTED",
                "description": "An initial evidence gap was detected.",
                "affected_ids": [item.gap_id],
                "source": request.source or "case_agent",
            }
            for item in analysis.evidence_gaps
        )
        event_specs.append({
            "event_type": "REASONING_COMPLETED",
            "description": "Initial deterministic reasoning completed.",
            "affected_ids": [reasoning.reasoning_id],
            "source": request.source or "case_agent",
        })
        event_specs.append({
            "event_type": "CASE_CREATED",
            "description": "Case created with initial structured evidence state.",
            "affected_ids": [case_id],
            "source": request.source or "case_agent",
        })
        saved = self.memory.create_case(
            state,
            change_summary="Initial case state created.",
            source=request.source or "case_agent",
            event_specs=event_specs,
        )
        return AgentOperationResult(
            state=saved,
            changes={
                "added_documents": [item.document_id for item in saved.documents],
                "added_facts": [item.fact_id for item in saved.facts],
                "added_evidence": [item.evidence_id for item in saved.evidence],
                "new_conflicts": [item.conflict_id for item in saved.conflicts],
                "new_gaps": [item.gap_id for item in saved.evidence_gaps],
            },
            affected_evidence_ids=[item.evidence_id for item in saved.evidence],
            affected_rule_ids=[item.rule_id for item in reasoning.rules_evaluated if item.triggered],
            reasoning_recomputed=True,
        )

    def update(self, case_id: str, request: AgentUpdateRequest) -> AgentOperationResult:
        old = self.memory.get_current_state(case_id)
        inputs = _identified_documents(request.documents)
        unique_inputs = []
        fingerprints = dict(old.document_fingerprints)
        replaced_document_ids = set()
        existing_ids = {item.document_id for item in old.documents}
        for document_input in inputs:
            document_id = document_input.document_id
            fingerprint = _fingerprint(document_input)
            previous_fingerprint = fingerprints.get(document_id)
            if previous_fingerprint == fingerprint:
                continue
            if document_id not in existing_ids and fingerprint in fingerprints.values():
                continue
            if document_id in existing_ids:
                replaced_document_ids.add(document_id)
            fingerprints[document_id] = fingerprint
            unique_inputs.append(document_input)

        new_analysis = analyze_case(
            CaseAnalysisRequest(
                case_id=case_id,
                case_title=old.metadata.case_title,
                case_type=old.metadata.case_type,
                parties=old.metadata.parties,
                documents=unique_inputs,
            )
        ) if unique_inputs else None

        base_facts = [item for item in old.facts if item.document_id not in replaced_document_ids]
        base_evidence = [item for item in old.evidence if item.document_id not in replaced_document_ids]
        base_claims = [item for item in old.claims if item.document_id not in replaced_document_ids]
        base_documents = [item for item in old.documents if item.document_id not in replaced_document_ids]
        base_analyses = [item for item in old.document_analyses if item.document_id not in replaced_document_ids]
        incoming_facts = list(request.facts) + (new_analysis.facts if new_analysis else [])
        incoming_evidence = list(request.evidence) + (new_analysis.evidence if new_analysis else [])
        incoming_claims = list(request.claims) + (new_analysis.claims if new_analysis else [])
        facts, added_fact_ids, changed_fact_ids = _merge_records(base_facts, incoming_facts)
        evidence, added_evidence_ids, changed_evidence_ids = _merge_records(base_evidence, incoming_evidence)
        claims, added_claim_ids, changed_claim_ids = _merge_records(base_claims, incoming_claims)

        incoming_analyses = new_analysis.documents if new_analysis else []
        document_analyses, _, changed_analysis_ids = _merge_records(base_analyses, incoming_analyses)
        incoming_refs = [
            CaseDocumentReference(
                document_id=item.document_id,
                filename=item.filename,
                document_type=item.classification.document_type if item.classification else None,
                source_type="pdf_upload",
                page_count=item.page_count,
            )
            for item in incoming_analyses
        ]
        documents, added_document_ids, changed_document_ids = _merge_records(base_documents, incoming_refs)
        conflicts = _preserve_conflict_ids(
            old.conflicts,
            detect_conflicts(facts, evidence, claims),
        )
        gaps = _preserve_gap_ids(
            old.evidence_gaps,
            detect_evidence_gaps(facts, evidence, claims, conflicts),
        )
        documents = _ensure_document_references(
            documents,
            facts,
            evidence,
            claims,
            conflicts,
            gaps,
        )

        active_payment_ids = {
            item.evidence_id for item in evidence if item.evidence_type == "payment_record"
        }
        invalid_verified_ids = set(request.verified_evidence_ids) - active_payment_ids
        if invalid_verified_ids:
            raise ValueError(
                "Verified evidence IDs must reference supplied payment_record evidence: "
                + ", ".join(sorted(invalid_verified_ids))
            )
        challenged_ids = set(old.challenged_ids)
        verified_ids = (
            set(old.verified_evidence_ids) | set(request.verified_evidence_ids)
        ) & active_payment_ids
        verified_ids -= challenged_ids
        metadata = old.metadata
        case_intake = assemble_case(
            CaseIntakeRequest(
                case_id=case_id,
                case_title=metadata.case_title,
                case_type=metadata.case_type,
                parties=metadata.parties,
                created_at=metadata.created_at,
                source=metadata.source,
                documents=documents,
                facts=facts,
                evidence=evidence,
                claims=claims,
                conflicts=conflicts,
                gaps=gaps,
            )
        )
        summary = _analysis_summary(document_analyses, facts, evidence, claims, conflicts, gaps)
        current_analysis = CaseAnalysisResult(
            case_intake=case_intake,
            documents=document_analyses,
            facts=facts,
            evidence=evidence,
            claims=claims,
            conflicts=conflicts,
            evidence_gaps=gaps,
            analysis_summary=summary,
            verified_evidence_ids=sorted(verified_ids),
            challenged_evidence_ids=sorted(challenged_ids & {item.evidence_id for item in evidence}),
        )
        candidate = CaseAgentState(
            case_id=case_id,
            version=old.version,
            metadata=metadata,
            documents=documents,
            document_analyses=document_analyses,
            document_fingerprints=fingerprints,
            facts=facts,
            evidence=evidence,
            claims=claims,
            conflicts=conflicts,
            evidence_gaps=gaps,
            reasoning_results=old.reasoning_results,
            rules_triggered=old.rules_triggered,
            unresolved_questions=old.unresolved_questions,
            challenges=old.challenges,
            human_reviews=old.human_reviews,
            overrides=old.overrides,
            challenged_ids=sorted(challenged_ids),
            verified_evidence_ids=sorted(verified_ids),
            agent_events=old.agent_events,
        )
        changes = _changes(old, candidate)
        changes["changed_documents"] = sorted(set(changes["changed_documents"] + changed_document_ids + changed_analysis_ids + list(replaced_document_ids)))
        changes["added_facts"] = sorted(set(changes["added_facts"] + added_fact_ids))
        changes["changed_facts"] = sorted(set(changes["changed_facts"] + changed_fact_ids))
        changes["added_evidence"] = sorted(set(changes["added_evidence"] + added_evidence_ids))
        changes["changed_evidence"] = sorted(set(changes["changed_evidence"] + changed_evidence_ids))
        changes["added_claims"] = sorted(added_claim_ids)
        changes["changed_claims"] = sorted(changed_claim_ids)
        meaningful = any(changes[key] for key in changes if key != "reasoning_changes")
        affected_evidence_ids = sorted(set(changes["added_evidence"] + changes["changed_evidence"]))
        if not meaningful:
            return AgentOperationResult(
                state=old,
                changes=changes,
                affected_evidence_ids=[],
                affected_rule_ids=[],
                reasoning_recomputed=False,
            )

        affected_rules = _affected_rules(changes, facts, evidence, claims, conflicts)
        if not old.reasoning_results:
            updated_reasoning = reason_case(current_analysis)
            affected_rules = {item.rule_id for item in updated_reasoning.rules_evaluated}
        elif affected_rules:
            updated_reasoning = reason_case(
                current_analysis,
                refresh_rule_ids=affected_rules,
                previous_result=old.reasoning_results[-1],
            )
        else:
            updated_reasoning = old.reasoning_results[-1]

        reasoning_results = (
            old.reasoning_results + [updated_reasoning]
            if updated_reasoning.reasoning_id != (old.reasoning_results[-1].reasoning_id if old.reasoning_results else None)
            else old.reasoning_results
        )
        changes["reasoning_changes"] = (
            [updated_reasoning.reasoning_id]
            if reasoning_results and reasoning_results[-1].reasoning_id == updated_reasoning.reasoning_id
            and (not old.reasoning_results or old.reasoning_results[-1].reasoning_id != updated_reasoning.reasoning_id)
            else []
        )
        candidate = candidate.model_copy(update={
            "reasoning_results": reasoning_results,
            "rules_triggered": [item.rule_id for item in updated_reasoning.rules_evaluated if item.triggered],
            "unresolved_questions": updated_reasoning.unresolved_questions,
        })

        event_specs = []
        source = request.source or "case_agent"
        for document_id in changes["added_documents"]:
            event_specs.append({"event_type": "DOCUMENT_ADDED", "description": "New document added to the case.", "affected_ids": [document_id]})
        for document_id in changes["changed_documents"]:
            event_specs.append({"event_type": "DOCUMENT_CHANGED", "description": "Existing document content or analysis changed.", "affected_ids": [document_id]})
        if changes["added_facts"] or changes["changed_facts"]:
            event_specs.append({"event_type": "FACTS_EXTRACTED", "description": "Case facts changed after new information was processed.", "affected_ids": changes["added_facts"] + changes["changed_facts"]})
        if changes["added_evidence"] or changes["changed_evidence"]:
            event_specs.append({"event_type": "EVIDENCE_ADDED", "description": "Case evidence changed after new information was processed.", "affected_ids": changes["added_evidence"] + changes["changed_evidence"]})
        if changes["verification_changes"]:
            event_specs.append({"event_type": "EVIDENCE_VERIFICATION_UPDATED", "description": "Caller-supplied verified-payment evidence selection changed.", "affected_ids": changes["verification_changes"]})
        for conflict_id in changes["new_conflicts"]:
            event_specs.append({"event_type": "CONFLICT_DETECTED", "description": "A new structured conflict was detected.", "affected_ids": [conflict_id]})
        for conflict_id in changes["resolved_conflicts"]:
            event_specs.append({"event_type": "CONFLICT_RESOLVED", "description": "A previous conflict is no longer present in current analysis.", "affected_ids": [conflict_id]})
        for gap_id in changes["new_gaps"]:
            event_specs.append({"event_type": "EVIDENCE_GAP_DETECTED", "description": "A new evidence gap was detected.", "affected_ids": [gap_id]})
        for gap_id in changes["resolved_gaps"]:
            event_specs.append({"event_type": "EVIDENCE_GAP_RESOLVED", "description": "A previous evidence gap is no longer present in current analysis.", "affected_ids": [gap_id]})
        if changes["reasoning_changes"]:
            event_specs.append({"event_type": "REASONING_UPDATED", "description": "Affected symbolic rules were reevaluated after case changes.", "affected_ids": changes["reasoning_changes"]})
        event_specs.append({"event_type": "CASE_STATE_UPDATED", "description": "Persistent case state advanced after new information.", "affected_ids": [case_id]})

        saved = self.memory.save_new_version(
            candidate,
            change_summary=_summarize_changes(changes),
            triggering_event=event_specs[0]["event_type"] if event_specs else "CASE_STATE_UPDATED",
            source=source,
            event_specs=event_specs,
            expected_version=old.version,
        )
        return AgentOperationResult(
            state=saved,
            changes=changes,
            affected_evidence_ids=affected_evidence_ids,
            affected_rule_ids=sorted(affected_rules),
            reasoning_recomputed=bool(changes["reasoning_changes"]),
        )

    def challenge(
        self,
        case_id: str,
        challenge_request: CaseChallengeRequest,
        source: str = "human_challenge",
    ) -> AgentOperationResult:
        old = self.memory.get_current_state(case_id)
        target_exists = any(
            item.evidence_id == challenge_request.target_id
            and (
                challenge_request.target_document_id is None
                or item.document_id == challenge_request.target_document_id
            )
            for item in old.evidence
        ) or any(item.claim_id == challenge_request.target_id for item in old.claims) or any(
            item.conflict_id == challenge_request.target_id for item in old.conflicts
        ) or any(item.gap_id == challenge_request.target_id for item in old.evidence_gaps)
        if not target_exists:
            raise ValueError(f"Challenge target '{challenge_request.target_id}' is not present in the case.")
        challenge = CaseChallenge(
            challenge_id=str(uuid4()),
            target_id=challenge_request.target_id,
            target_document_id=challenge_request.target_document_id,
            challenge_type=challenge_request.challenge_type,
            message=challenge_request.message,
            supporting_evidence_ids=challenge_request.supporting_evidence_ids,
            timestamp=datetime.now(timezone.utc),
        )
        challenge_key = (
            f"{challenge_request.target_document_id}::{challenge.target_id}"
            if challenge_request.target_document_id
            else challenge.target_id
        )
        challenged_ids = sorted(set(old.challenged_ids + [challenge_key]))
        verified_ids = [item for item in old.verified_evidence_ids if item != challenge.target_id]
        target_evidence = next(
            (
                item for item in old.evidence
                if item.evidence_id == challenge_request.target_id
                and (
                    challenge_request.target_document_id is None
                    or item.document_id == challenge_request.target_document_id
                )
            ),
            None,
        )
        target_claim = next(
            (item for item in old.claims if item.claim_id == challenge_request.target_id),
            None,
        )
        target_conflict = next(
            (item for item in old.conflicts if item.conflict_id == challenge_request.target_id),
            None,
        )
        target_gap = next(
            (item for item in old.evidence_gaps if item.gap_id == challenge_request.target_id),
            None,
        )
        existing_verification_gap = next(
            (
                item for item in old.evidence_gaps
                if item.gap_type == "missing_verification"
                and challenge.target_id in item.related_evidence_ids
            ),
            None,
        )
        gaps = list(old.evidence_gaps)
        if existing_verification_gap is None:
            gap_number = max(
                [int(item.gap_id[1:]) for item in gaps if item.gap_id.startswith("G") and item.gap_id[1:].isdigit()]
                + [0]
            ) + 1
            related_document_ids = []
            source_pages = []
            quotes = []
            related_evidence_ids = []
            related_claim_ids = []
            related_conflict_ids = []
            related_fact_types = []
            if target_evidence:
                related_document_ids.append(target_evidence.document_id)
                source_pages.append(target_evidence.page)
                quotes.append(target_evidence.quote)
                related_evidence_ids.append(target_evidence.evidence_id)
            if target_claim:
                related_document_ids.append(target_claim.document_id)
                source_pages.append(target_claim.page)
                quotes.append(target_claim.quote)
                related_claim_ids.append(target_claim.claim_id)
            if target_conflict:
                related_document_ids.extend(target_conflict.document_ids)
                source_pages.extend(target_conflict.source_pages)
                quotes.extend(target_conflict.quotes)
                related_evidence_ids.extend(target_conflict.evidence_ids)
                related_conflict_ids.append(target_conflict.conflict_id)
            if target_gap:
                related_document_ids.extend(target_gap.related_document_ids)
                source_pages.extend(target_gap.source_pages)
                quotes.extend(target_gap.quotes)
                related_evidence_ids.extend(target_gap.related_evidence_ids)
                related_claim_ids.extend(target_gap.related_claim_ids)
                related_conflict_ids.extend(target_gap.related_conflict_ids)
            if target_evidence and target_evidence.fact_id:
                linked_fact = next(
                    (item for item in old.facts if item.fact_id == target_evidence.fact_id and item.document_id == target_evidence.document_id),
                    None,
                )
                if linked_fact:
                    related_fact_types.append(linked_fact.fact_type)
            gaps.append(
                EvidenceGap(
                    gap_id=f"G{gap_number:03d}",
                    gap_type="missing_verification",
                    description="A supplied item was challenged and requires verification.",
                    importance="high",
                    related_fact_types=related_fact_types,
                    related_claim_ids=list(dict.fromkeys(related_claim_ids)),
                    related_evidence_ids=list(dict.fromkeys(related_evidence_ids)),
                    related_conflict_ids=list(dict.fromkeys(related_conflict_ids)),
                    related_document_ids=list(dict.fromkeys(related_document_ids)),
                    source_pages=source_pages,
                    quotes=quotes,
                    suggested_evidence=[],
                    reason=challenge.message,
                    confidence=1.0,
                )
            )

        candidate = old.model_copy(update={
            "challenges": old.challenges + [challenge],
            "challenged_ids": challenged_ids,
            "verified_evidence_ids": verified_ids,
            "evidence_gaps": gaps,
        })
        analysis = _case_analysis_from_state(candidate)
        updated_reasoning = reason_case(
            analysis,
            refresh_rule_ids={"R001", "R002", "R003", "R005", "R006"},
            previous_result=old.reasoning_results[-1] if old.reasoning_results else None,
        )
        reasoning_results = old.reasoning_results + [updated_reasoning]
        candidate = candidate.model_copy(update={
            "reasoning_results": reasoning_results,
            "rules_triggered": [item.rule_id for item in updated_reasoning.rules_evaluated if item.triggered],
            "unresolved_questions": updated_reasoning.unresolved_questions,
        })
        event_specs = [
            {
                "event_type": "HUMAN_CHALLENGE_RECEIVED",
                "description": "A structured human challenge was recorded without making a legal conclusion.",
                "affected_ids": [challenge.challenge_id, challenge.target_id],
            },
            {
                "event_type": "REASONING_UPDATED",
                "description": "Payment-related reasoning was refreshed after a challenged evidence item.",
                "affected_ids": [updated_reasoning.reasoning_id],
            },
            {
                "event_type": "CASE_STATE_UPDATED",
                "description": "Case state advanced after a structured challenge.",
                "affected_ids": [case_id],
            },
        ]
        saved = self.memory.save_new_version(
            candidate,
            change_summary=f"Challenge received for {challenge.target_id}.",
            triggering_event="HUMAN_CHALLENGE_RECEIVED",
            source=source,
            event_specs=event_specs,
            expected_version=old.version,
        )
        return AgentOperationResult(
            state=saved,
            changes={"challenges": [challenge.challenge_id], "challenged_ids": [challenge.target_id]},
            affected_evidence_ids=[challenge.target_id] if any(
                item.evidence_id == challenge.target_id
                and (
                    challenge_request.target_document_id is None
                    or item.document_id == challenge_request.target_document_id
                )
                for item in old.evidence
            ) else [],
            affected_rule_ids=["R001", "R002", "R005"],
            reasoning_recomputed=True,
        )

    def review(
        self,
        case_id: str,
        request: CaseHumanReviewRequest,
        source: str = "human_review",
    ) -> AgentOperationResult:
        old = self.memory.get_current_state(case_id)
        latest = old.reasoning_results[-1] if old.reasoning_results else None
        review = CaseHumanReview(
            review_id=str(uuid4()),
            decision=request.decision,
            notes=request.notes,
            reasoning_id=latest.reasoning_id if latest else None,
            timestamp=datetime.now(timezone.utc),
        )
        candidate = old.model_copy(
            update={"human_reviews": old.human_reviews + [review]}
        )
        saved = self.memory.save_new_version(
            candidate,
            change_summary=f"Human review recorded: {review.decision}.",
            triggering_event="HUMAN_REVIEW_RECORDED",
            source=source,
            event_specs=[
                {
                    "event_type": "HUMAN_REVIEW_RECORDED",
                    "description": f"A human reviewer recorded decision '{review.decision}'.",
                    "affected_ids": [review.review_id],
                }
            ],
            expected_version=old.version,
        )
        return AgentOperationResult(
            state=saved,
            changes={"human_review_changes": [review.review_id]},
            reasoning_recomputed=False,
        )

    def override(
        self,
        case_id: str,
        request: CaseOverrideRequest,
        source: str = "human_override",
    ) -> AgentOperationResult:
        old = self.memory.get_current_state(case_id)
        latest = old.reasoning_results[-1] if old.reasoning_results else None
        if latest is None:
            raise ValueError("A recommendation must exist before it can be overridden.")
        previous_recommendation = (
            old.overrides[-1].recommendation if old.overrides else latest.recommendation
        )
        timestamp = datetime.now(timezone.utc)
        override = CaseOverride(
            override_id=str(uuid4()),
            previous_recommendation=previous_recommendation,
            recommendation=request.recommendation,
            reason=request.reason,
            reasoning_id=latest.reasoning_id,
            timestamp=timestamp,
        )
        review = CaseHumanReview(
            review_id=str(uuid4()),
            decision="overridden",
            notes=request.reason,
            reasoning_id=latest.reasoning_id,
            timestamp=timestamp,
        )
        candidate = old.model_copy(
            update={
                "overrides": old.overrides + [override],
                "human_reviews": old.human_reviews + [review],
            }
        )
        saved = self.memory.save_new_version(
            candidate,
            change_summary="A human reviewer overrode the generated recommendation.",
            triggering_event="HUMAN_OVERRIDE_APPLIED",
            source=source,
            event_specs=[
                {
                    "event_type": "HUMAN_OVERRIDE_APPLIED",
                    "description": "A human reviewer recorded an explicit recommendation override.",
                    "affected_ids": [override.override_id, review.review_id],
                }
            ],
            expected_version=old.version,
        )
        return AgentOperationResult(
            state=saved,
            changes={
                "override_changes": [override.override_id],
                "human_review_changes": [review.review_id],
            },
            reasoning_recomputed=False,
        )

    def what_if(
        self,
        case_id: str,
        request: CaseWhatIfRequest,
    ) -> CaseWhatIfResponse:
        state = self.memory.get_current_state(case_id)
        document_ids = {item.document_id for item in state.documents}
        evidence_ids = {item.evidence_id for item in state.evidence}
        unknown_documents = set(request.excluded_document_ids) - document_ids
        unknown_evidence = set(request.excluded_evidence_ids) - evidence_ids
        if unknown_documents or unknown_evidence:
            unknown = sorted(unknown_documents | unknown_evidence)
            raise ValueError("Unknown what-if exclusion IDs: " + ", ".join(unknown))

        excluded_documents = set(request.excluded_document_ids)
        excluded_evidence = set(request.excluded_evidence_ids)
        facts = [
            item for item in state.facts
            if item.document_id not in excluded_documents
        ]
        evidence = [
            item for item in state.evidence
            if item.document_id not in excluded_documents
            and item.evidence_id not in excluded_evidence
        ]
        claims = [
            item for item in state.claims
            if item.document_id not in excluded_documents
        ]
        conflicts = detect_conflicts(facts, evidence, claims)
        gaps = detect_evidence_gaps(facts, evidence, claims, conflicts)
        simulated_state = state.model_copy(
            update={
                "documents": [
                    item for item in state.documents
                    if item.document_id not in excluded_documents
                ],
                "document_analyses": [
                    item for item in state.document_analyses
                    if item.document_id not in excluded_documents
                ],
                "facts": facts,
                "evidence": evidence,
                "claims": claims,
                "conflicts": conflicts,
                "evidence_gaps": gaps,
                "verified_evidence_ids":[
                    item for item in state.verified_evidence_ids
                    if item not in excluded_evidence
                    and any(evidence_item.evidence_id == item for evidence_item in evidence)
                ],
            }
        )
        simulated_analysis = _case_analysis_from_state(simulated_state)
        return CaseWhatIfResponse(
            case_id=case_id,
            base_version=state.version,
            excluded_document_ids=sorted(excluded_documents),
            excluded_evidence_ids=sorted(excluded_evidence),
            simulated_reasoning=reason_case(simulated_analysis),
        )

    def state_response(self, case_id: str) -> CaseStateResponse:
        state = self.memory.get_current_state(case_id)
        latest = state.reasoning_results[-1] if state.reasoning_results else None
        return CaseStateResponse(
            case_id=case_id,
            version=state.version,
            metadata=state.metadata,
            counts=CaseCounts(
                document_count=len(state.documents),
                fact_count=len(state.facts),
                evidence_count=len(state.evidence),
                claim_count=len(state.claims),
                conflict_count=len(state.conflicts),
                evidence_gap_count=len(state.evidence_gaps),
            ),
            reasoning_summary=(
                {
                    "reasoning_id": latest.reasoning_id,
                    "recommendation": latest.recommendation,
                    "effective_recommendation": (
                        state.overrides[-1].recommendation
                        if state.overrides
                        else latest.recommendation
                    ),
                    "confidence": latest.confidence,
                    "human_review_required": latest.human_review_required,
                    "human_review_status": (
                        state.human_reviews[-1].decision
                        if state.human_reviews
                        else "required" if latest.human_review_required else "not_required"
                    ),
                }
                if latest
                else {}
            ),
            unresolved_questions=state.unresolved_questions,
            recent_events=state.agent_events[-10:],
            state=state,
        )

    def diff(self, case_id: str, from_version: int, to_version: int) -> CaseStateDiff:
        before = self.memory.get_version(case_id, from_version).state
        after = self.memory.get_version(case_id, to_version).state
        changes = _changes(before, after)
        return CaseStateDiff(
            case_id=case_id,
            from_version=from_version,
            to_version=to_version,
            **changes,
        )


def _case_analysis_from_state(state: CaseAgentState) -> CaseAnalysisResult:
    intake = assemble_case(
        CaseIntakeRequest(
            case_id=state.case_id,
            case_title=state.metadata.case_title,
            case_type=state.metadata.case_type,
            parties=state.metadata.parties,
            created_at=state.metadata.created_at,
            source=state.metadata.source,
            documents=state.documents,
            facts=state.facts,
            evidence=state.evidence,
            claims=state.claims,
            conflicts=state.conflicts,
            gaps=state.evidence_gaps,
        )
    )
    summary = _analysis_summary(
        state.document_analyses,
        state.facts,
        state.evidence,
        state.claims,
        state.conflicts,
        state.evidence_gaps,
    )
    return CaseAnalysisResult(
        case_intake=intake,
        documents=state.document_analyses,
        facts=state.facts,
        evidence=state.evidence,
        claims=state.claims,
        conflicts=state.conflicts,
        evidence_gaps=state.evidence_gaps,
        analysis_summary=summary,
        verified_evidence_ids=state.verified_evidence_ids,
        challenged_evidence_ids=[
            item.evidence_id
            for item in state.evidence
            if item.evidence_id in state.challenged_ids
            or f"{item.document_id}::{item.evidence_id}" in state.challenged_ids
        ],
    )


def _analysis_summary(document_analyses, facts, evidence, claims, conflicts, gaps):
    from app.schemas.analysis import AnalysisSummary

    review_signal = (
        "conflicts_require_attention"
        if any(item.severity == "high" for item in conflicts)
        else "evidence_gaps_require_attention"
        if gaps
        else "review_recommended"
        if conflicts or any(item.status == "unverified" for item in claims)
        else "no_review_signal"
    )
    return AnalysisSummary(
        document_count=len(document_analyses),
        fact_count=len(facts),
        evidence_count=len(evidence),
        claim_count=len(claims),
        conflict_count=len(conflicts),
        evidence_gap_count=len(gaps),
        high_severity_conflict_count=sum(item.severity == "high" for item in conflicts),
        review_signal=review_signal,
    )


def _summarize_changes(changes: dict[str, list[str]]) -> str:
    summaries = [f"{key.replace('_', ' ')}: {len(values)}" for key, values in changes.items() if values]
    return "; ".join(summaries) if summaries else "No structured changes detected."