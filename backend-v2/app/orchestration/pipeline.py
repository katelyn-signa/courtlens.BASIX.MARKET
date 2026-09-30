"""Configurable pipeline definition. Change the workflow here, not in the orchestrator."""

from dataclasses import dataclass

from app.core.exceptions import InvalidInputError
from app.orchestration.registry import AGENT_METHOD, AgentKey


# Public module names accepted in ``requested_modules`` (includes legacy aliases).
MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "document_intelligence": ("ocr", "evidence_extraction"),
    "reasoning": ("rule_evaluation", "summary_generation"),
}


@dataclass(frozen=True)
class StageDefinition:
    name: str
    agent_key: AgentKey
    required: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def method(self) -> str:
        return AGENT_METHOD


@dataclass(frozen=True)
class PipelineDefinition:
    version: str
    stages: tuple[StageDefinition, ...]

    def names(self) -> list[str]:
        return [s.name for s in self.stages]

    def get(self, name: str) -> StageDefinition:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise InvalidInputError(f"Unknown module {name!r}.", details={"available": self.public_modules()})

    def public_modules(self) -> list[str]:
        return self.names() + list(MODULE_ALIASES.keys())

    def resolve(self, requested: list[str] | None) -> list[StageDefinition]:
        """Requested modules plus dependencies, in pipeline order."""
        if not requested:
            return list(self.stages)
        wanted: set[str] = set()

        def add(name: str) -> None:
            if name in MODULE_ALIASES:
                for part in MODULE_ALIASES[name]:
                    add(part)
                return
            stage = self.get(name)
            for dep in stage.depends_on:
                add(dep)
            wanted.add(stage.name)

        for name in requested:
            add(name)
        return [s for s in self.stages if s.name in wanted]


DEFAULT_PIPELINE = PipelineDefinition(
    version="2.0",
    stages=(
        StageDefinition("ocr", AgentKey.OCR),
        StageDefinition("evidence_extraction", AgentKey.EVIDENCE_EXTRACTION, depends_on=("ocr",)),
        StageDefinition("conflict_detection", AgentKey.CONFLICT_DETECTION,
                        depends_on=("evidence_extraction",)),
        StageDefinition("rule_evaluation", AgentKey.RULE_EVALUATION,
                        depends_on=("conflict_detection",)),
        StageDefinition("summary_generation", AgentKey.SUMMARY_GENERATION,
                        depends_on=("rule_evaluation",)),
    ),
)
