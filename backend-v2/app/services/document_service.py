from typing import BinaryIO, Optional

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import (CaseNotFoundError, DocumentNotFoundError, InvalidInputError,
                                 UnsupportedFileTypeError)
from app.models.case import Case
from app.models.document import Document
from app.models.enums import AuditEventType, DocumentProcessingStatus, TriggerType
from app.repositories.analysis import AnalysisRepository
from app.repositories.cases import CaseRepository
from app.repositories.documents import DocumentRepository
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.document import DocumentRegister
from app.services.audit_service import AuditService
from app.services.storage import LocalFileStorage, safe_display_name, validate_storage_key
import os


class DocumentService:
    def __init__(self, session: Session, settings: Settings, storage: LocalFileStorage,
                 analysis_service=None):
        self.session = session
        self.settings = settings
        self.storage = storage
        self.analysis_service = analysis_service
        self.cases = CaseRepository(session)
        self.docs = DocumentRepository(session)
        self.runs = AnalysisRepository(session)
        self.audit = AuditService(session)

    def _case(self, case_id: str) -> Case:
        case = self.cases.get(case_id)
        if case is None:
            raise CaseNotFoundError()
        return case

    def get_document(self, document_id: str) -> Document:
        doc = self.docs.get(document_id)
        if doc is None:
            raise DocumentNotFoundError()
        return doc

    def _validate_type(self, filename: str, mime_type: str) -> None:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self.settings.allowed_upload_extensions:
            raise UnsupportedFileTypeError(f"File extension {ext or '(none)'!r} is not allowed.",
                                           details={"allowed": self.settings.allowed_upload_extensions})
        if mime_type.lower() not in self.settings.allowed_upload_mime_types:
            raise UnsupportedFileTypeError(f"MIME type {mime_type!r} is not allowed.",
                                           details={"allowed": self.settings.allowed_upload_mime_types})

    def register_document(self, case_id: str, data: DocumentRegister, actor: str
                          ) -> tuple[Document, bool, Optional[str]]:
        """Register metadata. Returns (document, created, triggered_run_id).

        Idempotent: re-registering the latest version of a filename with an identical checksum
        returns the existing record. A changed checksum creates version N+1.
        """
        case = self._case(case_id)
        filename = safe_display_name(data.filename)
        self._validate_type(filename, data.mime_type)
        if data.size_bytes > self.settings.max_upload_bytes:
            from app.core.exceptions import FileTooLargeError
            raise FileTooLargeError(f"Document exceeds {self.settings.max_upload_bytes} bytes.")
        if data.storage_key:
            validate_storage_key(data.storage_key)
        checksum = data.checksum_sha256.lower()
        latest = self.docs.latest_version(case_id, filename)
        if latest is not None and latest.checksum_sha256 == checksum:
            return latest, False, None
        return self._create(case, filename, data.mime_type, data.size_bytes, checksum,
                            data.storage_key, data.document_type, data.source_reference, actor,
                            latest.version + 1 if latest else 1)

    def upload_document(self, case_id: str, filename: str, mime_type: str, stream: BinaryIO,
                        document_type: Optional[str], source_reference: Optional[str], actor: str
                        ) -> tuple[Document, bool, Optional[str]]:
        case = self._case(case_id)
        name = safe_display_name(filename)
        self._validate_type(name, mime_type)
        key, checksum, size = self.storage.save_stream(
            case_id, name, stream, allowed_extensions=self.settings.allowed_upload_extensions,
            max_bytes=self.settings.max_upload_bytes)
        latest = self.docs.latest_version(case_id, name)
        if latest is not None and latest.checksum_sha256 == checksum:
            self.storage.resolve(key).unlink(missing_ok=True)  # identical content: keep existing
            return latest, False, None
        return self._create(case, name, mime_type, size, checksum, key, document_type,
                            source_reference, actor, latest.version + 1 if latest else 1)

    def _create(self, case: Case, filename, mime_type, size, checksum, storage_key, document_type,
                source_reference, actor, version) -> tuple[Document, bool, Optional[str]]:
        doc = self.docs.add(Document(
            case_id=case.id, filename=filename, mime_type=mime_type, size_bytes=size,
            checksum_sha256=checksum, storage_key=storage_key, document_type=document_type,
            processing_status=DocumentProcessingStatus.PENDING, version=version,
            uploaded_by=actor, source_reference=source_reference))
        self.audit.record(AuditEventType.DOCUMENT_REGISTERED, case_id=case.id, actor=actor,
                          resource_type="document", resource_id=doc.id,
                          metadata={"filename": filename, "version": version, "size_bytes": size,
                                    "mime_type": mime_type})
        # Reprocessing strategy: never overwrite. Flag prior analyses as stale and the case as
        # needing a refresh; the next run picks the new version up automatically.
        case.analysis_needs_refresh = True
        stale = self.runs.mark_stale(case.id)
        if stale:
            self.audit.record(AuditEventType.ANALYSIS_MARKED_STALE, case_id=case.id, actor="system",
                              resource_type="document", resource_id=doc.id,
                              metadata={"run_ids": stale})
        self.session.commit()
        triggered = None
        if self.settings.auto_reanalyze_on_new_document and self.analysis_service is not None:
            run, _ = self.analysis_service.request_run(
                case.id, AnalysisRunCreate(), actor, trigger=TriggerType.NEW_DOCUMENT)
            triggered = run.id
        return doc, True, triggered

    def status(self, document_id: str) -> tuple[Document, int]:
        doc = self.get_document(document_id)
        return doc, self.docs.evidence_count(doc.id)
