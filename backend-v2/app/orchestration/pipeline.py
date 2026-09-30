"""Configurable pipeline definition. Change the workflow here, not in the orchestrator."""

from dataclasses import dataclass

from app.core.exceptions import InvalidInputError
from app.orchestration.registry import AGENT_METHODS, AgentKey


@dataclass(frozen=True)
class StageDefinition:
    name: str
    agent_key: AgentKey
    required: bool = True
    depends_on: tuple[str, ...] = ()

    @property
    def method(self) -> str:
        return AGENT_METHODS[self.agent_key]


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
        raise InvalidInputError(f"Unknown module {name!r}.", details={"available": self.names()})

    def resolve(self, requested: list[str] | None) -> list[StageDefinition]:
        """Requested modules plus their dependencies, in pipeline order."""
        if not requested:
            return list(self.stages)
        wanted: set[str] = set()

        def add(name: str) -> None:
            stage = self.get(name)
            for dep in stage.depends_on:
                add(dep)
            wanted.add(stage.name)

        for name in requested:
            add(name)
        return [s for s in self.stages if s.name in wanted]


DEFAULT_PIPELINE = PipelineDefinition(
    version="1.0",
    stages=(
        StageDefinition("document_intelligence", AgentKey.DOCUMENT_INTELLIGENCE),
        StageDefinition("conflict_detection", AgentKey.CONFLICT_DETECTION,
                        depends_on=("document_intelligence",)),
        StageDefinition("reasoning", AgentKey.REASONING, depends_on=("conflict_detection",)),
    ),
)
