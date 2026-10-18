"""Command line: process one note or a file/folder of notes.

Examples
  python -m claims_intake.cli --input data/claim_intake_notes.csv --out outputs
  python -m claims_intake.cli --text "Parked car scratched in Pune on 18-May-2026, policy POL-7004" --received 2026-05-25
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .io_utils import load_notes, write_csv, write_json
from .pipeline import process_inputs
from .report import write_report
from .schema import NoteInput


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="First-pass claims intake note structuring (no claim decisions).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="CSV / JSON / JSONL file, a .txt export, or a folder of .txt exports")
    src.add_argument("--text", help="a single note passed on the command line")
    ap.add_argument("--note-id", default="NOTE-0001")
    ap.add_argument("--channel")
    ap.add_argument("--received", help="received date YYYY-MM-DD")
    ap.add_argument("--out", default="outputs", help="output folder (batch mode)")
    ap.add_argument("--limit", type=int, help="process only the first N notes")
    ap.add_argument("--use-llm", action="store_true", help="optional OpenAI summary refinement for hard notes (needs OPENAI_API_KEY)")
    ap.add_argument("--llm-max-calls", type=int, default=10)
    a = ap.parse_args(argv)

    items = [NoteInput(claim_note_id=a.note_id, intake_note_text=a.text, source_channel=a.channel, received_date=a.received)] if a.text else load_notes(a.input)
    if a.limit:
        items = items[: a.limit]
    results = process_inputs(items)

    if a.use_llm:
        from .llm_assist import make_openai_client, refine
        raw = {r.claim_note_id: it.intake_note_text for r, it in zip(results, items)}
        stats = refine(results, raw, make_openai_client(), max_calls=a.llm_max_calls)
        print(f"LLM step: {stats['called']} call(s), {stats['accepted']} accepted, {stats['rejected']} rejected, {stats['errors']} errors", file=sys.stderr)

    if a.text:
        print(json.dumps(results[0].model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    out = Path(a.out)
    write_json(results, out / "processed_outputs.json")
    write_csv(results, out / "processed_outputs.csv")
    write_report(results, out / "reviewer_report.html")
    man = sum(r.assessment.manual_review_required == "Yes" for r in results)
    print(f"Processed {len(results)} notes -> {out}/ (processed_outputs.json, processed_outputs.csv, reviewer_report.html); manual review: {man}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
