from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CaseId, CaseServiceDep, PageDep, ReviewId, ReviewServiceDep
from app.core.exceptions import InvalidInputError
from app.core.security import REVIEWS_READ, REVIEWS_WRITE, Actor, require_permission
from app.models.enums import ReviewStatus
from app.schemas.common import Page, page_of
from app.schemas.review import InformationRequest, ReviewCreate, ReviewRead, ReviewUpdate

router = APIRouter(tags=["reviews"])


@router.post("/cases/{case_id}/reviews", response_model=ReviewRead, status_code=201,
             summary="Create a human review record")
def create_review(case_id: CaseId, body: ReviewCreate, service: ReviewServiceDep,
                  actor: Actor = Depends(require_permission(REVIEWS_WRITE))):
    return service.create_review(case_id, body, actor.id)


@router.get("/cases/{case_id}/reviews", response_model=Page[ReviewRead],
            summary="List reviews of a case")
def list_reviews(case_id: CaseId, service: ReviewServiceDep, cases: CaseServiceDep, page: PageDep,
                 status: Optional[ReviewStatus] = None, analysis_run_id: Optional[str] = None,
                 reviewer_id: Optional[str] = None,
                 _actor: Actor = Depends(require_permission(REVIEWS_READ))):
    cases.get_case(case_id)
    return page_of(service.reviews.list_for_case(
        case_id, limit=page.limit, offset=page.offset, status=status,
        analysis_run_id=analysis_run_id, reviewer_id=reviewer_id), ReviewRead)


@router.get("/reviews/{review_id}", response_model=ReviewRead, summary="Get a review")
def get_review(review_id: ReviewId, service: ReviewServiceDep,
               _actor: Actor = Depends(require_permission(REVIEWS_READ))):
    return service.get_review(review_id)


@router.patch("/reviews/{review_id}", response_model=ReviewRead,
              summary="Update review status / notes (validated transitions)")
def update_review(review_id: ReviewId, body: ReviewUpdate, service: ReviewServiceDep,
                  actor: Actor = Depends(require_permission(REVIEWS_WRITE))):
    return service.update_review(review_id, body, actor.id)


@router.post("/reviews/{review_id}/request-information", response_model=ReviewRead,
             summary="Record an additional-information request")
def request_information(review_id: ReviewId, body: InformationRequest, service: ReviewServiceDep,
                        actor: Actor = Depends(require_permission(REVIEWS_WRITE))):
    return service.request_information(review_id, body, actor.id)
