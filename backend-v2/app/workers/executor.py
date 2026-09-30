"""Background execution for analysis runs (optional; API contract unchanged when sync)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, Optional

from app.core.logging import get_logger
from app.core.metrics import get_metrics

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

log = get_logger("workers")


class BackgroundRunExecutor:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="courtlens-run")
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active_tasks(self) -> int:
        with self._lock:
            return self._active

    def submit(self, job: Callable[[], None]) -> None:
        def wrapped() -> None:
            with self._lock:
                self._active += 1
            get_metrics().set_gauge("active_background_runs", float(self._active))
            try:
                job()
            except Exception as exc:  # noqa: BLE001
                log.error("Background job failed: %s", type(exc).__name__)
                get_metrics().inc("background_run_failures")
            finally:
                with self._lock:
                    self._active -= 1
                get_metrics().set_gauge("active_background_runs", float(self._active))

        self._pool.submit(wrapped)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)


def run_analysis_in_background(
    session_factory: "sessionmaker",
    settings,
    registry,
    storage,
    pipeline,
    run_id: str,
    actor: str,
) -> Callable[[], None]:
    def job() -> None:
        from app.services.analysis_service import AnalysisService

        session = session_factory()
        try:
            svc = AnalysisService(session, settings, registry, storage, pipeline)
            svc._execute(run_id, actor)  # noqa: SLF001 — worker entry point
        finally:
            session.close()

    return job
