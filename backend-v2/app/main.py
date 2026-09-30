"""CourtLens backend entry point (Person 4)."""

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import health
from app.api.router import build_v1_router
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.db.migrate import upgrade_to_head
from app.db.session import create_db_engine, create_session_factory
from app.orchestration.pipeline import DEFAULT_PIPELINE, PipelineDefinition
from app.orchestration.registry import AgentRegistry, build_default_registry
from app.services.storage import LocalFileStorage

log = get_logger("main")

_TITLE_DESC = (
    "CourtLens shared backend: persistent case memory, agent orchestration, human-review "
    "records and audit history. **Decision-support only**: nothing here grants or refuses bail."
)


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    rid = request_id_ctx.get()
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "details": details,
        "request_id": None if rid == "-" else rid}})


def create_app(settings: Optional[Settings] = None, *, registry: Optional[AgentRegistry] = None,
               pipeline: PipelineDefinition = DEFAULT_PIPELINE) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.database_url, echo=False)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            upgrade_to_head(settings.database_url)  # Alembic is the only schema creator
        log.info("CourtLens backend %s started (env=%s)", __version__, settings.app_env)
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=__version__, description=_TITLE_DESC,
                  lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.registry = registry or build_default_registry(settings)
    app.state.pipeline = pipeline
    app.state.storage = LocalFileStorage(settings.storage_dir)

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if incoming and len(incoming) <= 100 and incoming.isprintable() \
            else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(p) for p in e["loc"]], "message": e["msg"], "type": e["type"]}
                   for e in exc.errors()]  # inputs are intentionally not echoed
        return _error(422, "VALIDATION_ERROR", "Request validation failed.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError):
        log.warning("Database integrity error: %s", type(exc.orig).__name__)
        return _error(409, "DATABASE_INTEGRITY_ERROR", "The request conflicts with existing data.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return _error(500, "INTERNAL_ERROR", "An unexpected error occurred.")

    app.include_router(health.public_router)
    app.include_router(build_v1_router(), prefix=settings.api_v1_prefix)
    return app


app = create_app()
