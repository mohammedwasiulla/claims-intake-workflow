"""OPTIONAL, cost-capped LLM step (off by default).

What it may do: rewrite the *summary* of a note that the rules flagged as hard (manual review / low confidence / very long).
What it may NOT do: change any extracted fact, flag, tag, queue or confidence value. Its output is stored separately in
``generated.llm_summary`` and is discarded unless it passes the grounding checks below.

Cost controls: only flagged notes are sent, at most ``max_calls`` per run, input truncated to ``max_chars``, small model,
temperature 0, max_tokens 200.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from . import config as C
from .schema import ProcessedNote

PROMPT = (
    "You help insurance operations reviewers. Summarise the intake note below in at most 2 sentences. "
    "Use ONLY facts written in the note. Do not add numbers, names, dates or references that are not in the note. "
    "Do not say whether a claim is valid, covered, payable, approved, rejected or who is at fault. "
    "If something is unclear in the note, say it is unclear. Reply as JSON: {\"summary\": \"...\"}.\n\nNOTE:\n"
)


def needs_llm(r: ProcessedNote, raw_len: int, long_chars: int = 1200) -> bool:
    a = r.assessment
    return a.manual_review_required == "Yes" and a.confidence_level == "Low" or raw_len > long_chars


def grounded(summary: str, note_text: str) -> tuple[bool, str]:
    """Reject summaries that introduce tokens (numbers, ids) absent from the note, or use decision language."""
    low = summary.lower()
    for w in C.BANNED_DECISION_TERMS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            return False, f"decision term '{w}'"
    note_low = note_text.lower()
    for tok in re.findall(r"[a-z]{2,}-?\d+|\d[\d,\.]*", low):
        if tok.strip(".,") and tok.strip(".,") not in note_low:
            return False, f"token '{tok}' not found in note"
    if len(summary) > 500:
        return False, "too long"
    return True, ""


def make_openai_client() -> Any:  # pragma: no cover - needs network + key
    from openai import OpenAI
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI()


def refine(results: list[ProcessedNote], raw_texts: dict[str, str], client: Any, model: Optional[str] = None,
           max_calls: int = 10, max_chars: int = 4000) -> dict:
    """Mutates ``generated.llm_summary`` for eligible notes. Returns usage stats."""
    model = model or os.getenv("CLAIMS_LLM_MODEL", "gpt-4o-mini")
    stats = {"eligible": 0, "called": 0, "accepted": 0, "rejected": 0, "errors": 0, "rejections": []}
    for r in results:
        raw = raw_texts.get(r.claim_note_id, "")
        if not needs_llm(r, len(raw)):
            continue
        stats["eligible"] += 1
        if stats["called"] >= max_calls:
            continue
        stats["called"] += 1
        try:
            resp = client.chat.completions.create(model=model, temperature=0, max_tokens=200,
                                                  response_format={"type": "json_object"},
                                                  messages=[{"role": "user", "content": PROMPT + raw[:max_chars]}])
            summary = json.loads(resp.choices[0].message.content)["summary"].strip()
        except Exception as exc:  # network, parse, quota ... never break the batch
            stats["errors"] += 1
            stats["rejections"].append((r.claim_note_id, f"error: {type(exc).__name__}"))
            continue
        ok, why = grounded(summary, raw)
        if ok:
            r.generated.llm_summary = summary
            stats["accepted"] += 1
        else:
            stats["rejected"] += 1
            stats["rejections"].append((r.claim_note_id, why))
    return stats
