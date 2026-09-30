"""Evidence extraction from OCR text (structured entities with provenance)."""

import hashlib
import re
from datetime import date, timedelta

from app.models.enums import FactType, VerificationStatus
from app.orchestration.contracts import (
    AgentResultStatus, DocumentProcessingResult, DocumentResultStatus, EvidenceAgentInput,
    EvidenceAgentOutput, ExtractedFact,
)

_ENTITY_PATTERNS: list[tuple[FactType, str, str]] = [
    (FactType.FIR_REFERENCE, r"\bFIR[\s\-/]*(?:No\.?|Number)?[\s\-/]*([A-Za-z0-9/\-]+)", "FIR"),
    (FactType.STATUTORY_SECTION, r"\b(?:IPC|Section)\s*(\d+[A-Za-z]?)", "IPC section"),
]


class DemoEvidenceAgent:
    name = "demo-evidence-agent"
    version = "0.1-simulated"

    def extract(self, request: EvidenceAgentInput) -> EvidenceAgentOutput:
        facts: list[ExtractedFact] = []
        results: list[DocumentProcessingResult] = []
        for doc in request.documents:
            ocr = request.ocr_by_document_id.get(doc.document_id) or {}
            text = str(ocr.get("full_text") or "")
            seed = int(hashlib.sha256(doc.checksum_sha256.encode()).hexdigest()[:6], 16)
            if not text.strip():
                text = f"synthetic-{seed}"
            common = {
                "source_document_id": doc.document_id,
                "source_page": 1,
                "confidence": float(ocr.get("confidence") or 0.5),
                "provenance": {
                    "document": doc.document_id,
                    "page": 1,
                    "paragraph": 1,
                    "confidence": float(ocr.get("confidence") or 0.5),
                    "simulated": True,
                },
            }
            arrest = date(2024, 1, 1) + timedelta(days=seed % 200)
            facts.append(ExtractedFact(
                fact_type=FactType.ARREST_DATE, value={"date": arrest.isoformat()},
                quote=text[:120] or "[SIMULATED] arrest date",
                char_start=0, char_end=min(32, len(text)),
                verification_status=VerificationStatus.UNVERIFIED, **common))
            for fact_type, pattern, label in _ENTITY_PATTERNS:
                match = re.search(pattern, text, re.I)
                if fact_type == FactType.FIR_REFERENCE:
                    val = match.group(1) if match else f"SIM-FIR-{seed % 1000:03d}"
                    facts.append(ExtractedFact(
                        fact_type=fact_type, value={"reference": val},
                        quote=match.group(0)[:200] if match else f"[SIMULATED] {label}",
                        verification_status=VerificationStatus.UNVERIFIED, **common))
                elif match:
                    facts.append(ExtractedFact(
                        fact_type=fact_type, value={"section": match.group(1)},
                        quote=match.group(0)[:200],
                        verification_status=VerificationStatus.UNVERIFIED, **common))
            # Witness / location / weapon placeholders when keywords appear
            if re.search(r"\bwitness\b", text, re.I):
                facts.append(ExtractedFact(
                    fact_type=FactType.OTHER, value={"entity": "witness", "label": "witness mention"},
                    category="witness", entity_ref="witness_1",
                    quote="witness", verification_status=VerificationStatus.UNVERIFIED, **common))
            results.append(DocumentProcessingResult(document_id=doc.document_id,
                                                    status=DocumentResultStatus.SUCCESS))
        return EvidenceAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, facts=facts, document_results=results)
