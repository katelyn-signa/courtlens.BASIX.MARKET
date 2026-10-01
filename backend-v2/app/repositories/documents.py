from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import DocumentProcessingStatus
from app.models.evidence import Evidence
from app.repositories.base import PageResult, paginate


class DocumentRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, doc: Document) -> Document:
        self.session.add(doc)
        self.session.flush()
        return doc

    def get(self, document_id: str) -> Optional[Document]:
        return self.session.get(Document, document_id)

    def get_many(self, case_id: str, ids: Sequence[str]) -> list[Document]:
        if not ids:
            return []
        return list(self.session.scalars(
            select(Document).where(Document.case_id == case_id, Document.id.in_(ids))))

    def latest_version(self, case_id: str, filename: str) -> Optional[Document]:
        return self.session.scalar(
            select(Document).where(Document.case_id == case_id, Document.filename == filename)
            .order_by(Document.version.desc()).limit(1))

    def latest_versions_for_case(self, case_id: str) -> list[Document]:
        """Highest version of each filename (the default analysis input set)."""
        docs = self.session.scalars(select(Document).where(Document.case_id == case_id)
                                    .order_by(Document.filename, Document.version)).all()
        latest: dict[str, Document] = {}
        for doc in docs:
            latest[doc.filename] = doc
        return sorted(latest.values(), key=lambda d: (d.uploaded_at, d.id))

    def list_all(self, *, limit: int, offset: int,
                 processing_status: Optional[DocumentProcessingStatus] = None,
                 document_type: Optional[str] = None) -> PageResult[Document]:
        stmt = select(Document)
        if processing_status:
            stmt = stmt.where(Document.processing_status == processing_status)
        if document_type:
            stmt = stmt.where(Document.document_type == document_type)
        stmt = stmt.order_by(Document.uploaded_at.desc(), Document.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def list_for_case(self, case_id: str, *, limit: int, offset: int,
                      processing_status: Optional[DocumentProcessingStatus] = None,
                      document_type: Optional[str] = None) -> PageResult[Document]:
        stmt = select(Document).where(Document.case_id == case_id)
        if processing_status:
            stmt = stmt.where(Document.processing_status == processing_status)
        if document_type:
            stmt = stmt.where(Document.document_type == document_type)
        stmt = stmt.order_by(Document.uploaded_at.desc(), Document.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def evidence_count(self, document_id: str) -> int:
        return self.session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.document_id == document_id)) or 0
