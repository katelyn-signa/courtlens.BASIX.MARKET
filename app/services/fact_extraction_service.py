import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.document_classification import (
    DocumentClassificationResult,
    DocumentType,
)
from app.schemas.facts import ExtractedFact, FactExtractionResult, FactType, FactValue
from app.services.document_classifier import classify_document


class FactExtractionError(ValueError):
    """Raised when a document has no usable page text or valid provenance."""


@dataclass(frozen=True)
class LabelRule:
    fact_type: FactType
    field: str
    labels: tuple[str, ...]
    value_kind: str = "text"
    confidence: float = 0.98


PARTY_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "contract": (LabelRule("party", "seller", ("Seller",)), LabelRule("party", "buyer", ("Buyer",))),
    "invoice": (LabelRule("party", "seller", ("Seller", "From")), LabelRule("party", "buyer", ("Buyer", "Bill To", "To"))),
    "purchase_order": (LabelRule("party", "seller", ("Seller", "From")), LabelRule("party", "buyer", ("Buyer", "To"))),
    "payment_record": (LabelRule("party", "sender", ("Sender", "From")), LabelRule("party", "recipient", ("Recipient", "To"))),
    "delivery_receipt": (LabelRule("party", "seller", ("Seller",)), LabelRule("party", "buyer", ("Buyer",))),
    "email": (LabelRule("party", "sender", ("Sender", "From")), LabelRule("party", "recipient", ("Recipient", "To"))),
    "court_order": (LabelRule("party", "claimant", ("Claimant", "Petitioner")), LabelRule("party", "respondent", ("Respondent",))),
    "claim_statement": (LabelRule("party", "claimant", ("Claimant", "Petitioner")), LabelRule("party", "respondent", ("Respondent",))),
}

IDENTITY_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "contract": (LabelRule("identity", "case_id", ("Case ID", "Case Number", "Case No.")),),
    "invoice": (LabelRule("identity", "invoice_number", ("Invoice Number", "Invoice No.")),),
    "purchase_order": (LabelRule("identity", "purchase_order_number", ("Purchase Order Number", "Purchase Order No.", "PO Number", "PO No.")),),
    "payment_record": (LabelRule("identity", "transaction_id", ("Transaction ID", "Transaction Reference", "Payment Reference")),),
    "delivery_receipt": (LabelRule("identity", "delivery_reference", ("Delivery Reference", "Receipt Number", "Delivery Number")),),
    "court_order": (LabelRule("identity", "case_id", ("Case ID", "Case Number", "Case No.")),),
    "claim_statement": (LabelRule("identity", "case_id", ("Case ID", "Case Number", "Case No.")),),
}

FINANCIAL_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "contract": (LabelRule("financial", "contract_amount", ("Contract Amount", "Total Contract Amount"), "amount"),),
    "invoice": (
        LabelRule("financial", "invoice_amount", ("Invoice Amount", "Total Invoice Amount", "Total Amount"), "amount"),
        LabelRule("financial", "amount_due", ("Amount Due", "Balance Due"), "amount"),
    ),
    "purchase_order": (LabelRule("financial", "payment_amount", ("Order Amount",), "amount"),),
    "payment_record": (
        LabelRule("financial", "amount_paid", ("Amount Paid",), "amount"),
        LabelRule("financial", "payment_amount", ("Payment Amount",), "amount"),
    ),
    "claim_statement": (
        LabelRule("financial", "claimed_amount", ("Claimed Amount", "Claim Amount"), "amount"),
        LabelRule("financial", "disputed_amount", ("Disputed Amount",), "amount"),
    ),
}

