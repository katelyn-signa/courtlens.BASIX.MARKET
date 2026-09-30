from fastapi import APIRouter, Depends, Request

from app.core.metrics import get_metrics
from app.core.security import SYSTEM_READ, Actor, require_permission

router = APIRouter(tags=["system"])


@router.get("/system/metrics", summary="Runtime counters and stage timings")
def system_metrics(_request: Request, _actor: Actor = Depends(require_permission(SYSTEM_READ))):
    snap = get_metrics().snapshot()
    snap["health_status"] = "ok"
    return snap
