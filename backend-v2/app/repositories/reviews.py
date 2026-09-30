from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ReviewStatus
from app.models.review import Review
from app.repositories.base import PageResult, paginate


class ReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, review: Review) -> Review:
        self.session.add(review)
        self.session.flush()
        return review

    def get(self, review_id: str) -> Optional[Review]:
        return self.session.get(Review, review_id)

    def list_for_case(self, case_id: str, *, limit: int, offset: int,
                      status: Optional[ReviewStatus] = None,
                      analysis_run_id: Optional[str] = None,
                      reviewer_id: Optional[str] = None) -> PageResult[Review]:
        stmt = select(Review).where(Review.case_id == case_id)
        if status:
            stmt = stmt.where(Review.status == status)
        if analysis_run_id:
            stmt = stmt.where(Review.analysis_run_id == analysis_run_id)
        if reviewer_id:
            stmt = stmt.where(Review.reviewer_id == reviewer_id)
        stmt = stmt.order_by(Review.created_at.desc(), Review.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)
