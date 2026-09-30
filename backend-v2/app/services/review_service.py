from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (AnalysisRunNotFoundError, CaseNotFoundError, InvalidInputError,
                                 InvalidStateTransitionError, ReviewNotFoundError)
from app.core.state import REVIEW_TRANSITIONS, ensure_transition
from app.models.analysis_run import AnalysisRun
from app.models.conflict import Conflict
from app.models.enums import AuditEventType, ReviewStatus, WorkflowAction
from app.models.evidence import Evidence
from app.models.review import Review
from app.models.rule_result import RuleResult
from app.repositories.cases import CaseRepository
from app.repositories.reviews import ReviewRepository
from app.schemas.review import FindingRef, InformationRequest, ReviewCreate, ReviewUpdate
from app.services.audit_service import AuditService
from app.utils.time import utcnow

_REF_MODELS = {"conflict": Conflict, "rule_result": RuleResult, "evidence": Evidence}


class ReviewService:
    """Human review records. Never touches conflicts, rule results or evidence."""

    def __init__(self, session: Session):
        self.session = session
        self.cases = CaseRepository(session)
        self.reviews = ReviewRepository(session)
        self.audit = AuditService(session)

    def get_review(self, review_id: str) -> Review:
        review = self.reviews.get(review_id)
        if review is None:
            raise ReviewNotFoundError()
        return review

    def _validate_refs(self, case_id: str, refs: list[FindingRef]) -> list[dict]:
        out = []
        for ref in refs:
            model = _REF_MODELS[ref.type]
            if self.session.scalar(select(model.id).where(model.id == ref.id,
                                                          model.case_id == case_id)) is None:
                raise InvalidInputError(f"Referenced {ref.type} {ref.id!r} does not belong to this case.",
                                        code="INVALID_FINDING_REFERENCE")
            out.append(ref.model_dump())
        return out

    def create_review(self, case_id: str, data: ReviewCreate, actor: str) -> Review:
        if self.cases.get(case_id) is None:
            raise CaseNotFoundError()
        if data.analysis_run_id:
            run = self.session.get(AnalysisRun, data.analysis_run_id)
            if run is None or run.case_id != case_id:
                raise AnalysisRunNotFoundError("Analysis run not found for this case.")
        review = self.reviews.add(Review(
            case_id=case_id, analysis_run_id=data.analysis_run_id, reviewer_id=data.reviewer_id,
            notes=data.notes, reviewed_finding_refs=self._validate_refs(case_id, data.reviewed_finding_refs),
            created_by=actor))
        self.audit.record(AuditEventType.REVIEW_CREATED, case_id=case_id, actor=actor,
                          resource_type="review", resource_id=review.id,
                          analysis_run_id=data.analysis_run_id)
        self.session.commit()
        return review

    def update_review(self, review_id: str, data: ReviewUpdate, actor: str) -> Review:
        review = self.get_review(review_id)
        changes = data.model_dump(exclude_unset=True)
        if review.status == ReviewStatus.REVIEW_COMPLETED and changes:
            raise InvalidStateTransitionError("A completed review is immutable.",
                                              code="REVIEW_ALREADY_COMPLETED")
        new_status = changes.get("status", review.status)
        ensure_transition(review.status, new_status, REVIEW_TRANSITIONS, "Review status")
        if "workflow_action" in changes and changes["workflow_action"] is None:
            raise InvalidInputError("workflow_action cannot be null.")
        if "reviewed_finding_refs" in changes:
            if changes["reviewed_finding_refs"] is None:
                raise InvalidInputError("reviewed_finding_refs cannot be null.")
            review.reviewed_finding_refs = self._validate_refs(
                review.case_id, [FindingRef(**r) if isinstance(r, dict) else r
                                 for r in changes["reviewed_finding_refs"]])
        if "notes" in changes:
            review.notes = changes["notes"]
        if "reviewer_id" in changes:
            review.reviewer_id = changes["reviewer_id"]
        if "workflow_action" in changes:
            review.workflow_action = changes["workflow_action"]
        previous = review.status
        if new_status != previous:
            review.status = new_status
            if new_status == ReviewStatus.REVIEW_COMPLETED:
                review.completed_at = utcnow()
                review.workflow_action = WorkflowAction.COMPLETE_REVIEW
            if new_status == ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED:
                review.additional_evidence_requested = True
        event = {ReviewStatus.IN_REVIEW: AuditEventType.REVIEW_STARTED,
                 ReviewStatus.REVIEW_COMPLETED: AuditEventType.REVIEW_COMPLETED,
                 ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED:
                     AuditEventType.ADDITIONAL_INFORMATION_REQUESTED}.get(new_status)
        if new_status == previous or event is None:
            event = AuditEventType.REVIEW_UPDATED
        self.audit.record(event, case_id=review.case_id, actor=actor, resource_type="review",
                          resource_id=review.id, analysis_run_id=review.analysis_run_id,
                          metadata={"status": review.status.value,
                                    "changed_fields": sorted(changes.keys())})
        self.session.commit()
        return review

    def request_information(self, review_id: str, data: InformationRequest, actor: str) -> Review:
        review = self.get_review(review_id)
        if review.status == ReviewStatus.REVIEW_COMPLETED:
            raise InvalidStateTransitionError("A completed review is immutable.",
                                              code="REVIEW_ALREADY_COMPLETED")
        ensure_transition(review.status, ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED,
                          REVIEW_TRANSITIONS, "Review status")
        review.status = ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED
        review.workflow_action = WorkflowAction.REQUEST_ADDITIONAL_INFORMATION
        review.additional_evidence_requested = True
        review.additional_information_request = data.request_text
        self.audit.record(AuditEventType.ADDITIONAL_INFORMATION_REQUESTED, case_id=review.case_id,
                          actor=actor, resource_type="review", resource_id=review.id,
                          analysis_run_id=review.analysis_run_id,
                          metadata={"request_length": len(data.request_text)})
        self.session.commit()
        return review
