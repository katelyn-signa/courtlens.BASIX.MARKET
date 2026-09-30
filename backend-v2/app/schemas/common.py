from datetime import datetime
from typing import Any, Generic, Optional, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 200


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None
    request_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    database: str = "ok"


def page_of(result, item_model: type[BaseModel]) -> dict:
    return {"items": [item_model.model_validate(i) for i in result.items], "total": result.total,
            "limit": result.limit, "offset": result.offset}