DATE_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "contract": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "filing_date", ("Filing Date", "Date Filed"), "date"),
        LabelRule("date", "contract_date", ("Contract Date",), "date"),
        LabelRule("date", "effective_date", ("Effective Date",), "date"),
        LabelRule("date", "delivery_date", ("Delivery Date",), "date"),
        LabelRule("date", "payment_due_date", ("Payment Due Date", "Due Date"), "date"),
    ),
    "invoice": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "invoice_date", ("Invoice Date", "Date"), "date"),
        LabelRule("date", "payment_due_date", ("Payment Due Date", "Due Date"), "date"),
    ),
    "purchase_order": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "order_date", ("Order Date",), "date"),
        LabelRule("date", "delivery_date", ("Delivery Date",), "date"),
    ),
    "payment_record": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "payment_date", ("Payment Date", "Transaction Date", "Date"), "date"),
    ),
    "delivery_receipt": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "delivery_date", ("Delivery Date", "Date"), "date"),
    ),
    "email": (LabelRule("date", "email_date", ("Date", "Sent"), "date"),),
    "court_order": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "filing_date", ("Filing Date", "Date Filed"), "date"),
        LabelRule("date", "order_date", ("Order Date", "Date"), "date"),
    ),
    "advocate_note": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
    ),
    "party_document": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "filing_date", ("Filing Date", "Date Filed"), "date"),
    ),
    "claim_statement": (
        LabelRule("date", "document_date", ("Document Date",), "date"),
        LabelRule("date", "filing_date", ("Filing Date", "Date Filed"), "date"),
    ),
}

OBLIGATION_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "contract": (
        LabelRule("obligation", "payment_obligation", ("Payment Obligation",)),
        LabelRule("obligation", "delivery_obligation", ("Delivery Obligation",)),
    ),
}
CLAIM_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "claim_statement": (LabelRule("claim", "claim_description", ("Claim Description", "Relief Sought")),),
}
COMMUNICATION_RULES: dict[DocumentType, tuple[LabelRule, ...]] = {
    "email": (LabelRule("communication", "subject", ("Subject",)),),
}
RULE_GROUPS = (
    PARTY_RULES,
    IDENTITY_RULES,
    FINANCIAL_RULES,
    DATE_RULES,
    OBLIGATION_RULES,
    CLAIM_RULES,
    COMMUNICATION_RULES,
)

MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
    "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
DATE_VALUE_PATTERN = re.compile(
    rf"\b(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}\s+(?:{MONTH_NAMES})\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})\b",
    re.IGNORECASE,
)
AMOUNT_VALUE_PATTERN = re.compile(
    r"^\s*(?:(?P<prefix>INR|Rs\.?|₹)\s*)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<suffix>INR|Rs\.?)?\s*$",
    re.IGNORECASE,
)


def _label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    choices = "|".join(
        re.escape(label).replace(r"\ ", r"\s+")
        for label in sorted(labels, key=len, reverse=True)
    )
    return re.compile(
        rf"^\s*(?P<label>{choices})\s*[:#-]\s*(?P<value>.*?)\s*$",
        re.IGNORECASE,
    )


def _parse_amount(value: str) -> tuple[FactValue, str | None, float]:
    match = AMOUNT_VALUE_PATTERN.fullmatch(value)
    if match is None:
        return value, None, 0.6
    try:
        amount = Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return value, None, 0.6
    normalized: int | float = int(amount) if amount == amount.to_integral_value() else float(amount)
    currency_token = match.group("prefix") or match.group("suffix")
    return normalized, "INR" if currency_token else None, 0.98 if currency_token else 0.9


def _parse_date(value: str) -> tuple[str, float] | None:
    match = DATE_VALUE_PATTERN.search(value)
    if match is None:
        return None
    date_text = match.group(0)
    for date_format, confidence in (
        ("%Y-%m-%d", 0.98),
        ("%d %B %Y", 0.98),
        ("%d %b %Y", 0.96),
        ("%d/%m/%Y", 0.8),
    ):
        try:
            return datetime.strptime(date_text, date_format).date().isoformat(), confidence
        except ValueError:
            continue
    return None


