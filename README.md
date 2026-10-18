# Claims Intake Note Structuring Workflow (first-pass, for ops reviewers)

Turns unstructured insurance claim intake notes into a consistent, reviewer-ready record: key fields, missing/unclear
information, document mentions, tags, urgency, suggested queue, confidence, a manual-review flag and a short handoff note.

**It never decides a claim.** No approval, rejection, payout, liability or policy-term interpretation. If something is not in the
note it is marked `MISSING` - never guessed. It is deterministic, rule-based and runs offline; an LLM step is optional and off by default.

## What is in the box

| Path | Purpose |
|---|---|
| `src/claims_intake/` | the workflow (extractors, pipeline, schema, API, CLI, report, optional LLM step) |
| `data/` | the 85 synthetic notes (CSV/JSONL), queue mapping, raw `.txt` exports |
| `outputs/processed_outputs.json / .csv` | **sample processed outputs** for all 85 notes |
| `outputs/reviewer_report.html` | plain-language report for non-technical reviewers (open in a browser) |
| `outputs/custom_notes_processed.json` | outputs for the extra clean / incomplete / long / ambiguous test notes |
| `outputs/evaluation_results.json` | numbers behind `docs/EVALUATION.md` |
| `schema/output_schema.json` | JSON Schema of one processed note (generated from the Pydantic models) |
| `docs/` | `ASSUMPTIONS.md`, `LIMITATIONS.md`, `EVALUATION.md`, `SCHEMA.md` |
| `tests/` | 51 tests: dataset test cases TC-01..08, 16 hand-checked gold notes, custom notes, invariants, API, LLM guard |

## Setup (Windows / macOS / Linux, Python 3.10+)

```bash
cd claims-intake-workflow
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=src              # Windows PowerShell: $env:PYTHONPATH="src"   |  cmd: set PYTHONPATH=src
```

## Run

**1. Batch (CSV / JSON / JSONL / folder of .txt exports)**
```bash
python -m claims_intake.cli --input data/claim_intake_notes.csv --out outputs
python -m claims_intake.cli --input data/raw_note_exports --out outputs_txt     # .txt exports work too
```
Writes `processed_outputs.json`, `processed_outputs.csv` (Excel-friendly) and `reviewer_report.html`.
Input columns: `intake_note_text` (required), `claim_note_id`, `source_channel`, `received_date` (YYYY-MM-DD) - optional.

**2. One note**
```bash
python -m claims_intake.cli --text "Parked car scratched in Pune. Policy POL-7004, claimant CLMNT-3388, loss date 18-May-2026." --received 2026-05-25 --channel Email
```

**3. Browser UI + API**
```bash
uvicorn claims_intake.api:app --reload
```
Open **http://127.0.0.1:8000/** for the UI (paste one note or upload a CSV/JSON/JSONL, see cards per note, download JSON/CSV).
API docs for developers: http://127.0.0.1:8000/docs
`POST /process` (one note) · `POST /process/batch` (JSON list, `?format=csv` optional) · `POST /process/file` (upload csv/json/jsonl) · `GET /health`.
```bash
curl -X POST localhost:8000/process -H "content-type: application/json" \
  -d '{"claim_note_id":"N1","intake_note_text":"Laptop liquid spill. Policy POL-5555","received_date":"2026-06-01"}'
```

**4. Tests and evaluation**
```bash
python -m pytest -q tests          # 51 tests
python scripts/run_evaluation.py   # compares with the dataset's starter labels
```

**5. Optional LLM summaries** (off by default; needs `pip install openai` and `OPENAI_API_KEY`)
```bash
python -m claims_intake.cli --input data/claim_intake_notes.csv --out outputs --use-llm --llm-max-calls 10
```
Only notes that are Low-confidence + manual-review, or longer than 1,200 characters, are sent; capped calls, `gpt-4o-mini` by default
(`CLAIMS_LLM_MODEL` to change), temperature 0. The answer goes into `generated.llm_summary` only if it adds no number/ID that is not in the
note and uses no decision language. It can never change extracted facts, flags, queue or confidence. *The live OpenAI call was not exercised
in development (no network/key); the guard and cap logic are tested with a fake client.*

## How to read one output

Each processed note has three blocks, so facts and generated text are never mixed:

1. **`extracted_facts`** - copied from the note, each with an `evidence` snippet and a `status`
   (`found`, `tentative`, `unclear`, `invalid`, `missing`).
2. **`assessment`** - rule-based judgements: category, missing-information flags, ambiguity/conflict flags, tags, urgency (+ basis), queue, confidence (+ reasons), manual-review flag (+ reasons), readiness.
3. **`generated`** - `short_incident_summary`, `reviewer_handoff_note`, `source_grounding_note`; written *from* blocks 1-2.

Reviewer outcome (`readiness_status`): **Ready for ops review** · **Needs more information** (gaps, but nothing contradictory) · **Manual review before routing** (conflicts, invalid/ambiguous dates, unclear category, explicit "re-check/hold/duplicate" remarks, or 3+ of 4 core fields missing/uncertain). Manual cases go to the **Manual Clarification Queue**; `intended_queue_after_clarification` shows where they belong afterwards.

All rules and vocabularies are in `src/claims_intake/config.py` (e.g. `MANUAL_IF_CORE_ISSUES_AT_LEAST`, category keywords, thresholds).

## Design in one paragraph
`clean_note` removes email noise (quoted replies, signatures, disclaimers) → regex extractors for references, dates, location, amounts, documents and follow-ups → keyword scoring for category (never trusts the submitter's or system's label) → deterministic rules for flags, tags, urgency, manual review, queue and confidence → templated generated text, scanned for decision wording → Pydantic validation → JSON/CSV/HTML. A batch pass also flags a claimant reference that appears in several notes.
