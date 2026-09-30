from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.api.deps import CaseId, DocumentId, DocumentServiceDep, PageDep
from app.core.security import DOCUMENTS_READ, DOCUMENTS_WRITE, Actor, require_permission
from app.models.enums import DocumentProcessingStatus
from app.schemas.common import Page, page_of
from app.schemas.document import (DocumentRead, DocumentRegister, DocumentRegistrationResult,
                                  DocumentStatusRead)

router = APIRouter(tags=["documents"])


def _result(doc, created: bool, run_id: Optional[str], case_needs_refresh: bool, response: Response):
    response.status_code = 201 if created else 200
    return DocumentRegistrationResult(
        document=DocumentRead.model_validate(doc), created=created,
        analysis_needs_refresh=case_needs_refresh, triggered_analysis_run_id=run_id)


@router.post("/cases/{case_id}/documents", response_model=DocumentRegistrationResult,
             status_code=201, summary="Register document metadata (idempotent by checksum)")
def register_document(case_id: CaseId, body: DocumentRegister, response: Response,
                      service: DocumentServiceDep,
                      actor: Actor = Depends(require_permission(DOCUMENTS_WRITE))):
    doc, created, run_id = service.register_document(case_id, body, actor.id)
    return _result(doc, created, run_id, service.cases.get(case_id).analysis_needs_refresh, response)


@router.post("/cases/{case_id}/documents/upload", response_model=DocumentRegistrationResult,
             status_code=201, summary="Upload a file (validated, stored in private storage)")
def upload_document(case_id: CaseId, response: Response, service: DocumentServiceDep,
                    file: Annotated[UploadFile, File(description="The document file")],
                    document_type: Annotated[Optional[str], Form(max_length=100)] = None,
                    source_reference: Annotated[Optional[str], Form(max_length=255)] = None,
                    actor: Actor = Depends(require_permission(DOCUMENTS_WRITE))):
    doc, created, run_id = service.upload_document(
        case_id, file.filename or "", file.content_type or "application/octet-stream", file.file,
        document_type, source_reference, actor.id)
    return _result(doc, created, run_id, service.cases.get(case_id).analysis_needs_refresh, response)


@router.get("/cases/{case_id}/documents", response_model=Page[DocumentRead],
            summary="List documents of a case")
def list_documents(case_id: CaseId, service: DocumentServiceDep, page: PageDep,
                   processing_status: Optional[DocumentProcessingStatus] = None,
                   document_type: Optional[str] = None,
                   _actor: Actor = Depends(require_permission(DOCUMENTS_READ))):
    service._case(case_id)
    return page_of(service.docs.list_for_case(case_id, limit=page.limit, offset=page.offset,
                                              processing_status=processing_status,
                                              document_type=document_type), DocumentRead)


@router.get("/documents/{document_id}", response_model=DocumentRead,
            summary="Get document metadata")
def get_document(document_id: DocumentId, service: DocumentServiceDep,
                 _actor: Actor = Depends(require_permission(DOCUMENTS_READ))):
    return service.get_document(document_id)


@router.get("/documents/{document_id}/status", response_model=DocumentStatusRead,
            summary="Document processing status")
def document_status(document_id: DocumentId, service: DocumentServiceDep,
                    _actor: Actor = Depends(require_permission(DOCUMENTS_READ))):
    doc, count = service.status(document_id)
    return DocumentStatusRead(
        document_id=doc.id, version=doc.version, processing_status=doc.processing_status,
        processing_error=doc.processing_error, processing_updated_at=doc.processing_updated_at,
        evidence_count=count)
