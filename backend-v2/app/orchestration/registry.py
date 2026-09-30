"""Agent registry. Missing agents are reported honestly (NOT_CONFIGURED); never faked."""

import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from app.core.logging import get_logger
from app.orchestration.agent_adapter import StandardAgent, wrap_legacy_agent

log = get_logger("registry")


class AgentKey(str, Enum):
    OCR = "ocr"
    EVIDENCE_EXTRACTION = "evidence_extraction"
    CONFLICT_DETECTION = "conflict_detection"
    RULE_EVALUATION = "rule_evaluation"
    SUMMARY_GENERATION = "summary_generation"
    # Legacy keys (Person 1–3 bundles) — resolved to modern stages via pipeline aliases.
    DOCUMENT_INTELLIGENCE = "document_intelligence"
    REASONING = "reasoning"


AGENT_METHOD = "execute"


@dataclass
class AgentRegistration:
    key: AgentKey
    agent: Any  # StandardAgent
    source: str  # "demo" | "custom" | "manual"


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[AgentKey, AgentRegistration] = {}
        self._config_errors: dict[AgentKey, str] = {}

    def register(self, key: AgentKey | str, agent: Any, *, source: str = "manual",
                 replace: bool = False) -> None:
        key = AgentKey(key)
        if not callable(getattr(agent, AGENT_METHOD, None)):
            raise TypeError(f"Agent for {key.value!r} must implement .{AGENT_METHOD}(request).")
        if key in self._agents and not replace:
            raise ValueError(f"An agent is already registered for {key.value!r}.")
        self._agents[key] = AgentRegistration(key, agent, source)
        self._config_errors.pop(key, None)

    def register_legacy(self, key: AgentKey, agent: Any, *, method: str, source: str,
                        replace: bool = False) -> None:
        wrapped = wrap_legacy_agent(agent, stage_key=key.value, method=method,
                                    is_simulated=source == "demo")
        self.register(key, wrapped, source=source, replace=replace)

    def unregister(self, key: AgentKey | str) -> None:
        self._agents.pop(AgentKey(key), None)

    def get(self, key: AgentKey | str) -> Optional[AgentRegistration]:
        return self._agents.get(AgentKey(key))

    def record_configuration_error(self, key: AgentKey, message: str) -> None:
        self._config_errors[key] = message

    def health_report(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key in AgentKey:
            reg = self._agents.get(key)
            if reg is None:
                continue
            health_fn = getattr(reg.agent, "health", None)
            meta_fn = getattr(reg.agent, "metadata", None)
            out[key.value] = {
                "health": health_fn().status if callable(health_fn) else "unknown",
                "metadata": meta_fn() if callable(meta_fn) else {},
            }
        return out

    def describe(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        pipeline_keys = (
            AgentKey.OCR, AgentKey.EVIDENCE_EXTRACTION, AgentKey.CONFLICT_DETECTION,
            AgentKey.RULE_EVALUATION, AgentKey.SUMMARY_GENERATION,
        )
        for key in pipeline_keys:
            reg = self._agents.get(key)
            if reg is None:
                entry: dict[str, Any] = {"status": "NOT_CONFIGURED"}
                if key in self._config_errors:
                    entry["configuration_error"] = self._config_errors[key]
                out[key.value] = entry
            else:
                meta = reg.agent.metadata() if hasattr(reg.agent, "metadata") else {}
                out[key.value] = {
                    "status": "CONFIGURED",
                    "source": reg.source,
                    "agent_name": meta.get("name", getattr(reg.agent, "name", "?")),
                    "agent_version": meta.get("version", "unknown"),
                    "is_simulated": reg.source == "demo",
                }
        return out


def _load_class(path: str) -> Any:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("Use the format 'package.module:ClassName'.")
    return getattr(importlib.import_module(module_name), attr)


def build_default_registry(settings) -> AgentRegistry:
    """Wire agents from configuration (five pipeline stages + optional legacy class paths)."""
    from app.integrations.conflict_agent import DemoConflictAgent
    from app.integrations.evidence_agent import DemoEvidenceAgent
    from app.integrations.ocr_agent import DemoOcrAgent
    from app.integrations.rule_agent import DemoRuleAgent
    from app.integrations.summary_agent import DemoSummaryAgent

    registry = AgentRegistry()
    demo_wiring = [
        (AgentKey.OCR, DemoOcrAgent, "run_ocr"),
        (AgentKey.EVIDENCE_EXTRACTION, DemoEvidenceAgent, "extract"),
        (AgentKey.CONFLICT_DETECTION, DemoConflictAgent, "analyze"),
        (AgentKey.RULE_EVALUATION, DemoRuleAgent, "evaluate"),
        (AgentKey.SUMMARY_GENERATION, DemoSummaryAgent, "summarize"),
    ]
    class_paths = {
        AgentKey.OCR: getattr(settings, "ocr_agent_class", None) or settings.document_agent_class,
        AgentKey.EVIDENCE_EXTRACTION: getattr(settings, "evidence_agent_class", None)
        or settings.document_agent_class,
        AgentKey.CONFLICT_DETECTION: settings.conflict_agent_class,
        AgentKey.RULE_EVALUATION: getattr(settings, "rule_agent_class", None)
        or settings.reasoning_agent_class,
        AgentKey.SUMMARY_GENERATION: getattr(settings, "summary_agent_class", None)
        or settings.reasoning_agent_class,
    }
    for key, demo_cls, method in demo_wiring:
        class_path = class_paths.get(key)
        if class_path:
            try:
                instance = _load_class(class_path)()
                registry.register_legacy(key, instance, method=method, source="custom", replace=True)
            except Exception as exc:  # noqa: BLE001
                registry.record_configuration_error(key, f"Could not load agent: {type(exc).__name__}")
                log.error("Failed to load %s agent (%s)", key.value, type(exc).__name__)
        elif settings.enable_demo_agents:
            registry.register_legacy(key, demo_cls(), method=method, source="demo", replace=True)
    return registry
