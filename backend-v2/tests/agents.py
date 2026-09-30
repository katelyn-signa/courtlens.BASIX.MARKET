"""Test agents used to exercise failure paths (real adapters stay untouched)."""

import time

from app.integrations.conflict_agent import DemoConflictAgent
from app.integrations.document_agent import DemoDocumentAgent
from app.integrations.reasoning_agent import DemoReasoningAgent
from app.orchestration.contracts import (
    AgentProcessingError, AgentUnavailableError, ConflictAgentOutput, ConflictFinding,
    AgentResultStatus,
)
from app.models.enums import ConflictType
from app.orchestration.registry import AgentRegistry

SENTINEL = "SENSITIVE-DOCUMENT-TEXT-XYZZY"


def full_registry(**overrides) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register("document_intelligence", overrides.get("document") or DemoDocumentAgent())
    reg.register("conflict_detection", overrides.get("conflict") or DemoConflictAgent())
    reg.register("reasoning", overrides.get("reasoning") or DemoReasoningAgent())
    return reg


class RecordingAgent:
    """Wraps an agent and records the call order in a shared list."""
    def __init__(self, inner, method, order, label):
        self.inner, self.order, self.label = inner, order, label
        self.name, self.version = inner.name, inner.version
        setattr(self, method, self._call)
        self._method = method

    def _call(self, request):
        self.order.append(self.label)
        return getattr(self.inner, self._method)(request)


class FailingConflictAgent:
    name, version = "failing-conflict", "1"
    def analyze(self, request):
        raise AgentProcessingError("boom")


class UnavailableConflictAgent:
    name, version = "unavailable-conflict", "1"
    def __init__(self, fail_times):
        self.fail_times, self.calls = fail_times, 0
    def analyze(self, request):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise AgentUnavailableError("down")
        return DemoConflictAgent().analyze(request)


class SlowConflictAgent:
    name, version = "slow-conflict", "1"
    def analyze(self, request):
        time.sleep(0.5)
        return DemoConflictAgent().analyze(request)


class StubReasoningAgent:
    name, version = "stub-reasoning", "1"
    def evaluate(self, request):
        raise NotImplementedError


class InvalidOutputConflictAgent:
    """Returns a finding that references an evidence id that does not exist."""
    name, version = "invalid-conflict", "1"
    def analyze(self, request):
        return ConflictAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            findings=[ConflictFinding(
                finding_type=ConflictType.CONTRADICTION, description="x",
                related_evidence_ids=["evd_" + "0" * 21])])


class LeakyFailingAgent:
    """Fails with a message containing 'document text' via an unexpected exception."""
    name, version = "leaky", "1"
    def analyze(self, request):
        raise RuntimeError(SENTINEL)


class FlakyReasoningAgent:
    name, version = "flaky-reasoning", "1"
    def __init__(self):
        self.calls = 0
    def evaluate(self, request):
        self.calls += 1
        if self.calls == 1:
            raise AgentProcessingError("first attempt fails")
        return DemoReasoningAgent().evaluate(request)
