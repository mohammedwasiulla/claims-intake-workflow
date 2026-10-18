import json, pathlib, re
import pytest
from claims_intake import config as C
from claims_intake.pipeline import process_note, process_inputs
from claims_intake.schema import ProcessedNote, NoteInput

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLD = json.load(open(ROOT / "tests" / "gold_cases.json"))


@pytest.mark.parametrize("nid", sorted(GOLD))
def test_gold_cases(results, nid):
    g, r = GOLD[nid], results[nid]
    f, a = r.extracted_facts, r.assessment
    assert (f.policy_reference.value, f.policy_reference.status) == tuple(g["policy"])
    assert f.claimant_reference.value == g["claimant"]
    if "claimant_status" in g:
        assert f.claimant_reference.status == g["claimant_status"]
    assert f.incident_date.date_status == g["date_status"]
    if "iso" in g:
        assert f.incident_date.iso_date == g["iso"]
    assert f.location.value == g["location"]
    assert a.detected_claim_category == g["category"]
    for key, attr in (("manual", "manual_review_required"), ("urgency", "urgency_indicator"), ("queue", "recommended_reviewer_queue"), ("confidence", "confidence_level")):
        if key in g:
            assert getattr(a, attr) == g[key]


# ---- the eight suggested test cases from the dataset pack
def test_tc01_clean(results):
    a = results["CI-2026-0084"].assessment
    assert a.manual_review_required == "No" and a.readiness_status == "Ready for ops review"

def test_tc02_very_limited(results):
    r = results["CI-2026-0081"]
    a, f = r.assessment, r.extracted_facts
    for fld in (f.policy_reference, f.claimant_reference, f.location):
        assert fld.value is None and fld.status == "missing"
    assert a.detected_claim_category == C.UNCLEAR_CATEGORY          # does not invent "Motor"
    assert "NO_ATTACHMENTS" in a.operational_tags

def test_tc03_mismatch(results):
    a = results["CI-2026-0082"].assessment
    assert a.manual_review_required == "Yes" and "MISMATCH_STATED" in a.operational_tags
    assert any("do not match" in x for x in a.ambiguity_conflict_flags)

def test_tc04_category_correction(results):
    a = results["CI-2026-0083"].assessment
    assert a.detected_claim_category == "Device/Personal Item Damage"
    assert "CATEGORY_MISMATCH" in a.operational_tags and "INVALID_OR_AMBIGUOUS_DATE" in a.operational_tags
    assert a.intended_queue_after_clarification == "Asset and Device Claims"

def test_tc05_attachment_mentioned_not_available(results):
    docs = {d.name: d.status for d in results["CI-2026-0085"].extracted_facts.document_details}
    assert docs["photos"] == "mentioned_not_available"

def test_tc06_batch_one_row_per_note(dataset, results):
    assert len(results) == len(dataset) == 85

def test_tc07_queue_matches_category_unless_manual(results):
    for r in results.values():
        a = r.assessment
        if a.manual_review_required == "No":
            assert a.recommended_reviewer_queue == C.CATEGORY_TO_QUEUE[a.detected_claim_category]
        else:
            assert a.recommended_reviewer_queue == C.MANUAL_QUEUE

def test_tc08_long_messy(custom):
    r = custom["CUS-LONG-01"]
    f = r.extracted_facts
    assert f.policy_reference.value == "POL-7781"            # quoted reply (POL-1111) and signature ignored
    assert f.incident_date.date_status == "ambiguous"        # two dates -> flagged, not guessed
    assert r.assessment.urgency_indicator == "Urgent"
    assert len(r.generated.short_incident_summary) < 400


# ---- custom: incomplete / ambiguous / clean
def test_clean_custom(custom):
    a = custom["CUS-CLEAN-01"].assessment
    assert a.manual_review_required == "No" and a.confidence_level == "High"

def test_incomplete_custom(custom):
    r = custom["CUS-INCOMPLETE-01"]
    assert r.assessment.manual_review_required == "Yes" and r.assessment.confidence_level == "Low"
    assert r.extracted_facts.policy_reference.value is None

