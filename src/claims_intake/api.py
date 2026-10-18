"""FastAPI service.  Run:  uvicorn claims_intake.api:app --reload   (docs at http://127.0.0.1:8000/docs)"""
from __future__ import annotations

import io
import json
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pathlib import Path
import csv as _csv

import pandas as pd

from . import SCHEMA_VERSION, __version__
from .io_utils import _row_to_input
from .pipeline import process_inputs
from .schema import CSV_COLUMNS, NoteInput, ProcessedNote, to_flat_row

app = FastAPI(title="Claims Intake Note Structuring (first-pass)", version=__version__,
              description="Structures unstructured claim intake notes for ops reviewers. Makes no claim decisions.")
MAX_BATCH = 2000


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui() -> str:
    """Simple browser UI for ops users (paste a note or upload a file)."""
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/export/csv", response_class=PlainTextResponse, include_in_schema=False)
def export_csv(results: list[ProcessedNote]) -> PlainTextResponse:
    return PlainTextResponse(_csv_text(results), media_type="text/csv")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION}


@app.post("/process", response_model=ProcessedNote, summary="Process one note")
def process_one(note: NoteInput) -> ProcessedNote:
    return process_inputs([note])[0]


def _csv_text(results: list[ProcessedNote]) -> str:
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for r in results:
        w.writerow(to_flat_row(r))
    return buf.getvalue()


@app.post("/process/batch", summary="Process a JSON list of notes")
def process_batch(notes: list[NoteInput], format: str = Query("json", pattern="^(json|csv)$")):
    if len(notes) > MAX_BATCH:
        raise HTTPException(413, f"batch too large (max {MAX_BATCH})")
    results = process_inputs(notes)
    if format == "csv":
        return PlainTextResponse(_csv_text(results), media_type="text/csv")
    return [r.model_dump(mode="json") for r in results]


@app.post("/process/file", summary="Upload a CSV / JSON / JSONL file of notes")
async def process_file(file: UploadFile = File(...), format: str = Query("json", pattern="^(json|csv)$")):
    raw = (await file.read()).decode("utf-8-sig")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            rows = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False).to_dict("records")
        elif name.endswith(".jsonl"):
            rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
        elif name.endswith(".json"):
            data = json.loads(raw)
            rows = data if isinstance(data, list) else data.get("notes", [data])
        else:
            raise HTTPException(415, "upload a .csv, .json or .jsonl file")
        notes = [_row_to_input(r, i) for i, r in enumerate(rows, 1)]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"could not read file: {exc}")
    if len(notes) > MAX_BATCH:
        raise HTTPException(413, f"batch too large (max {MAX_BATCH})")
    results = process_inputs(notes)
    if format == "csv":
        return PlainTextResponse(_csv_text(results), media_type="text/csv")
    return [r.model_dump(mode="json") for r in results]
