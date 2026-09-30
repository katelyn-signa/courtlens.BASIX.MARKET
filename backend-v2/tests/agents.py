"""Test agents used to exercise failure paths (real adapters stay untouched)."""

import time

from app.integrations.conflict_agent import DemoConflictAgent
from app.integrations.evidence_agent import DemoEvidenceAgent
from app.integrations.ocr_agent import DemoOcrAgent
from app.integrations.rule_agent import DemoRuleAgent
from app.integrations.summary_agent import DemoSummaryAgent
from app.orchestration.contracts import (
    AgentProcessingError, AgentUnavailableError, ConflictAgentOutput, ConflictFinding,
    AgentResultStatus,
)
from app.models.enums import ConflictType
from app.orchestration.registry import AgentKey, AgentRegistry

SENTINEL = "SENSITIVE-DOCUMENT-TEXT-XYZZY"

_DEFAULT_METHODS = {
    AgentKey.OCR: ("run_ocr", DemoOcrAgent),
    AgentKey.EVIDENCE_EXTRACTION: ("extract", DemoEvidenceAgent),
    AgentKey.CONFLICT_DETECTION: ("analyze", DemoConflictAgent),
    AgentKey.RULE_EVALUATION: ("evaluate", DemoRuleAgent),
    AgentKey.SUMMARY_GENERATION: ("summarize", DemoSummaryAgent),
}


def full_registry(**overrides) -> AgentRegistry:
    reg = AgentRegistry()
    alias = {
        "ocr": AgentKey.OCR,
        "document": AgentKey.OCR,
        "document_intelligence": AgentKey.OCR,
        "evidence": AgentKey.EVIDENCE_EXTRACTION,
        "conflict": AgentKey.CONFLICT_DETECTION,
        "rule": AgentKey.RULE_EVALUATION,
        "reasoning": AgentKey.RULE_EVALUATION,
        "summary": AgentKey.SUMMARY_GENERATION,
    }
    chosen = dict(overrides)
    for key, (method, default_cls) in _DEFAULT_METHODS.items():
        inner = None
        for name, mapped in alias.items():
            if mapped == key and name in chosen:
                inner = chosen.pop(name)
                break
        reg.register_legacy(key, inner or default_cls(), method=method, source="demo")
    return reg


class RecordingAgent:
    """Wraps an agent and records the call order in a shared list."""

    def __init__(self, inner, method, order, label):
        self.inner, self.order, self.label = inner, order, label
        self.name, self.version = inner.name, inner.version
        self._method = method

    def execute(self, request):
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


class StubSummaryAgent:
    name, version = "stub-summary", "1"

    def summarize(self, request):
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


class FlakyRuleAgent:
    name, version = "flaky-rule", "1"

    def __init__(self):
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        if self.calls == 1:
            raise AgentProcessingError("first attempt fails")
        return DemoRuleAgent().evaluate(request)
