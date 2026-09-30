"""HTTP endpoints for the independently runnable reasoning service."""

from fastapi import APIRouter

from backend.app.agents.reasoning.reasoning_service import ReasoningService
from backend.app.agents.reasoning.schemas import ReasoningRequest, ReasoningResponse

router = APIRouter(prefix="/api/reasoning", tags=["reasoning"])
service = ReasoningService()


@router.post("/analyze", response_model=ReasoningResponse)
def analyze_reasoning(request: ReasoningRequest) -> ReasoningResponse:
    return service.analyze(request)


@router.get("/health")
def reasoning_health() -> dict[str, str]:
    return {"status": "ok", "service": "court-lens-reasoning"}