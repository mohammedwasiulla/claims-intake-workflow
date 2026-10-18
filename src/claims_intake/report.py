"""Plain-language HTML report for non-technical ops reviewers (open in any browser)."""
from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

from .schema import ProcessedNote

_E = html.escape
_ORDER = ["Manual Clarification Queue", "Motor Claims Intake", "Property Claims Intake", "Health Reimbursement Review",
          "Travel Claims Intake", "Asset and Device Claims", "Commercial Equipment Review"]


def _card(n: ProcessedNote) -> str:
    a, f, g = n.assessment, n.extracted_facts, n.generated
    tone = {"Yes": "manual", "No": "ok"}[a.manual_review_required]
    def li(xs): return "".join(f"<li>{_E(x)}</li>" for x in xs) or "<li class='none'>none</li>"
    return f"""<details class="card {tone}"><summary>
<b>{_E(n.claim_note_id)}</b> &middot; {_E(a.detected_claim_category)} &middot; <span class="pill {a.urgency_indicator.lower()}">{_E(a.urgency_indicator)}</span>
<span class="pill conf-{a.confidence_level.lower()}">confidence {_E(a.confidence_level)}</span>
{'<span class="pill manual">manual review</span>' if a.manual_review_required == 'Yes' else ''}
<span class="status">{_E(a.readiness_status)}</span></summary>
<p class="gen"><b>Handoff note</b> (generated): {_E(g.reviewer_handoff_note)}</p>
<div class="cols"><div><h4>Facts taken from the note</h4><ul>
<li>Policy: {_E(f.policy_reference.value or 'MISSING')} <i>({_E(f.policy_reference.status)})</i></li>
<li>Claimant: {_E(f.claimant_reference.value or 'MISSING')} <i>({_E(f.claimant_reference.status)})</i></li>
<li>Incident date: {_E(f.incident_date.value or 'MISSING')} <i>({_E(f.incident_date.date_status)})</i></li>
<li>Location: {_E(f.location.value or 'MISSING')}</li><li>Amount: {_E(f.amount_or_estimate.value or 'MISSING')}</li>
<li>Documents mentioned: {_E(', '.join(f.supporting_document_mentions) or 'none')}</li></ul></div>
<div><h4>Missing information</h4><ul>{li(a.missing_information_flags)}</ul>
<h4>Unclear / conflicting</h4><ul>{li(a.ambiguity_conflict_flags)}</ul>
<h4>Why manual review</h4><ul>{li(a.manual_review_reasons)}</ul></div></div>
<p class="small">Tags: {_E(', '.join(a.operational_tags) or 'none')} &middot; Urgency basis: {_E(a.urgency_basis)}</p></details>"""


def write_report(results: list[ProcessedNote], path: str | Path, title: str = "Claims intake - reviewer hand-off report") -> Path:
    by_q: dict[str, list[ProcessedNote]] = {}
    for r in results:
        by_q.setdefault(r.assessment.recommended_reviewer_queue, []).append(r)
    total = len(results)
    man = sum(r.assessment.manual_review_required == "Yes" for r in results)
    ready = sum(r.assessment.readiness_status == "Ready for ops review" for r in results)
    urgent = sum(r.assessment.urgency_indicator == "Urgent" for r in results)
    qcount = Counter(r.assessment.recommended_reviewer_queue for r in results)
    sections = []
    for q in sorted(by_q, key=lambda x: (_ORDER.index(x) if x in _ORDER else 99, x)):
        items = sorted(by_q[q], key=lambda r: (r.assessment.urgency_indicator != "Urgent", r.assessment.manual_review_required != "Yes", r.claim_note_id))
        sections.append(f"<h2>{_E(q)} <small>({qcount[q]})</small></h2>" + "".join(_card(r) for r in items))
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_E(title)}</title><style>
:root{{--bg:#fff;--fg:#1d2430;--mut:#5b6573;--card:#f6f8fb;--bd:#d9dee6;--man:#b4442f;--ok:#2f7d4f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14181f;--fg:#e8ecf2;--mut:#9aa5b4;--card:#1d232d;--bd:#323a47;--man:#e0775f;--ok:#61b886}}}}
body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:20px;background:var(--bg);color:var(--fg)}}
h1{{font-size:22px}}h2{{margin-top:32px;border-bottom:1px solid var(--bd);padding-bottom:4px}}h2 small{{color:var(--mut);font-weight:400}}
h4{{margin:10px 0 4px}}ul{{margin:0;padding-left:18px}}.none{{color:var(--mut)}}
.card{{background:var(--card);border:1px solid var(--bd);border-left:5px solid var(--ok);border-radius:6px;margin:8px 0;padding:8px 12px}}
.card.manual{{border-left-color:var(--man)}}summary{{cursor:pointer}}.status{{color:var(--mut);margin-left:8px}}
.pill{{font-size:12px;border:1px solid var(--bd);border-radius:10px;padding:1px 8px;margin-left:4px}}.pill.urgent,.pill.manual{{border-color:var(--man);color:var(--man)}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}}
.gen{{margin:10px 0}}.small{{font-size:13px;color:var(--mut)}}.kpis span{{display:inline-block;margin-right:18px}}
</style></head><body><h1>{_E(title)}</h1>
<p class="kpis"><span><b>{total}</b> notes</span><span><b>{man}</b> need manual review</span><span><b>{ready}</b> ready for ops review</span><span><b>{urgent}</b> urgent</span></p>
<p class="small">First-pass preparation only. This report does not approve, reject, price or assess any claim. Facts come from the note text; the handoff note is generated from those facts.
Notes are grouped by suggested queue; urgent and manual-review items are listed first.</p>
{''.join(sections)}</body></html>"""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
