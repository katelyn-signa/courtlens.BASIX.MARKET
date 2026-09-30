"""FastAPI dependencies: DB session, services, registry, path-parameter types."""

from typing import Annotated, Iterator

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.orchestration.registry import AgentRegistry
from app.services.analysis_service import AnalysisService
from app.services.case_service import CaseService
from app.services.document_service import DocumentService
from app.services.review_service import ReviewService
from app.services.storage import LocalFileStorage
from app.schemas.common import MAX_PAGE_SIZE
from app.utils.identifiers import CASE, DOCUMENT, REVIEW, RUN, id_pattern

CaseId = Annotated[str, Path(pattern=id_pattern(CASE), description="Case ID (case_...)")]
DocumentId = Annotated[str, Path(pattern=id_pattern(DOCUMENT), description="Document ID (doc_...)")]
RunId = Annotated[str, Path(pattern=id_pattern(RUN), description="Analysis run ID (run_...)")]
ReviewId = Annotated[str, Path(pattern=id_pattern(REVIEW), description="Review ID (rev_...)")]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


RegistryDep = Annotated[AgentRegistry, Depends(get_registry)]


def get_storage(request: Request) -> LocalFileStorage:
    return request.app.state.storage


def get_case_service(session: SessionDep) -> CaseService:
    return CaseService(session)


def get_analysis_service(request: Request, session: SessionDep) -> AnalysisService:
    return AnalysisService(
        session, request.app.state.settings, request.app.state.registry,
        request.app.state.storage, request.app.state.pipeline,
        session_factory=request.app.state.session_factory,
        background_executor=getattr(request.app.state, "background_executor", None),
    )


def get_document_service(request: Request, session: SessionDep) -> DocumentService:
    analysis = get_analysis_service(request, session)
    return DocumentService(session, request.app.state.settings, request.app.state.storage, analysis)


def get_review_service(session: SessionDep) -> ReviewService:
    return ReviewService(session)


CaseServiceDep = Annotated[CaseService, Depends(get_case_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


class Pagination:
    def __init__(self, limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
                 offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset


PageDep = Annotated[Pagination, Depends()]
