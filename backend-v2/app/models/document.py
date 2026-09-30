from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import DocumentProcessingStatus
from app.utils.identifiers import DOCUMENT, new_id
from app.utils.time import utcnow


class Document(Base):
    """Document *metadata*. File bytes live in private storage; extraction belongs to Person 1."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("case_id", "filename", "version", name="uq_documents_case_filename_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        Index("ix_documents_case_checksum", "case_id", "checksum_sha256"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(DOCUMENT))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[Optional[str]] = mapped_column(String(100))
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[Optional[str]] = mapped_column(String(255))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        enum_column(DocumentProcessingStatus, "processing_status"),
        default=DocumentProcessingStatus.PENDING, nullable=False, index=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    processing_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                             nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(100))
    source_reference: Mapped[Optional[str]] = mapped_column(String(255))
    # OCR output: pages[], full_text, confidence (written by the ocr pipeline stage).
    ocr_artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    case = relationship("Case", back_populates="documents")
    evidence_items = relationship("Evidence", back_populates="document", passive_deletes="all")
