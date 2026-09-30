"""Agent registry. Missing agents are reported honestly (NOT_CONFIGURED); never faked."""

import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from app.core.logging import get_logger

log = get_logger("registry")


class AgentKey(str, Enum):
    DOCUMENT_INTELLIGENCE = "document_intelligence"   # Person 1
    CONFLICT_DETECTION = "conflict_detection"         # Person 2
    REASONING = "reasoning"                           # Person 3


# The single method each agent must expose (see contracts.py protocols).
AGENT_METHODS = {
    AgentKey.DOCUMENT_INTELLIGENCE: "extract",
    AgentKey.CONFLICT_DETECTION: "analyze",
    AgentKey.REASONING: "evaluate",
}


@dataclass
class AgentRegistration:
    key: AgentKey
    agent: Any
    source: str  # "demo" | "custom" | "manual"


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[AgentKey, AgentRegistration] = {}
        self._config_errors: dict[AgentKey, str] = {}

    def register(self, key: AgentKey | str, agent: Any, *, source: str = "manual",
                 replace: bool = False) -> None:
        key = AgentKey(key)
        method = AGENT_METHODS[key]
        if not callable(getattr(agent, method, None)):
            raise TypeError(f"Agent for {key.value!r} must implement .{method}(request).")
        if key in self._agents and not replace:
            raise ValueError(f"An agent is already registered for {key.value!r}.")
        self._agents[key] = AgentRegistration(key, agent, source)
        self._config_errors.pop(key, None)

    def unregister(self, key: AgentKey | str) -> None:
        self._agents.pop(AgentKey(key), None)

    def get(self, key: AgentKey | str) -> Optional[AgentRegistration]:
        return self._agents.get(AgentKey(key))

    def record_configuration_error(self, key: AgentKey, message: str) -> None:
        self._config_errors[key] = message

    def describe(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key in AgentKey:
            reg = self._agents.get(key)
            if reg is None:
                entry: dict[str, Any] = {"status": "NOT_CONFIGURED"}
                if key in self._config_errors:
                    entry["configuration_error"] = self._config_errors[key]
                out[key.value] = entry
            else:
                out[key.value] = {
                    "status": "CONFIGURED",
                    "source": reg.source,
                    "agent_name": getattr(reg.agent, "name", type(reg.agent).__name__),
                    "agent_version": getattr(reg.agent, "version", "unknown"),
                    "is_simulated": reg.source == "demo",
                }
        return out


def _load_class(path: str) -> Any:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("Use the format 'package.module:ClassName'.")
    return getattr(importlib.import_module(module_name), attr)


def build_default_registry(settings) -> AgentRegistry:
    """Wire agents from configuration.

    Order of precedence per stage: ``*_AGENT_CLASS`` import path > demo agents > not configured.
    A bad import path never crashes startup; it is reported as a configuration error.
    """
    from app.integrations.conflict_agent import DemoConflictAgent
    from app.integrations.document_agent import DemoDocumentAgent
    from app.integrations.reasoning_agent import DemoReasoningAgent

    registry = AgentRegistry()
    wiring = [
        (AgentKey.DOCUMENT_INTELLIGENCE, settings.document_agent_class, DemoDocumentAgent),
        (AgentKey.CONFLICT_DETECTION, settings.conflict_agent_class, DemoConflictAgent),
        (AgentKey.REASONING, settings.reasoning_agent_class, DemoReasoningAgent),
    ]
    for key, class_path, demo_cls in wiring:
        if class_path:
            try:
                registry.register(key, _load_class(class_path)(), source="custom")
            except Exception as exc:  # noqa: BLE001 - reported, not fatal
                registry.record_configuration_error(key, f"Could not load agent: {type(exc).__name__}")
                log.error("Failed to load %s agent (%s)", key.value, type(exc).__name__)
        elif settings.enable_demo_agents:
            registry.register(key, demo_cls(), source="demo")
    return registry