def _make_fact(
    document: DocumentExtractionResult,
    page: DocumentPage,
    rule: LabelRule,
    value: str,
    quote: str,
    fact_number: int,
) -> ExtractedFact | None:
    normalized: FactValue = value
    currency = None
    confidence = rule.confidence
    if rule.value_kind == "amount":
        normalized, currency, confidence = _parse_amount(value)
    elif rule.value_kind == "date":
        parsed_date = _parse_date(value)
        if parsed_date is None:
            return None
        normalized, confidence = parsed_date

    return ExtractedFact(
        fact_id=f"F{fact_number:04d}",
        fact_type=rule.fact_type,
        field=rule.field,
        value=value,
        normalized_value=normalized,
        document_id=document.document_id,
        page=page.page,
        quote=quote,
        confidence=confidence,
        currency=currency,
        extraction_method=page.extraction_method,
    )


def _extract_labeled_facts(
    document: DocumentExtractionResult,
    page: DocumentPage,
    rules: tuple[LabelRule, ...],
    first_fact_number: int,
) -> list[ExtractedFact]:
    facts = []
    for rule in rules:
        pattern = _label_pattern(rule.labels)
        for line in page.text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            value = match.group("value").strip()
            if not value:
                continue
            fact = _make_fact(
                document,
                page,
                rule,
                value,
                match.group(0).strip(),
                first_fact_number + len(facts),
            )
            if fact is not None:
                facts.append(fact)
    return facts


def _extract_contract_obligations(
    document: DocumentExtractionResult,
    page: DocumentPage,
    first_fact_number: int,
) -> list[ExtractedFact]:
    patterns = (
        ("payment_obligation", r"\b(?:payment shall be made|buyer shall pay|payment must be made)\b[^.!?]*[.!?]?"),
        ("delivery_obligation", r"\b(?:seller shall deliver|goods shall be delivered|delivery must be completed)\b[^.!?]*[.!?]?"),
    )
    facts = []
    for line in page.text.splitlines():
        for field, expression in patterns:
            match = re.search(expression, line, re.IGNORECASE)
            if match is None:
                continue
            quote = match.group(0).strip()
            facts.append(
                ExtractedFact(
                    fact_id=f"F{first_fact_number + len(facts):04d}",
                    fact_type="obligation",
                    field=field,
                    value=quote,
                    normalized_value=quote,
                    document_id=document.document_id,
                    page=page.page,
                    quote=quote,
                    confidence=0.9,
                    extraction_method=page.extraction_method,
                )
            )
    return facts


def _extract_narrative_delivery_date(
    document: DocumentExtractionResult,
    page: DocumentPage,
    first_fact_number: int,
    already_labeled: bool,
) -> list[ExtractedFact]:
    if already_labeled:
        return []

    facts = []
    for line in page.text.splitlines():
        phrase = re.search(r"\bgoods were delivered on\b", line, re.IGNORECASE)
        if phrase is None:
            continue
        date_match = DATE_VALUE_PATTERN.search(line, phrase.end())
        if date_match is None:
            continue
        date_value = date_match.group(0)
        parsed_date = _parse_date(date_value)
        if parsed_date is None:
            continue
        normalized_date, confidence = parsed_date
        facts.append(
            ExtractedFact(
                fact_id=f"F{first_fact_number + len(facts):04d}",
                fact_type="date",
                field="delivery_date",
                value=date_value,
                normalized_value=normalized_date,
                document_id=document.document_id,
                page=page.page,
                quote=line.strip(),
                confidence=min(confidence, 0.9),
                extraction_method=page.extraction_method,
            )
        )
    return facts


