from fastapi import FastAPI, File, HTTPException, UploadFile

from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import (
    DocumentClassificationRequest,
    DocumentClassificationResult,
)
from app.schemas.facts import FactExtractionRequest, FactExtractionResult
from app.schemas.evidence import EvidenceAnalysisResult, EvidenceExtractionRequest
from app.schemas.conflict import ConflictDetectionRequest, ConflictDetectionResult
from app.schemas.evidence_gap import (
    EvidenceGapDetectionRequest,
    EvidenceGapDetectionResult,
)
from app.schemas.retrieval import (
    CaseEvidenceSearchRequest,
    RetrievalRequest,
    RetrievalResponse,
)
from app.schemas.case import CaseIntakeRequest, CaseIntakeResult
from app.schemas.analysis import CaseAnalysisRequest, CaseAnalysisResult
from app.schemas.agent_state import (
    AgentOperationResult,
    AgentStartRequest,
    AgentUpdateRequest,
    CaseChallengeRequest,
    CaseEventsResponse,
    CaseHumanReviewRequest,
    CaseOverrideRequest,
    CaseStateDiff,
    CaseStateResponse,
    CaseVersionResponse,
    CaseVersionSummary,
    CaseVersionsResponse,
    CaseWhatIfRequest,
    CaseWhatIfResponse,
)
from app.schemas.reasoning import ReasoningResult
from app.schemas.evidence_graph import EvidenceGraph
from app.schemas.agent_state import (
    AgentEvent,
    AgentOperationResult,
    AgentStartRequest,
    AgentUpdateRequest,
    CaseChallengeRequest,
    CaseEventsResponse,
    CaseStateDiff,
    CaseStateResponse,
    CaseVersionResponse,
    CaseVersionSummary,
    CaseVersionsResponse,
)
from app.agents.conflict_agent import run_conflict_agent
from app.agents.gap_agent import run_gap_agent
from app.agents.retrieval_agent import retrieve
from app.agents.intake_agent import assemble_case_intake
from app.agents.case_analysis_agent import analyze as analyze_case_request
from app.agents.case_agent import CaseAgent
from app.agents.reasoning_agent import reason_case
from app.agents.case_agent import CaseAgent
from app.services.case_memory_service import (
    CaseAlreadyExistsError,
    CaseMemoryService,
    CaseNotFoundError,
    CaseVersionConflictError,
    CaseVersionNotFoundError,
)
from app.services.evidence_graph_service import build_evidence_graph
from app.services.retrieval_service import search_case_evidence
from app.services.document_classifier import classify_document
from app.services.evidence_service import EvidenceExtractionError, analyze_document
from app.services.fact_extraction_service import FactExtractionError, extract_facts
from app.services.pdf_service import PdfExtractionError, extract_pdf
from app.services.case_memory_service import (
    CaseAlreadyExistsError,
    CaseMemoryService,
    CaseNotFoundError,
    CaseVersionConflictError,
    CaseVersionNotFoundError,
)

app = FastAPI()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "CourtLens Member 2 - Document Intelligence",
    }


@app.post("/api/documents/extract", response_model=DocumentExtractionResult)
def extract_document(file: UploadFile = File(...)) -> DocumentExtractionResult:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")

    try:
        return extract_pdf(file.file.read(), filename=file.filename)
    except PdfExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/classify", response_model=DocumentClassificationResult)
def classify_extracted_document(
    request: DocumentClassificationRequest,
) -> DocumentClassificationResult:
    if request.text is not None:
        text = request.text
    else:
        text = "\n".join(page.text for page in request.document.pages)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Document text must not be empty.")

    return classify_document(text)


@app.post("/api/documents/extract-facts", response_model=FactExtractionResult)
def extract_document_facts(
    request: FactExtractionRequest,
) -> FactExtractionResult:
    try:
        return extract_facts(request.document, request.classification)
    except FactExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/documents/extract-evidence",
    response_model=EvidenceAnalysisResult,
)
def extract_document_evidence(
    request: EvidenceExtractionRequest,
) -> EvidenceAnalysisResult:
    try:
        return analyze_document(request.document, request.classification)
    except EvidenceExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/documents/detect-conflicts",
    response_model=ConflictDetectionResult,
)
def detect_document_conflicts(
    request: ConflictDetectionRequest,
) -> ConflictDetectionResult:
    facts = list(request.facts)
    evidence = list(request.evidence)
    claims = list(request.claims)
    for analysis in request.analyses:
        facts.extend(analysis.facts)
        evidence.extend(analysis.evidence)
        claims.extend(analysis.claims)
    return run_conflict_agent(facts, evidence, claims)


@app.post(
    "/api/documents/detect-gaps",
    response_model=EvidenceGapDetectionResult,
)
def detect_document_gaps(
    request: EvidenceGapDetectionRequest,
) -> EvidenceGapDetectionResult:
    return run_gap_agent(
        request.facts,
        request.evidence,
        request.claims,
        request.conflicts,
        request.classification,
    )


@app.post("/api/documents/search", response_model=RetrievalResponse)
def search_document_evidence(request: RetrievalRequest) -> RetrievalResponse:
    return retrieve(request)


@app.post("/api/cases/intake", response_model=CaseIntakeResult)
def intake_case(request: CaseIntakeRequest) -> CaseIntakeResult:
    return assemble_case_intake(request)


@app.post("/api/cases/analyze", response_model=CaseAnalysisResult)
def analyze_case(request: CaseAnalysisRequest) -> CaseAnalysisResult:
    return analyze_case_request(request)


@app.post("/api/cases/reason", response_model=ReasoningResult)
def reason_about_case(request: CaseAnalysisResult) -> ReasoningResult:
    return reason_case(request)


