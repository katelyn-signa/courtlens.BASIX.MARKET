"""OCR stage: PDF text layer and image placeholder extraction (no legal interpretation)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from app.orchestration.contracts import (
    AgentIssue, AgentResultStatus, DocumentResultStatus, OcrAgentInput, OcrAgentOutput,
    OcrDocumentResult, OcrPageResult,
)

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _extract_pdf(path: Path) -> tuple[list[OcrPageResult], str, float]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF OCR") from exc
    reader = PdfReader(str(path))
    pages: list[OcrPageResult] = []
    chunks: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append(OcrPageResult(page=idx, text=text, confidence=0.85 if text else 0.2))
        chunks.append(text)
    full = "\n\n".join(chunks)
    conf = 0.85 if full.strip() else 0.25
    return pages, full, conf


def _extract_image(path: Path, seed: int) -> tuple[list[OcrPageResult], str, float]:
    # Without Tesseract we store a deterministic placeholder so downstream stages can run in demo mode.
    note = f"[OCR PLACEHOLDER image hash={seed % 10000:04d}]"
    page = OcrPageResult(page=1, text=note, confidence=0.35)
    return [page], note, 0.35


class DemoOcrAgent:
    name = "demo-ocr-agent"
    version = "0.1-simulated"

    def run_ocr(self, request: OcrAgentInput) -> OcrAgentOutput:
        results: list[OcrDocumentResult] = []
        for doc in request.documents:
            path_str = doc.content_path
            if not path_str:
                seed = int(hashlib.sha256(doc.checksum_sha256.encode()).hexdigest()[:6], 16)
                text = f"[SIMULATED OCR] no file for {doc.filename} seed={seed}"
                results.append(OcrDocumentResult(
                    document_id=doc.document_id, status=DocumentResultStatus.SUCCESS,
                    pages=[OcrPageResult(page=1, text=text, confidence=0.4)], full_text=text,
                    confidence=0.4))
                continue
            path = Path(path_str)
            ext = path.suffix.lower()
            try:
                if ext == ".pdf":
                    pages, full, conf = _extract_pdf(path)
                elif ext in _IMAGE_EXT:
                    seed = int(hashlib.sha256(doc.checksum_sha256.encode()).hexdigest()[:6], 16)
                    pages, full, conf = _extract_image(path, seed)
                else:
                    full = path.read_text(encoding="utf-8", errors="replace")[:500_000]
                    pages = [OcrPageResult(page=1, text=full, confidence=0.7)]
                    conf = 0.7
                results.append(OcrDocumentResult(
                    document_id=doc.document_id, status=DocumentResultStatus.SUCCESS,
                    pages=pages, full_text=full, confidence=conf))
            except Exception as exc:  # noqa: BLE001
                results.append(OcrDocumentResult(
                    document_id=doc.document_id, status=DocumentResultStatus.FAILED,
                    error=AgentIssue(code="OCR_FAILED", message=str(type(exc).__name__)[:200])))
        return OcrAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, document_results=results)
