"""Uniform agent surface: execute(), health(), metadata() with configurable retries/timeouts."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentHealth:
    status: str  # ok | degraded | unavailable
    message: Optional[str] = None


class StandardAgent:
    """Wraps a stage implementation so the registry always sees execute/health/metadata."""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        stage_key: str,
        handler: Callable[[BaseModel], Any],
        is_simulated: bool = False,
        timeout_seconds: Optional[float] = None,
        max_attempts: Optional[int] = None,
    ) -> None:
        self.name = name
        self.version = version
        self.stage_key = stage_key
        self._handler = handler
        self.is_simulated = is_simulated
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def execute(self, request: BaseModel) -> Any:
        return self._handler(request)

    def health(self) -> AgentHealth:
        return AgentHealth(status="ok")

    def metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "stage_key": self.stage_key,
            "is_simulated": self.is_simulated,
        }
        if self.timeout_seconds is not None:
            out["timeout_seconds"] = self.timeout_seconds
        if self.max_attempts is not None:
            out["max_attempts"] = self.max_attempts
        return out


def wrap_legacy_agent(
    agent: Any,
    *,
    stage_key: str,
    method: str,
    is_simulated: bool = False,
) -> StandardAgent:
    fn = getattr(agent, method, None)
    if not callable(fn):
        raise TypeError(f"Agent must implement .{method}()")
    return StandardAgent(
        name=getattr(agent, "name", type(agent).__name__),
        version=getattr(agent, "version", "unknown"),
        stage_key=stage_key,
        handler=fn,
        is_simulated=is_simulated,
        timeout_seconds=getattr(agent, "timeout_seconds", None),
        max_attempts=getattr(agent, "max_attempts", None),
    )
