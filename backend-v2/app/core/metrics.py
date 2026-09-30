"""In-process counters and timing histograms (Prometheus-style labels as dict keys)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _TimingStats:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0

    def record(self, seconds: float) -> None:
        self.count += 1
        self.total_seconds += seconds
        if seconds > self.max_seconds:
            self.max_seconds = seconds


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, _TimingStats] = defaultdict(_TimingStats)
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, value: int = 1, **labels: Any) -> None:
        key = _key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, **labels: Any) -> None:
        key = _key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, seconds: float, **labels: Any) -> None:
        key = _key(name, labels)
        with self._lock:
            self._timings[key].record(seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            timings = {
                k: {
                    "count": v.count,
                    "total_seconds": round(v.total_seconds, 4),
                    "avg_seconds": round(v.total_seconds / v.count, 4) if v.count else 0.0,
                    "max_seconds": round(v.max_seconds, 4),
                }
                for k, v in self._timings.items()
            }
        return {"counters": counters, "gauges": gauges, "timings": timings}


def _key(name: str, labels: dict[str, Any]) -> str:
    if not labels:
        return name
    parts = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}{{{parts}}}"


_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _metrics


class observe_duration:
    """Context manager: ``with observe_duration('pipeline_run', run_id=rid): ...``"""

    def __init__(self, name: str, **labels: Any) -> None:
        self._name = name
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> observe_duration:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        get_metrics().observe(self._name, time.perf_counter() - self._start, **self._labels)
