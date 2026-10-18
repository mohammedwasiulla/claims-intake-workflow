"""Input loading (CSV / JSON / JSONL / folder of .txt exports) and output writing (JSON / CSV)."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .schema import CSV_COLUMNS, NoteInput, ProcessedNote, to_flat_row

_ID_KEYS = ("claim_note_id", "note_id", "id")
_TEXT_KEYS = ("intake_note_text", "note_text", "text", "note")


def _row_to_input(row: dict, idx: int) -> NoteInput:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    text = next((low[k] for k in _TEXT_KEYS if k in low and isinstance(low[k], str) and low[k].strip()), None)
    if text is None:
        raise ValueError(f"row {idx}: no note text found (expected one of {_TEXT_KEYS})")
    nid = next((str(low[k]) for k in _ID_KEYS if k in low and pd.notna(low[k])), None)

    def opt(k):
        v = low.get(k)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" else str(v).strip()
    return NoteInput(claim_note_id=nid, intake_note_text=text, source_channel=opt("source_channel"), received_date=opt("received_date"))


_TXT_HEADER = re.compile(r"^(Claim Note ID|Source Channel|Received Date):\s*(.*)$", re.I)


def parse_txt_export(path: Path) -> NoteInput:
    """Parse a raw_note_exports/*.txt file ('Claim Note ID: ..' header lines, blank line, body)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    i = 0
    while i < len(lines) and (m := _TXT_HEADER.match(lines[i])):
        meta[m.group(1).lower()] = m.group(2).strip()
        i += 1
    body = "\n".join(lines[i:]).strip()
    return NoteInput(claim_note_id=meta.get("claim note id") or path.stem, intake_note_text=body or path.read_text(encoding="utf-8"),
                     source_channel=meta.get("source channel"), received_date=meta.get("received date"))


def load_notes(path: str | Path) -> list[NoteInput]:
    p = Path(path)
    if p.is_dir():
        files = sorted(p.glob("*.txt"))
        if not files:
            raise ValueError(f"no .txt files in {p}")
        return [parse_txt_export(f) for f in files]
    suf = p.suffix.lower()
    if suf == ".csv":
        rows = pd.read_csv(p, dtype=str, keep_default_na=False).to_dict("records")
    elif suf == ".jsonl":
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif suf == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("notes", [data])
    elif suf == ".txt":
        return [parse_txt_export(p)]
    else:
        raise ValueError(f"unsupported input type: {p.suffix}")
    return [_row_to_input(r, i) for i, r in enumerate(rows, 1)]


def write_json(results: Iterable[ProcessedNote], path: str | Path) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_csv(results: Iterable[ProcessedNote], path: str | Path) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig so Excel shows the rupee sign correctly
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in results:
            w.writerow(to_flat_row(r))
    return path
