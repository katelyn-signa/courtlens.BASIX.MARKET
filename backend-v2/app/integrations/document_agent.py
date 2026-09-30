"""Person 1 integration point.

Replace ``DemoDocumentAgent`` with the real module by setting, e.g.
``DOCUMENT_AGENT_CLASS=person1_pkg.agent:DocumentIntelligenceAgent`` (no-arg constructor) or by
calling ``registry.register("document_intelligence", MyAgent())``.

``DemoDocumentAgent`` is SIMULATED: it invents deterministic synthetic facts so the backend can
be exercised end-to-end. Everything it emits carries ``is_simulated=True`` and a
``[SIMULATED]`` quotation. It performs no OCR and reads no file content.
"""

import hashlib
from datetime import date, timedelta

from app.orchestration.contracts import (
    AgentResultStatus, DocumentAgentInput, DocumentAgentOutput, DocumentProcessingResult,
    DocumentResultStatus, ExtractedFact,
)
from app.models.enums import FactType, VerificationStatus


class DemoDocumentAgent:
    name = "demo-document-agent"
    version = "0.0-simulated"

    def extract(self, request: DocumentAgentInput) -> DocumentAgentOutput:
        facts: list[ExtractedFact] = []
        results: list[DocumentProcessingResult] = []
        for doc in request.documents:
            seed = int(hashlib.sha256(doc.checksum_sha256.encode()).hexdigest()[:6], 16)
            arrest = date(2024, 1, 1) + timedelta(days=seed % 200)
            common = {"source_document_id": doc.document_id, "source_page": 1,
                      "confidence": 0.5, "provenance": {"simulated": True}}
            facts.append(ExtractedFact(
                fact_type=FactType.ARREST_DATE, value={"date": arrest.isoformat()},
                quote="[SIMULATED] synthetic arrest date", char_start=0, char_end=32,
                verification_status=VerificationStatus.UNVERIFIED, **common))
            facts.append(ExtractedFact(
                fact_type=FactType.FIR_REFERENCE, value={"reference": f"SIM-FIR-{seed % 1000:03d}"},
                quote="[SIMULATED] synthetic FIR reference",
                verification_status=VerificationStatus.UNVERIFIED, **common))
            results.append(DocumentProcessingResult(document_id=doc.document_id,
                                                    status=DocumentResultStatus.SUCCESS))
        return DocumentAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, facts=facts, document_results=results)
