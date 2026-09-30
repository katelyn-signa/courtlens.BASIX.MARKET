import re

from app.schemas.document_classification import (
    DocumentClassificationResult,
    DocumentType,
)

SIGNALS: dict[DocumentType, tuple[tuple[str, int], ...]] = {
    "contract": (
        ("contract", 4),
        ("agreement", 3),
        ("terms and conditions", 3),
        ("obligations", 2),
        ("effective date", 2),
        ("contract amount", 2),
        ("seller:", 1),
        ("buyer:", 1),
    ),
    "purchase_order": (
        ("purchase order", 4),
        ("po number", 4),
        ("order quantity", 3),
        ("quantity ordered", 2),
    ),
    "invoice": (
        ("tax invoice", 5),
        ("invoice number", 5),
        ("invoice", 4),
        ("bill to", 2),
        ("total amount", 1),
        ("amount due", 2),
    ),
    "payment_record": (
        ("bank transaction", 5),
        ("payment reference", 5),
        ("transaction id", 4),
        ("amount paid", 3),
        ("paid", 2),
        ("payment", 1),
    ),
    "delivery_receipt": (
        ("delivery receipt", 5),
        ("goods received", 5),
        ("received by", 3),
        ("delivery date", 2),
        ("delivered", 2),
    ),
    "email": (
        ("from:", 3),
        ("to:", 3),
        ("subject:", 3),
        ("sent:", 2),
        ("dear ", 2),
        ("email", 2),
    ),
    "court_order": (
        ("hereby ordered", 5),
        ("court order", 5),
        ("listed for hearing", 4),
        ("matter is listed", 3),
        ("hearing on", 2),
        ("petitioner", 3),
        ("respondent", 3),
        ("judge", 2),
        ("disposed", 2),
    ),
    "advocate_note": (("advocate note", 5), ("counsel note", 4)),
    "party_document": (("party submitted document", 5), ("party document", 4)),
    "claim_statement": (
        ("statement of claim", 5),
        ("relief sought", 5),
        ("claimant", 4),
        ("disputed amount", 3),
        ("alleges", 3),
        ("claim", 2),
    ),
}

MINIMUM_CLASSIFICATION_SCORE = 3


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def classify_document(text: str) -> DocumentClassificationResult:
    normalized_text = _normalize_text(text)
    scores: dict[DocumentType, int] = {}
    matches: dict[DocumentType, list[str]] = {}

    for document_type, signals in SIGNALS.items():
        category_matches = [
            (signal, weight)
            for signal, weight in signals
            if signal in normalized_text
        ]
        scores[document_type] = sum(weight for _, weight in category_matches)
        matches[document_type] = [signal for signal, _ in category_matches]

    best_score = max(scores.values(), default=0)
    if best_score == 0:
        return DocumentClassificationResult(
            document_type="other",
            confidence=0.0,
            matched_signals=[],
        )

    strongest = [
        category for category, score in scores.items() if score == best_score
    ]
    if best_score < MINIMUM_CLASSIFICATION_SCORE:
        return DocumentClassificationResult(
            document_type="other",
            confidence=min(0.45, best_score * 0.12),
            matched_signals=matches[strongest[0]],
        )

    if len(strongest) > 1:
        tied_signals = [
            signal
            for category in strongest
            for signal in matches[category]
        ]
        return DocumentClassificationResult(
            document_type="other",
            confidence=0.4,
            matched_signals=tied_signals,
        )

    document_type = strongest[0]
    runner_up_score = max(
        (score for category, score in scores.items() if category != document_type),
        default=0,
    )
    margin = best_score - runner_up_score
    confidence = min(
        0.99,
        0.35 + min(best_score, 10) * 0.04 + min(margin, 5) * 0.035,
    )
    return DocumentClassificationResult(
        document_type=document_type,
        confidence=confidence,
        matched_signals=matches[document_type],
    )