def _case_agent() -> CaseAgent:
    return CaseAgent(CaseMemoryService())


@app.post(
    "/api/cases/{case_id}/agent/start",
    response_model=AgentOperationResult,
    status_code=201,
)
def start_case_agent(case_id: str, request: AgentStartRequest) -> AgentOperationResult:
    try:
        return _case_agent().start(case_id, request)
    except CaseAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/update",
    response_model=AgentOperationResult,
)
def update_case_agent(case_id: str, request: AgentUpdateRequest) -> AgentOperationResult:
    try:
        return _case_agent().update(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/state", response_model=CaseStateResponse)
def get_case_agent_state(case_id: str) -> CaseStateResponse:
    try:
        return _case_agent().state_response(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/versions", response_model=CaseVersionsResponse)
def get_case_versions(case_id: str) -> CaseVersionsResponse:
    try:
        versions = _case_agent().memory.list_versions(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CaseVersionsResponse(
        case_id=case_id,
        versions=[CaseVersionSummary.model_validate(item) for item in versions],
    )


@app.get(
    "/api/cases/{case_id}/versions/{version}",
    response_model=CaseVersionResponse,
)
def get_case_version(case_id: str, version: int) -> CaseVersionResponse:
    try:
        return _case_agent().memory.get_version(case_id, version)
    except (CaseNotFoundError, CaseVersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/events", response_model=CaseEventsResponse)
def get_case_events(case_id: str) -> CaseEventsResponse:
    try:
        return CaseEventsResponse(
            case_id=case_id,
            events=_case_agent().memory.list_events(case_id),
        )
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/api/cases/{case_id}/versions/{from_version}/{to_version}/diff",
    response_model=CaseStateDiff,
)
def get_case_version_diff(
    case_id: str,
    from_version: int,
    to_version: int,
) -> CaseStateDiff:
    try:
        return _case_agent().diff(case_id, from_version, to_version)
    except (CaseNotFoundError, CaseVersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/challenge",
    response_model=AgentOperationResult,
)
def challenge_case_agent(
    case_id: str,
    request: CaseChallengeRequest,
) -> AgentOperationResult:
    try:
        return _case_agent().challenge(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/cases/{case_id}/evidence-graph",
    response_model=EvidenceGraph,
)
def get_case_evidence_graph(case_id: str) -> EvidenceGraph:
    try:
        state = _case_agent().memory.get_current_state(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_evidence_graph(state)


@app.post(
    "/api/cases/{case_id}/evidence/search",
    response_model=RetrievalResponse,
)
def search_case_evidence_endpoint(
    case_id: str,
    request: CaseEvidenceSearchRequest,
) -> RetrievalResponse:
    try:
        state = _case_agent().memory.get_current_state(case_id)
        return search_case_evidence(state, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/review",
    response_model=AgentOperationResult,
)
def review_case_agent(
    case_id: str,
    request: CaseHumanReviewRequest,
) -> AgentOperationResult:
    try:
        return _case_agent().review(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/override",
    response_model=AgentOperationResult,
)
def override_case_agent(
    case_id: str,
    request: CaseOverrideRequest,
) -> AgentOperationResult:
    try:
        return _case_agent().override(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/what-if",
    response_model=CaseWhatIfResponse,
)
def what_if_case_agent(
    case_id: str,
    request: CaseWhatIfRequest,
) -> CaseWhatIfResponse:
    try:
        return _case_agent().what_if(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _case_agent() -> CaseAgent:
    return CaseAgent(CaseMemoryService())


@app.post(
    "/api/cases/{case_id}/agent/start",
    response_model=AgentOperationResult,
    status_code=201,
)
def start_case_agent(case_id: str, request: AgentStartRequest) -> AgentOperationResult:
    try:
        return _case_agent().start(case_id, request)
    except CaseAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/update",
    response_model=AgentOperationResult,
)
def update_case_agent(case_id: str, request: AgentUpdateRequest) -> AgentOperationResult:
    try:
        return _case_agent().update(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/state", response_model=CaseStateResponse)
def get_case_agent_state(case_id: str) -> CaseStateResponse:
    try:
        return _case_agent().state_response(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/versions", response_model=CaseVersionsResponse)
def get_case_versions(case_id: str) -> CaseVersionsResponse:
    try:
        versions = _case_agent().memory.list_versions(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CaseVersionsResponse(
        case_id=case_id,
        versions=[CaseVersionSummary.model_validate(item) for item in versions],
    )


@app.get(
    "/api/cases/{case_id}/versions/{version}",
    response_model=CaseVersionResponse,
)
def get_case_version(case_id: str, version: int) -> CaseVersionResponse:
    try:
        return _case_agent().memory.get_version(case_id, version)
    except (CaseNotFoundError, CaseVersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/events", response_model=CaseEventsResponse)
def get_case_events(case_id: str) -> CaseEventsResponse:
    try:
        events = _case_agent().memory.list_events(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CaseEventsResponse(case_id=case_id, events=events)


@app.get(
    "/api/cases/{case_id}/versions/{from_version}/{to_version}/diff",
    response_model=CaseStateDiff,
)
def get_case_state_diff(
    case_id: str,
    from_version: int,
    to_version: int,
) -> CaseStateDiff:
    try:
        return _case_agent().diff(case_id, from_version, to_version)
    except (CaseNotFoundError, CaseVersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/cases/{case_id}/agent/challenge",
    response_model=AgentOperationResult,
)
def challenge_case_agent(
    case_id: str,
    request: CaseChallengeRequest,
) -> AgentOperationResult:
    try:
        return _case_agent().challenge(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CaseVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