def test_ambiguous_custom(custom):
    r = custom["CUS-AMBIG-01"]
    assert r.extracted_facts.policy_reference.status == "unclear"
    assert r.extracted_facts.amount_or_estimate.amount_inr is None       # two amounts -> no number picked
    assert r.assessment.manual_review_required == "Yes"

def test_decision_bait_not_echoed(custom):
    r = custom["CUS-DECISIONBAIT-01"]
    text = (r.generated.short_incident_summary + " " + r.generated.reviewer_handoff_note).lower()
    assert "approve" not in text and "at fault" not in text
    assert "DECISION_REQUESTED_BY_CLAIMANT" in r.assessment.operational_tags


# ---- invariants over every note
def test_schema_roundtrip(results, custom):
    for r in list(results.values()) + list(custom.values()):
        ProcessedNote.model_validate(r.model_dump(mode="json"))

def test_grounding_found_values_appear_in_note(results, raw):
    """Anything marked found/tentative must be traceable to the note text (no invented details)."""
    norm = lambda s: re.sub(r"[\s\-]+", "", s.lower())
    for nid, r in results.items():
        t = norm(raw[nid])
        f = r.extracted_facts
        for fld in (f.policy_reference, f.claimant_reference):
            if fld.value and fld.status in ("found", "tentative"):
                assert norm(fld.value) in t, (nid, fld.value)
        if f.location.status == "found":
            assert norm(f.location.value) in t, (nid, f.location.value)
        if f.incident_date.value:
            assert norm(f.incident_date.value.split(" / ")[0]) in t, (nid, f.incident_date.value)
        for d in f.supporting_document_mentions:
            assert norm(d) in t, (nid, d)

def test_missing_never_filled(results):
    for r in results.values():
        f = r.extracted_facts
        for fld in (f.policy_reference, f.claimant_reference, f.location):
            if fld.status == "missing":
                assert fld.value is None

def test_no_decision_language(results, custom):
    for r in list(results.values()) + list(custom.values()):
        text = (r.generated.short_incident_summary + " " + r.generated.reviewer_handoff_note).lower()
        for w in C.BANNED_DECISION_TERMS:
            assert not re.search(rf"\b{re.escape(w)}\b", text), (r.claim_note_id, w)

def test_manual_flag_consistent(results):
    for r in results.values():
        a = r.assessment
        assert (a.manual_review_required == "Yes") == bool(a.manual_review_reasons)
        assert (a.readiness_status == "Manual review before routing") == (a.manual_review_required == "Yes")

def test_deterministic(dataset):
    a = [r.model_dump() for r in process_inputs(dataset[:20])]
    b = [r.model_dump() for r in process_inputs(dataset[:20])]
    assert a == b

def test_duplicate_claimant_across_batch(results):
    assert "POSSIBLE_DUPLICATE" in results["CI-2026-0030"].assessment.operational_tags      # CLMNT-8245 also in 0050

def test_duplicate_input_ids_not_merged():
    n = NoteInput(claim_note_id="X", intake_note_text="Car bumper damaged in Pune. Policy POL-1234.")
    out = process_inputs([n, n])
    assert len(out) == 2 and out[0].claim_note_id != out[1].claim_note_id

def test_single_note_without_metadata():
    r = process_note("S1", "Laptop damaged by liquid spill. Policy POL-5555, CLMNT-1212, loss date 01-Jun-2026, Pune.")
    assert r.extracted_facts.source_channel == "MISSING" or "inferred" in r.extracted_facts.source_channel
    assert r.extracted_facts.received_date == "MISSING"

def test_future_incident_date_flagged():
    r = process_note("F1", "Car bumper damaged. Policy POL-1234, CLMNT-9999, loss date 2026-07-01, Pune.", "Email", "2026-06-01")
    assert any("later than the received date" in x for x in r.assessment.ambiguity_conflict_flags)
