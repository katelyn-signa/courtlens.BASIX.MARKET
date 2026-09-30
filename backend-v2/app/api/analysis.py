from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.deps import AnalysisServiceDep, CaseId, PageDep, RunId
from app.core.exceptions import InvalidInputError
from app.core.security import ANALYSIS_READ, ANALYSIS_RUN, Actor, require_permission
from app.models.enums import RunStatus
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunDetail, AnalysisRunRead, StageRead
from app.schemas.common import Page, page_of

router = APIRouter(tags=["analysis"])


@router.post("/cases/{case_id}/analysis-runs", response_model=AnalysisRunDetail, status_code=201,
             summary="Request (and execute) an analysis run")
def create_run(case_id: CaseId, response: Response, service: AnalysisServiceDep,
               body: Optional[AnalysisRunCreate] = None,
               idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
               actor: Actor = Depends(require_permission(ANALYSIS_RUN))):
    body = body or AnalysisRunCreate()
    if idempotency_key and not body.idempotency_key:
        body = body.model_copy(update={"idempotency_key": idempotency_key[:120]})
    run, reused = service.request_run(case_id, body, actor.id)
    if reused:
        response.status_code = 200
    message = ("An identical run already exists; returning it (use force=true to run again)."
               if reused else None)
    return service.detail(run, reused=reused, message=message)


@router.get("/cases/{case_id}/analysis-runs", response_model=Page[AnalysisRunRead],
            summary="List analysis runs of a case (newest first)")
def list_runs(case_id: CaseId, service: AnalysisServiceDep, page: PageDep,
              status: Optional[RunStatus] = None,
              _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    service._case(case_id)
    return page_of(service.runs.list_runs(case_id, limit=page.limit, offset=page.offset,
                                          status=status), AnalysisRunRead)


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunDetail,
            summary="Get an analysis run with stages and summary")
def get_run(run_id: RunId, service: AnalysisServiceDep,
            _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    return service.detail(service.get_run(run_id))


@router.get("/analysis-runs/{run_id}/stages", response_model=list[StageRead],
            summary="Stage-by-stage status of a run")
def get_stages(run_id: RunId, service: AnalysisServiceDep,
               _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    return [StageRead.model_validate(s) for s in service.get_run(run_id).stages]


@router.post("/analysis-runs/{run_id}/retry", response_model=AnalysisRunDetail, status_code=201,
             summary="Retry a FAILED / PARTIALLY_COMPLETED run as a new linked attempt")
def retry_run(run_id: RunId, service: AnalysisServiceDep,
              actor: Actor = Depends(require_permission(ANALYSIS_RUN))):
    return service.detail(service.retry_run(run_id, actor.id))
