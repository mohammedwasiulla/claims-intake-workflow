"""Pydantic output schema.

The JSON output is split in three blocks so a reader can always tell where a statement came from:

* ``extracted_facts``  - copied from the note text (with the evidence snippet). Nothing is invented;
                         anything not in the note is marked ``missing``.
* ``assessment``       - rule-derived judgements (category, flags, tags, urgency, queue, confidence).
* ``generated``        - human-readable text written *from* the two blocks above.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import SCHEMA_VERSION

FieldStatus = Literal["found", "tentative", "missing", "unclear", "invalid"]
DateStatus = Literal["complete", "partial", "approximate", "ambiguous", "invalid", "relative", "unconfirmed", "missing"]
DocStatus = Literal[
    "mentioned",               # listed as sent / attached / mentioned
    "mentioned_not_available", # note says it was sent but cannot be seen / is pending
    "mentioned_conflicting",   # listed in one place and reported missing/pending in another
    "quality_issue",           # present but unclear / incomplete / too short
    "reported_missing",        # only referenced as missing / pending / not attached
]


class ExtractedField(BaseModel):
    value: Optional[str] = Field(None, description="Text as written in the note, or null when missing.")
    status: FieldStatus
    evidence: Optional[str] = Field(None, description="Verbatim snippet of the note the value was taken from.")
    detail: Optional[str] = Field(None, description="Why the field is missing/unclear (as stated in the note).")


class DateField(ExtractedField):
    iso_date: Optional[str] = Field(None, description="YYYY-MM-DD, only when the note gives an unambiguous full date.")
    date_status: DateStatus = "missing"
    candidate_iso_dates: list[str] = Field(default_factory=list, description="Possible readings of an ambiguous numeric date that are not after the received date.")


class AmountField(ExtractedField):
    amount_inr: Optional[float] = Field(None, description="Numeric rupee value when a figure is stated.")
    qualifier: Optional[str] = Field(None, description="approx / quoted / estimate wording used in the note.")
    all_amounts_found: list[str] = Field(default_factory=list)


class DocumentMention(BaseModel):
    name: str
    status: DocStatus
    evidence: str
    detail: Optional[str] = None


class ExtractedFacts(BaseModel):
    policy_reference: ExtractedField
    claimant_reference: ExtractedField
    incident_date: DateField
    received_date: str
    location: ExtractedField
    amount_or_estimate: AmountField
    source_channel: str
    incident_description_excerpt: Optional[str] = Field(None, description="Verbatim incident wording from the note.")
    user_selected_category: Optional[str] = Field(None, description="Category the submitter picked, if the note says so.")
    supporting_document_mentions: list[str] = Field(default_factory=list)
    documents_reported_missing: list[str] = Field(default_factory=list)
    document_details: list[DocumentMention] = Field(default_factory=list)
    gaps_stated_in_note: list[str] = Field(default_factory=list, description="Gaps the note itself reports, e.g. 'baggage tag unclear'.")
    follow_up_requirements: list[str] = Field(default_factory=list)
    internal_remarks: list[str] = Field(default_factory=list, description="Instructions/remarks found in the note, verbatim.")


class Assessment(BaseModel):
    detected_claim_category: str
    category_basis: list[str] = Field(default_factory=list, description="Keywords that drove the category.")
    category_runner_up: Optional[str] = None
    missing_information_flags: list[str] = Field(default_factory=list)
    ambiguity_conflict_flags: list[str] = Field(default_factory=list)
    operational_tags: list[str] = Field(default_factory=list)
    urgency_indicator: Literal["Low", "Normal", "Urgent", "Unknown"]
    urgency_basis: str
    recommended_reviewer_queue: str
    intended_queue_after_clarification: Optional[str] = None
    confidence_level: Literal["High", "Medium", "Low"]
    confidence_score: int = Field(ge=0, le=100)
    confidence_reasons: list[str] = Field(default_factory=list)
    manual_review_required: Literal["Yes", "No"]
    manual_review_reasons: list[str] = Field(default_factory=list)
    readiness_status: Literal["Ready for ops review", "Needs more information", "Manual review before routing"]


class GeneratedText(BaseModel):
    short_incident_summary: str
    reviewer_handoff_note: str
    source_grounding_note: str
    llm_summary: Optional[str] = Field(None, description="Only present when the optional LLM step ran and passed grounding checks.")


class ProcessedNote(BaseModel):
    schema_version: str = SCHEMA_VERSION
    claim_note_id: str
    extracted_facts: ExtractedFacts
    assessment: Assessment
    generated: GeneratedText


class NoteInput(BaseModel):
    claim_note_id: Optional[str] = None
    intake_note_text: str = Field(min_length=1)
    source_channel: Optional[str] = None
    received_date: Optional[str] = None


CSV_COLUMNS = [
    "claim_note_id", "source_channel", "received_date", "detected_claim_category",
    "policy_reference", "claimant_reference", "incident_date", "incident_date_status", "location",
    "amount_or_estimate", "supporting_document_mentions", "documents_reported_missing",
    "missing_information_flags", "ambiguity_conflict_flags", "operational_tags", "urgency_indicator",
    "recommended_reviewer_queue", "intended_queue_after_clarification", "confidence_level",
    "manual_review_required", "manual_review_reasons", "readiness_status", "follow_up_requirements",
    "short_incident_summary", "reviewer_handoff_note", "source_grounding_note",
]


def to_flat_row(n: ProcessedNote) -> dict:
    """Flatten one processed note into a reviewer-friendly CSV row ('MISSING' marks absent fields)."""
    f, a, g = n.extracted_facts, n.assessment, n.generated

    def val(x: ExtractedField) -> str:
        if x.value is None:
            return "MISSING" if x.status == "missing" else f"UNCLEAR ({x.detail or 'see note'})"
        return x.value if x.status in ("found",) else f"{x.value} [{x.status.upper()}]"

    def j(xs: list[str]) -> str:
        return " | ".join(xs)

    return {
        "claim_note_id": n.claim_note_id, "source_channel": f.source_channel, "received_date": f.received_date,
        "detected_claim_category": a.detected_claim_category,
        "policy_reference": val(f.policy_reference), "claimant_reference": val(f.claimant_reference),
        "incident_date": (f.incident_date.value or "MISSING") + ("" if f.incident_date.date_status in ("complete", "missing") else f" [{f.incident_date.date_status.upper()}]"),
        "incident_date_status": f.incident_date.date_status,
        "location": val(f.location),
        "amount_or_estimate": f.amount_or_estimate.value or "MISSING",
        "supporting_document_mentions": j(f.supporting_document_mentions),
        "documents_reported_missing": j(f.documents_reported_missing),
        "missing_information_flags": j(a.missing_information_flags),
        "ambiguity_conflict_flags": j(a.ambiguity_conflict_flags),
        "operational_tags": ", ".join(a.operational_tags),
        "urgency_indicator": a.urgency_indicator,
        "recommended_reviewer_queue": a.recommended_reviewer_queue,
        "intended_queue_after_clarification": a.intended_queue_after_clarification or "",
        "confidence_level": a.confidence_level, "manual_review_required": a.manual_review_required,
        "manual_review_reasons": j(a.manual_review_reasons), "readiness_status": a.readiness_status,
        "follow_up_requirements": j(f.follow_up_requirements),
        "short_incident_summary": g.short_incident_summary, "reviewer_handoff_note": g.reviewer_handoff_note,
        "source_grounding_note": g.source_grounding_note,
    }