def _extract_narrative_hearing_facts(
    document: DocumentExtractionResult,
    page: DocumentPage,
    first_fact_number: int,
) -> list[ExtractedFact]:
    facts = []
    for line in page.text.splitlines():
        if not re.search(r"\bhearing\b", line, re.IGNORECASE):
            continue
        date_match = DATE_VALUE_PATTERN.search(line)
        if date_match is not None:
            date_value = date_match.group(0)
            parsed_date = _parse_date(date_value)
            if parsed_date is not None:
                normalized_date, confidence = parsed_date
                facts.append(
                    ExtractedFact(
                        fact_id=f"F{first_fact_number + len(facts):04d}",
                        fact_type="date",
                        field="hearing_date",
                        value=date_value,
                        normalized_value=normalized_date,
                        document_id=document.document_id,
                        page=page.page,
                        quote=line.strip(),
                        confidence=confidence,
                        extraction_method=page.extraction_method,
                    )
                )
                continue

        period_match = re.search(
            r"\bexpected hearing during\s+(?P<period>the\s+second week of\s+"
            r"(?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{4})",
            line,
            re.IGNORECASE,
        )
        if period_match is not None:
            normalized_period = re.sub(
                MONTH_NAMES,
                lambda match: match.group(0).capitalize(),
                period_match.group("period").casefold(),
                flags=re.IGNORECASE,
            )
            facts.append(
                ExtractedFact(
                    fact_id=f"F{first_fact_number + len(facts):04d}",
                    fact_type="communication",
                    field="expected_hearing_period",
                    value=period_match.group("period"),
                    normalized_value=normalized_period,
                    document_id=document.document_id,
                    page=page.page,
                    quote=line.strip(),
                    confidence=0.9,
                    extraction_method=page.extraction_method,
                )
            )
    return facts


def _extract_narrative_event_facts(
    document: DocumentExtractionResult,
    page: DocumentPage,
    first_fact_number: int,
    existing_facts: list[ExtractedFact],
) -> list[ExtractedFact]:
    event_phrases = (
        ("document_date", r"\bdocument (?:is )?dated\b"),
        ("filing_date", r"\b(?:filed on|filing was made on)\b"),
        ("payment_date", r"\b(?:payment (?:was )?made on|paid on)\b"),
        ("delivery_date", r"\b(?:goods were )?delivered on\b"),
    )
    facts = []
    existing_fields = {
        fact.field for fact in existing_facts if fact.page == page.page
    }
    for line in page.text.splitlines():
        for field, expression in event_phrases:
            if field in existing_fields or any(fact.field == field for fact in facts):
                continue
            phrase = re.search(expression, line, re.IGNORECASE)
            if phrase is None:
                continue
            date_match = DATE_VALUE_PATTERN.search(line, phrase.end())
            if date_match is None:
                continue
            parsed_date = _parse_date(date_match.group(0))
            if parsed_date is None:
                continue
            normalized_date, confidence = parsed_date
            facts.append(
                ExtractedFact(
                    fact_id=f"F{first_fact_number + len(facts):04d}",
                    fact_type="date",
                    field=field,
                    value=date_match.group(0),
                    normalized_value=normalized_date,
                    document_id=document.document_id,
                    page=page.page,
                    quote=line.strip(),
                    confidence=min(confidence, 0.92),
                    extraction_method=page.extraction_method,
                )
            )
    return facts


def extract_facts(
    document: DocumentExtractionResult,
    classification: DocumentClassificationResult | None = None,
) -> FactExtractionResult:
    full_text = "\n".join(page.text for page in document.pages)
    if not full_text.strip():
        raise FactExtractionError("Document contains no text to extract facts from.")
    if any(page.page < 1 for page in document.pages):
        raise FactExtractionError("Every document page must have a page number of at least 1.")

    selected = classification or classify_document(full_text)
    facts: list[ExtractedFact] = []
    for page in document.pages:
        if not page.text.strip():
            continue
        for rule_group in RULE_GROUPS:
            facts.extend(
                _extract_labeled_facts(
                    document,
                    page,
                    rule_group.get(selected.document_type, ()),
                    len(facts) + 1,
                )
            )
        if selected.document_type == "contract":
            facts.extend(_extract_contract_obligations(document, page, len(facts) + 1))
            facts.extend(
                _extract_narrative_delivery_date(
                    document,
                    page,
                    len(facts) + 1,
                    any(
                        fact.field == "delivery_date" and fact.page == page.page
                        for fact in facts
                    ),
                )
            )
        facts.extend(
            _extract_narrative_hearing_facts(document, page, len(facts) + 1)
        )
        facts.extend(
            _extract_narrative_event_facts(
                document,
                page,
                len(facts) + 1,
                facts,
            )
        )

    return FactExtractionResult(
        document_type=selected.document_type,
        document_id=document.document_id,
        fact_count=len(facts),
        facts=facts,
    )