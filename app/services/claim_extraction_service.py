import re

from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import DocumentType
from app.schemas.evidence import ClaimType, ExtractedClaim

CLAIM_INDICATORS = re.compile(
    r"\b(?:claims?\s+that|states?\s+that|alleges?\s+that|asserts?\s+that|"
    r"according\s+to|we\s+have\s+paid|payment\s+was\s+made|"
    r"amount\s+was\s+adjusted|goods\s+were\s+delivered|"
    r"goods\s+were\s+not\s+delivered|we\s+did\s+not\s+receive|we\s+received)\b",
    re.IGNORECASE,
)
CLAIMANT_PATTERN = re.compile(
    r"^\s*(?P<claimant>[A-Z][A-Za-z0-9&.,' -]*?)\s+"
    r"(?:claims?|states?|alleges?|asserts?)\s+that\b",
    re.IGNORECASE,
)
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _classify_claim(sentence: str) -> ClaimType:
    text = sentence.casefold()
    if "adjust" in text or "credit note" in text:
        return "adjustment_claim"
    if "breach" in text or "breached" in text:
        return "breach_claim"
    if any(phrase in text for phrase in ("not delivered", "did not receive", "not receive", "never received")):
        return "non_delivery_claim"
    if any(phrase in text for phrase in ("not paid", "did not pay", "unpaid", "non-payment")):
        return "non_payment_claim"
    if any(phrase in text for phrase in ("goods were delivered", "we received", "goods received")):
        return "delivery_claim"
    if any(phrase in text for phrase in ("payment", "paid", "amount paid")):
        return "payment_claim"
    if any(phrase in text for phrase in ("amount", "disputed", "balance")):
        return "amount_claim"
    if any(phrase in text for phrase in ("obligation", "obliged", "shall")):
        return "contractual_obligation_claim"
    return "general_statement"


def extract_claims(
    document: DocumentExtractionResult,
    document_type: DocumentType,
) -> list[ExtractedClaim]:
    claims = []
    for page in document.pages:
        for line in page.text.splitlines():
            for sentence in SENTENCE_PATTERN.split(line.strip()):
                sentence = sentence.strip()
                if not sentence or CLAIM_INDICATORS.search(sentence) is None:
                    continue

                claimant_match = CLAIMANT_PATTERN.match(sentence)
                claimant = claimant_match.group("claimant").strip() if claimant_match else None
                normalized_claim = " ".join(sentence.split())
                claims.append(
                    ExtractedClaim(
                        claim_id=f"C{len(claims) + 1:04d}",
                        claimant=claimant,
                        claim_type=_classify_claim(sentence),
                        claim_text=sentence,
                        normalized_claim=normalized_claim,
                        document_id=document.document_id,
                        document_type=document_type,
                        page=page.page,
                        quote=sentence,
                        confidence=0.92 if claimant_match else 0.82,
                    )
                )
    return claims