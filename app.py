"""Streamlit UI for the claims intake workflow.   Run:  streamlit run app.py"""
import io
import json
import pathlib
import sys

import pandas as pd
import streamlit as st

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from claims_intake.io_utils import _row_to_input, load_notes   # noqa: E402
from claims_intake.pipeline import process_inputs              # noqa: E402
from claims_intake.schema import CSV_COLUMNS, NoteInput, to_flat_row  # noqa: E402

st.set_page_config(page_title="Claims Intake Structuring", layout="wide")
st.title("Claims intake note structuring")
st.caption("First-pass preparation for ops reviewers. Makes no claim decision. Facts come from the note; the handoff text is generated from them.")

mode = st.sidebar.radio("Input", ["Paste one note", "Upload CSV / JSON", "Sample dataset (85 notes)"])
items: list[NoteInput] = []

if mode == "Paste one note":
    text = st.text_area("Intake note", height=180, placeholder="e.g. Parked car scratched in Pune. Policy POL-7004, claimant CLMNT-3388, loss date 18-May-2026. Photos attached.")
    c1, c2 = st.columns(2)
    channel = c1.selectbox("Source channel (optional)", ["", "Email", "Call Center", "Web Form", "Branch Upload", "WhatsApp Summary", "Partner Portal"])
    received = c2.text_input("Received date YYYY-MM-DD (optional)")
    if st.button("Process note", type="primary") and text.strip():
        items = [NoteInput(claim_note_id="NOTE-0001", intake_note_text=text, source_channel=channel or None, received_date=received or None)]
elif mode == "Upload CSV / JSON":
    up = st.file_uploader("File with an intake_note_text column (claim_note_id, source_channel, received_date optional)", type=["csv", "json", "jsonl"])
    if up:
        raw = up.read().decode("utf-8-sig")
        try:
            if up.name.lower().endswith(".csv"):
                rows = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False).to_dict("records")
            elif up.name.lower().endswith(".jsonl"):
                rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
            else:
                d = json.loads(raw)
                rows = d if isinstance(d, list) else d.get("notes", [d])
            items = [_row_to_input(r, i) for i, r in enumerate(rows, 1)]
        except Exception as e:
            st.error(f"Could not read file: {e}")
else:
    items = load_notes(ROOT / "data" / "claim_intake_notes.csv")

if items:
    st.session_state["results"] = process_inputs(items)

results = st.session_state.get("results")
if not results:
    st.info("Choose an input on the left.")
    st.stop()

n = len(results)
man = sum(r.assessment.manual_review_required == "Yes" for r in results)
ready = sum(r.assessment.readiness_status == "Ready for ops review" for r in results)
urg = sum(r.assessment.urgency_indicator == "Urgent" for r in results)
m = st.columns(4)
m[0].metric("Notes", n); m[1].metric("Manual review", man); m[2].metric("Ready for ops review", ready); m[3].metric("Urgent", urg)

flat = pd.DataFrame([to_flat_row(r) for r in results])
f1, f2, f3 = st.columns(3)
q = f1.multiselect("Queue", sorted(flat.recommended_reviewer_queue.unique()))
mr = f2.selectbox("Manual review", ["All", "Yes", "No"])
ug = f3.selectbox("Urgency", ["All", "Urgent", "Normal", "Low"])
view = flat
if q: view = view[view.recommended_reviewer_queue.isin(q)]
if mr != "All": view = view[view.manual_review_required == mr]
if ug != "All": view = view[view.urgency_indicator == ug]
st.dataframe(view[["claim_note_id", "detected_claim_category", "recommended_reviewer_queue", "manual_review_required", "urgency_indicator",
                   "confidence_level", "readiness_status", "missing_information_flags"]], use_container_width=True, hide_index=True)

d1, d2 = st.columns(2)
d1.download_button("Download CSV", flat[CSV_COLUMNS].to_csv(index=False).encode("utf-8-sig"), "processed_outputs.csv", "text/csv")
d2.download_button("Download JSON", json.dumps([r.model_dump(mode="json") for r in results], indent=2, ensure_ascii=False), "processed_outputs.json", "application/json")

st.subheader("Note detail")
pick = st.selectbox("Claim note", [r.claim_note_id for r in view.itertuples()] if len(view) else [r.claim_note_id for r in results])
r = next(x for x in results if x.claim_note_id == pick)
a, f, g = r.assessment, r.extracted_facts, r.generated
st.markdown(f"**{a.detected_claim_category}** · queue **{a.recommended_reviewer_queue}** · urgency **{a.urgency_indicator}** · confidence **{a.confidence_level}** ({a.confidence_score}) · manual review **{a.manual_review_required}**")
st.info(g.reviewer_handoff_note)
c1, c2 = st.columns(2)
with c1:
    st.markdown("#### Facts taken from the note")
    st.table(pd.DataFrame([
        ("Policy", f.policy_reference.value or "MISSING", f.policy_reference.status),
        ("Claimant", f.claimant_reference.value or "MISSING", f.claimant_reference.status),
        ("Incident date", f.incident_date.value or "MISSING", f.incident_date.date_status),
        ("Location", f.location.value or "MISSING", f.location.status),
        ("Amount", f.amount_or_estimate.value or "MISSING", f.amount_or_estimate.status),
        ("Received", f.received_date, ""), ("Channel", f.source_channel, ""),
    ], columns=["Field", "Value", "Status"]))
    st.markdown("**Documents:** " + (", ".join(f"{d.name} ({d.status})" for d in f.document_details) or "none"))
    st.markdown("**Follow-ups:** " + ("; ".join(f.follow_up_requirements) or "none"))
with c2:
    st.markdown("#### Missing information"); st.write(a.missing_information_flags or "none")
    st.markdown("#### Unclear / conflicting"); st.write(a.ambiguity_conflict_flags or "none")
    st.markdown("#### Why manual review"); st.write(a.manual_review_reasons or "not required")
    st.markdown("#### Tags"); st.write(", ".join(a.operational_tags) or "none")
with st.expander("Short summary (generated) and full JSON"):
    st.write(g.short_incident_summary)
    st.json(r.model_dump(mode="json"))
