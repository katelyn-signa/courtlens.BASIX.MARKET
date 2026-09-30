"""Logging with request correlation and privacy protections.

Rule: application logs carry identifiers, counts and error *types* only.
Document text, quotations, agent-provided free text, secrets and API keys are never logged.
"""

import logging
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_factory_installed = False


def get_request_id() -> str:
    return request_id_ctx.get()


def _install_record_factory() -> None:
    global _factory_installed
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.request_id = request_id_ctx.get()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging(level: str = "INFO") -> None:
    _install_record_factory()
    logger = logging.getLogger("courtlens")
    logger.setLevel(level.upper())
    if not any(getattr(h, "_courtlens", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler._courtlens = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
        logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"courtlens.{name}")
