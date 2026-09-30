from app.schemas.retrieval import RetrievalRequest, RetrievalResponse
from app.services.retrieval_service import search


def retrieve(request: RetrievalRequest) -> RetrievalResponse:
    return search(request)