import re
from dataclasses import dataclass

from app.schemas.conflict import Conflict
from app.schemas.document import DocumentExtractionResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievalResult
from app.schemas.retrieval import CaseEvidenceSearchRequest

RESULT_TYPE_ORDER = {
    "evidence": 0,
    "fact": 1,
    "claim": 2,
    "conflict": 3,
    "evidence_gap": 4,
    "document_passage": 5,
}


@dataclass
class _Candidate:
    result: RetrievalResult
    searchable_fields: list[tuple[str, float]]
    source_text: str


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _score(query: str, fields: list[tuple[str, float]]) -> float:
    normalized_query = _normalize(query)
    terms = normalized_query.split()
    if not terms:
        return 0.0

    normalized_fields = [(_normalize(text), weight) for text, weight in fields if text]
    if not normalized_fields:
        return 0.0

    term_strengths = []
    for term in terms:
        best_strength = 0.0
        for text, weight in normalized_fields:
            words = text.split()
            if term in words:
                best_strength = max(best_strength, weight)
            elif any(term in word for word in words):
                best_strength = max(best_strength, weight * 0.35)
        term_strengths.append(min(1.0, best_strength))

    coverage = sum(term_strengths) / len(terms)
    phrase_match = any(
        f" {normalized_query} " in f" {text} "
        for text, _ in normalized_fields
    )
    score = 0.75 * coverage + (0.25 if phrase_match else 0.0)
    return round(min(1.0, score), 4)


