from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


@dataclass
class PageResult(Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int


def paginate(session: Session, stmt: Select[Any], *, limit: int, offset: int) -> PageResult[Any]:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = session.scalars(stmt.limit(limit).offset(offset)).all()
    return PageResult(items=items, total=total, limit=limit, offset=offset)
