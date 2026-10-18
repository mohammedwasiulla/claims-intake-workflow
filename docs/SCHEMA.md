# Output schema

Machine-readable: `schema/output_schema.json` (generated from `src/claims_intake/schema.py`, validated on every note).

| Required item | Where it lives |
|---|---|
| claim note ID | `claim_note_id` |
| detected claim category | `assessment.detected_claim_category` |
| short incident summary | `generated.short_incident_summary` |
| extracted key fields | `extracted_facts.policy_reference / claimant_reference / incident_date / received_date / location / amount_or_estimate / source_channel` (each with `value`, `status`, `evidence`) |
| missing information flags | `assessment.missing_information_flags` (absent) and `assessment.ambiguity_conflict_flags` (present but unclear/conflicting) |
| supporting document mentions | `extracted_facts.supporting_document_mentions`, `documents_reported_missing`, `document_details[].status` |
| urgency indicator | `assessment.urgency_indicator` (+ `urgency_basis`) |
| recommended reviewer queue | `assessment.recommended_reviewer_queue` (+ `intended_queue_after_clarification`) |
| confidence level | `assessment.confidence_level` (+ `confidence_score`, `confidence_reasons`) |
| manual review flag | `assessment.manual_review_required` (+ `manual_review_reasons`, `readiness_status`) |
| concise reviewer handoff note | `generated.reviewer_handoff_note` |
| facts vs generated separation | three blocks: `extracted_facts` / `assessment` / `generated`; `generated.source_grounding_note` explains it |

Field statuses: `found`, `tentative` (e.g. "policy maybe POL-9935", approximate amount), `unclear` (several values, unreadable, partial date), `invalid` (not a real date), `missing`.
Date statuses: `complete`, `approximate`, `partial` (no year), `ambiguous` (day/month order or several dates), `invalid`, `relative`, `unconfirmed`, `missing`.
Document statuses: `mentioned`, `mentioned_not_available`, `mentioned_conflicting`, `quality_issue`, `reported_missing`.

The CSV has one flattened row per note (`schema.CSV_COLUMNS`); missing fields are written as `MISSING`, uncertain ones as `value [STATUS]`, lists are joined with ` | `.

Operational tags: MISSING_POLICY_REF, UNCERTAIN_POLICY_REF, MISSING_CLAIMANT_REF, UNCERTAIN_CLAIMANT_REF, MISSING_INCIDENT_DATE, INCIDENT_DATE_INCOMPLETE, INVALID_OR_AMBIGUOUS_DATE, MISSING_LOCATION, UNCERTAIN_LOCATION, AMOUNT_NOT_STATED, DOCS_PENDING_OR_MISSING, DOCS_QUALITY_ISSUE, DOCS_CONFLICTING, NO_ATTACHMENTS, ATTACHMENT_UNREADABLE, ATTACHMENT_NOT_VISIBLE, MISMATCH_STATED, CATEGORY_MISMATCH, CATEGORY_RECHECK, CATEGORY_SELF_REPORTED, POSSIBLE_DUPLICATE, COPIED_FROM_THREAD, HOLD_UNTIL_CLEANED, CALLBACK_REQUESTED, EMAIL_FOLLOWUP_PREFERRED, STATUS_UPDATE_REQUESTED, CLAIMANT_QUESTION_OPEN, DECISION_REQUESTED_BY_CLAIMANT, NOTE_MENTIONS_BLAME, URGENT.

## Example (CI-2026-0085, abridged)
```json
{
  "claim_note_id": "CI-2026-0085",
  "extracted_facts": {
    "policy_reference": {
      "value": null,
      "status": "missing",
      "evidence": null,
      "detail": "not mentioned in the note"
    },
    "incident_date": {
      "value": "22 May",
      "status": "unclear",
      "evidence": "bad. Date approx 22 May. Photos sent on WhatsApp but not visible in upload folder. Repair quote to b...",
      "detail": "year not stated in the note",
      "iso_date": null,
      "date_status": "partial",
      "candidate_iso_dates": []
    },
    "location": {
      "value": "Hyderabad",
      "status": "found",
      "evidence": "int. Location Hyderabad. Dat",
      "detail": null
    },
    "supporting_document_mentions": [
      "photos"
    ],
    "follow_up_requirements": [
      "Caller asks whether an inspection is required",
      "Repair quote promised later"
    ]
  },
  "assessment": {
    "detected_claim_category": "Property Water Damage",
    "missing_information_flags": [
      "policy reference missing",
      "claimant reference missing",
      "amount/estimate not stated",
      "photos not visible/accessible",
      "repair quote pending (to be sent later)"
    ],
    "ambiguity_conflict_flags": [
      "incident date is uncertain: '22 May' - year not stated in the note"
    ],
    "urgency_indicator": "Normal",
    "recommended_reviewer_queue": "Manual Clarification Queue",
    "intended_queue_after_clarification": "Property Claims Intake",
    "confidence_level": "Medium",
    "manual_review_required": "Yes",
    "manual_review_reasons": [
      "3 of 4 core fields (policy, claimant, incident date, location) are missing or uncertain"
    ],
    "readiness_status": "Manual review before routing"
  },
  "generated": {
    "short_incident_summary": "Caller says ceiling leakage damaged kitchen cabinet and wall paint. Incident date: '22 May' (year not stated in the note); location: Hyderabad.",
    "reviewer_handoff_note": "Property Water Damage note via Call Center, received 2026-05-26. Stated in note: policy MISSING; claimant MISSING; incident date 22 May (unclear); location Hyderabad; amount MISSING. Documents mentioned: photos. Needs attention: 3 of 4 core fields (policy, claimant, incident date, location) are missing or uncertain; policy reference missing; claimant reference missing; amount/estimate not stated (+3 more in the detailed fields). Suggested queue: Manual Clarification Queue (intended queue after clarification: Property Claims Intake); urgency Normal; manual review required: Yes. Status: Manual review before routing. Follow-up noted: Caller asks whether an inspection is required; Repair quote promised later. First-pass preparation only - no claim decision implied."
  }
}
```