def _snippet(source_text: str, query: str, max_length: int = 240) -> str:
    text = source_text.strip()
    if len(text) <= max_length:
        return text

    lowered = text.casefold()
    positions = [position for term in _normalize(query).split() if (position := lowered.find(term)) >= 0]
    start = max(0, (min(positions) if positions else 0) - max_length // 3)
    end = min(len(text), start + max_length)
    snippet = text[start:end].strip()
    if start:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def _rank_candidate(query: str, candidate: _Candidate) -> RetrievalResult | None:
    score = _score(query, candidate.searchable_fields)
    if score <= 0:
        return None
    return candidate.result.model_copy(
        update={"score": score, "snippet": _snippet(candidate.source_text, query)}
    )


def _document_index(documents: list[DocumentExtractionResult]) -> dict[str, DocumentExtractionResult]:
    return {document.document_id: document for document in documents}


def _record_candidates(
    request: RetrievalRequest,
    documents: dict[str, DocumentExtractionResult],
) -> list[_Candidate]:
    candidates = []
    evidence_by_fact = {
        (item.document_id, item.fact_id): item
        for item in request.evidence
        if item.fact_id
    }

    for fact in request.facts:
        evidence = evidence_by_fact.get((fact.document_id, fact.fact_id))
        document = documents.get(fact.document_id or "")
        quote = fact.quote
        title = fact.field.replace("_", " ").title()
        result_id = f"fact:{fact.document_id or 'unknown'}:{fact.fact_id}"
        candidates.append(
            _Candidate(
                RetrievalResult(
                    result_id=result_id,
                    result_type="fact",
                    score=0,
                    title=title,
                    snippet="",
                    document_id=fact.document_id,
                    filename=document.filename if document else None,
                    page=fact.page,
                    quote=quote,
                    normalized_value=fact.normalized_value,
                    fact_id=fact.fact_id,
                    evidence_id=evidence.evidence_id if evidence else None,
                    confidence=fact.confidence,
                    extraction_method=fact.extraction_method,
                ),
                searchable_fields=[
                    (title, 1.0),
                    (fact.fact_type, 0.9),
                    (fact.value, 0.9),
                    (str(fact.normalized_value), 0.8),
                    (quote, 1.0),
                    (document.filename if document else "", 0.6),
                ],
                source_text=quote or fact.value,
            )
        )

    for item in request.evidence:
        document = documents.get(item.document_id)
        title = f"{item.evidence_type.replace('_', ' ').title()} evidence"
        candidates.append(
            _Candidate(
                RetrievalResult(
                    result_id=f"evidence:{item.document_id}:{item.evidence_id}",
                    result_type="evidence",
                    score=0,
                    title=title,
                    snippet="",
                    document_id=item.document_id,
                    filename=document.filename if document else None,
                    page=item.page,
                    quote=item.quote,
                    normalized_value=item.normalized_value,
                    fact_id=item.fact_id,
                    evidence_id=item.evidence_id,
                    confidence=item.confidence,
                    extraction_method=item.extraction_method,
                ),
                searchable_fields=[
                    (title, 1.0),
                    (item.evidence_type, 0.9),
                    (item.document_type, 0.8),
                    (str(item.normalized_value) if item.normalized_value is not None else "", 0.8),
                    (item.quote, 1.0),
                    (document.filename if document else "", 0.6),
                ],
                source_text=item.quote,
            )
        )

    for claim in request.claims:
        document = documents.get(claim.document_id)
        title = f"{claim.claim_type.replace('_', ' ').title()}"
        candidates.append(
            _Candidate(
                RetrievalResult(
                    result_id=f"claim:{claim.document_id}:{claim.claim_id}",
                    result_type="claim",
                    score=0,
                    title=title,
                    snippet="",
                    document_id=claim.document_id,
                    filename=document.filename if document else None,
                    page=claim.page,
                    quote=claim.quote,
                    claim_id=claim.claim_id,
                    related_evidence_ids=claim.supporting_evidence_ids,
                    confidence=claim.confidence,
                ),
                searchable_fields=[
                    (title, 1.0),
                    (claim.claim_type, 0.9),
                    (claim.claimant or "", 0.8),
                    (claim.status, 0.7),
                    (claim.claim_text, 1.0),
                    (claim.normalized_claim, 0.9),
                    (claim.quote, 1.0),
                    (document.filename if document else "", 0.6),
                ],
                source_text=claim.quote,
            )
        )

    for conflict in request.conflicts:
        quote = "\n".join(conflict.quotes)
        document_ids = conflict.document_ids
        document_id = document_ids[0] if len(document_ids) == 1 else None
        document = documents.get(document_id or "")
        title = f"{conflict.conflict_type.replace('_', ' ').title()}"
        candidates.append(
            _Candidate(
                RetrievalResult(
                    result_id=f"conflict:{conflict.conflict_id}",
                    result_type="conflict",
                    score=0,
                    title=title,
                    snippet="",
                    document_id=document_id,
                    document_ids=document_ids,
                    filename=document.filename if document else None,
                    page=conflict.source_pages[0] if len(conflict.source_pages) == 1 else None,
                    source_pages=conflict.source_pages,
                    quote=quote or None,
                    conflict_id=conflict.conflict_id,
                    related_evidence_ids=conflict.evidence_ids,
                    related_claim_ids=conflict.claim_ids,
                    confidence=conflict.confidence,
                ),
                searchable_fields=[
                    (title, 1.0),
                    (conflict.conflict_type, 0.9),
                    (conflict.fact_type, 0.8),
                    (conflict.description, 1.0),
                    (quote, 1.0),
                ],
                source_text=quote or conflict.description,
            )
        )

    for gap in request.gaps:
        quote = "\n".join(gap.quotes)
        document_ids = gap.related_document_ids
        document_id = document_ids[0] if len(document_ids) == 1 else None
        document = documents.get(document_id or "")
        title = f"{gap.gap_type.replace('_', ' ').title()}"
        candidates.append(
            _Candidate(
                RetrievalResult(
                    result_id=f"gap:{gap.gap_id}",
                    result_type="evidence_gap",
                    score=0,
                    title=title,
                    snippet="",
                    document_id=document_id,
                    document_ids=document_ids,
                    filename=document.filename if document else None,
                    page=gap.source_pages[0] if len(gap.source_pages) == 1 else None,
                    source_pages=gap.source_pages,
                    quote=quote or None,
                    gap_id=gap.gap_id,
                    related_evidence_ids=gap.related_evidence_ids,
                    related_claim_ids=gap.related_claim_ids,
                    related_conflict_ids=gap.related_conflict_ids,
                    confidence=gap.confidence,
                ),
                searchable_fields=[
                    (title, 1.0),
                    (gap.gap_type, 0.9),
                    (gap.description, 1.0),
                    (gap.reason, 0.9),
                    (" ".join(gap.suggested_evidence), 0.7),
                    (quote, 1.0),
                ],
                source_text=quote or gap.description,
            )
        )
    return candidates


def _passage_candidates(
    documents: list[DocumentExtractionResult],
) -> list[_Candidate]:
    candidates = []
    for document in documents:
        for page in document.pages:
            title = f"{document.filename} - Page {page.page}"
            candidates.append(
                _Candidate(
                    RetrievalResult(
                        result_id=f"document:{document.document_id}:page:{page.page}",
                        result_type="document_passage",
                        score=0,
                        title=title,
                        snippet="",
                        document_id=document.document_id,
                        filename=document.filename,
                        page=page.page,
                        quote=page.text,
                        extraction_method=page.extraction_method,
                    ),
                    searchable_fields=[
                        (title, 1.0),
                        (document.filename, 0.7),
                        (page.text, 1.0),
                    ],
                    source_text=page.text,
                )
            )
    return candidates


def search(request: RetrievalRequest) -> RetrievalResponse:
    documents = _document_index(request.documents)
    candidates = _record_candidates(request, documents)
    candidates.extend(_passage_candidates(request.documents))

    results = [
        result
        for candidate in candidates
        if (result := _rank_candidate(request.query, candidate)) is not None
    ]
    results.sort(
        key=lambda result: (
            -result.score,
            RESULT_TYPE_ORDER[result.result_type],
            result.document_id or "",
            result.page or 0,
            result.result_id,
        )
    )
    total = len(results)
    return RetrievalResponse(
        query=request.query,
        results=results[: request.top_k],
        total=total,
    )


def search_case_evidence(state, request: CaseEvidenceSearchRequest) -> RetrievalResponse:
    claim = next(
        (item for item in state.claims if item.claim_id == request.claim_id),
        None,
    ) if request.claim_id else None
    fact = next(
        (item for item in state.facts if item.fact_id == request.fact_id),
        None,
    ) if request.fact_id else None
    if request.claim_id and claim is None:
        raise ValueError(f"Claim '{request.claim_id}' is not present in this case.")
    if request.fact_id and fact is None:
        raise ValueError(f"Fact '{request.fact_id}' is not present in this case.")

    query_parts = [request.query or ""]
    if claim is not None:
        query_parts.append(claim.claim_text)
    if fact is not None:
        query_parts.extend((fact.field.replace("_", " "), fact.value, fact.quote))
    query = " ".join(part for part in query_parts if part).strip()
    if not query:
        raise ValueError("The selected case item has no searchable text.")

    response = search(
        RetrievalRequest(
            query=query,
            top_k=100,
            facts=state.facts,
            evidence=state.evidence,
            claims=state.claims,
            conflicts=state.conflicts,
            gaps=state.evidence_gaps,
        )
    )
    filenames = {item.document_id: item.filename for item in state.documents}
    evidence_results = [
        item.model_copy(update={"filename": filenames.get(item.document_id or "")})
        for item in response.results
        if item.result_type == "evidence"
    ]
    linked_evidence_ids = set(claim.supporting_evidence_ids if claim else [])
    if fact is not None:
        linked_evidence_ids.update(
            item.evidence_id
            for item in state.evidence
            if item.fact_id == fact.fact_id and item.document_id == fact.document_id
        )
    evidence_results.sort(
        key=lambda item: (
            item.evidence_id not in linked_evidence_ids,
            -item.score,
            item.document_id or "",
            item.page or 0,
            item.result_id,
        )
    )
    return RetrievalResponse(
        query=query,
        results=evidence_results[: request.top_k],
        total=len(evidence_results),
    )