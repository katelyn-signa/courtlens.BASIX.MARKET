from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.api.deps import RegistryDep, SettingsDep
from app.core.security import SYSTEM_READ, Actor, require_permission
from app.orchestration.contracts import CONTRACT_VERSION

# Public (unauthenticated) liveness endpoints.
public_router = APIRouter(tags=["health"])
# Authenticated system endpoints (mounted under /api/v1).
system_router = APIRouter(tags=["system"])


def _health(request: Request):
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db, code, status = "ok", 200, "ok"
    except Exception:  # noqa: BLE001 - never leak connection details
        db, code, status = "unavailable", 503, "degraded"
    return JSONResponse(status_code=code, content={
        "status": status, "version": __version__, "database": db,
        "timestamp": datetime.now(timezone.utc).isoformat()})


@public_router.get("/api/health", summary="Liveness/readiness check")
def health(request: Request):
    return _health(request)


@public_router.get("/api/v1/health", summary="Liveness/readiness check (versioned)")
def health_v1(request: Request):
    return _health(request)


@system_router.get("/system/status", summary="Configured integrations and runtime settings")
def system_status(request: Request, settings: SettingsDep, registry: RegistryDep,
                  _actor: Actor = Depends(require_permission(SYSTEM_READ))):
    pipeline = request.app.state.pipeline
    return {
        "app": settings.app_name, "version": __version__, "environment": settings.app_env,
        "contract_version": CONTRACT_VERSION,
        "database": {"dialect": request.app.state.engine.dialect.name},
        "authentication": {"api_key_required": settings.api_key_value is not None,
                           "note": "Development trust boundary; see app/core/security.py."},
        "agents": registry.describe(),
        "pipeline": {"version": pipeline.version,
                     "stages": [{"name": s.name, "agent": s.agent_key.value,
                                 "required": s.required, "depends_on": list(s.depends_on)}
                                for s in pipeline.stages]},
        "orchestration": {"agent_timeout_seconds": settings.agent_timeout_seconds,
                          "agent_max_attempts": settings.agent_max_attempts,
                          "max_run_retries": settings.max_run_retries,
                          "auto_reanalyze_on_new_document": settings.auto_reanalyze_on_new_document},
        "uploads": {"max_upload_bytes": settings.max_upload_bytes,
                    "allowed_extensions": settings.allowed_upload_extensions},
        "ai_provider_configured": bool(settings.ai_provider),
    }
