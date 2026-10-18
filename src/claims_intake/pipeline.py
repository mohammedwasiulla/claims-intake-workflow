"""End-to-end first-pass processing of intake notes. Deterministic and offline by default."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Iterable, Optional

from . import config as C
from . import extractors as X
from .schema import Assessment, ExtractedFacts, GeneratedText, NoteInput, ProcessedNote

_SUBMITTER_CATEGORY_WORDS = {
    "travel": "Travel Delay/Baggage", "motor": "Motor Accident", "vehicle": "Motor Accident", "car": "Motor Accident",
    "property": "Property Water Damage", "health": "Health Reimbursement", "medical": "Health Reimbursement",
    "device": "Device/Personal Item Damage", "commercial": "Commercial Equipment",
}
_CHANNEL_HINTS = [
    (r"\bweb\s+intake\s+form\b|\bweb\s+form\b", "Web Form"), (r"\bfwd\s+from\s+service\s+inbox\b|\be-?mail\b", "Email"),
    (r"\bcall\s+(?:log|center|centre)\b|\bcaller\b", "Call Center"), (r"\bwhatsapp\b", "WhatsApp Summary"),
    (r"\bpartner\s+(?:portal|uploaded)\b", "Partner Portal"), (r"\bbranch\b", "Branch Upload"),
]


# --------------------------------------------------------------------------- category
def detect_category(text: str) -> tuple[str, list[str], Optional[str], int, int]:
    """Return (category, matched keywords, runner-up, top score, runner-up score). Scores each rule once."""
    scoring_text = re.sub(r"user\s+selected\s+[A-Za-z/ ]+?\s+category", " ", text, flags=re.I)
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = defaultdict(list)
    for cat, rules in C.CATEGORY_RULES.items():
        for rx, w in rules:
            m = re.search(rx, scoring_text, re.I)
            if m:
                scores[cat] = scores.get(cat, 0) + w
                hits[cat].append(m.group(0).lower())
    if not scores:
        return C.UNCLEAR_CATEGORY, [], None, 0, 0
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_s = ranked[0]
    second, second_s = ranked[1] if len(ranked) > 1 else (None, 0)
    if top_s < C.CATEGORY_MIN_SCORE:
        return C.UNCLEAR_CATEGORY, hits[top], top, top_s, second_s
    return top, hits[top], second, top_s, second_s


def _infer_channel(text: str) -> Optional[str]:
    for rx, label in _CHANNEL_HINTS:
        if re.search(rx, text, re.I):
            return label
    return None


def _parse_iso(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- main entry
def process_note(note_id: str, text: str, source_channel: Optional[str] = None, received_date: Optional[str] = None,
                 extra_ambiguity: Optional[list[str]] = None) -> ProcessedNote:
    raw_text = text or ""
    t = X.clean_note(raw_text)
    received = _parse_iso(received_date)
    amb: list[str] = list(extra_ambiguity or [])
    miss: list[str] = []
    tags: list[str] = []
    hard: list[str] = []   # reasons that force manual review
    conf_notes: list[tuple[int, str]] = []  # (deduction, reason)

    # ---- extraction (facts)
    policy, claimant = X.extract_policy(t), X.extract_claimant(t)
    inc_date, date_flags, date_remark_missing = X.extract_incident_date(t, received)
    location, amount = X.extract_location(t), X.extract_amount(t)
    docs, gaps, doc_flags, extras = X.extract_documents(t)
    mismatches = X.extract_mismatch_statements(t)
    follow_ups = X.extract_follow_ups(t)
    remarks = X.extract_remarks(t)
    remark_tags = {tag for tag, _ in remarks}
    user_sel = X.extract_user_selected_category(t)
    description = X.extract_incident_description(t)

    channel = source_channel
    channel_note = ""
    if not channel:
        inferred = _infer_channel(t)
        channel = f"{inferred} (inferred from note text)" if inferred else "MISSING"
        channel_note = "channel inferred" if inferred else "channel missing"
    if received_date and not received:
        amb.append(f"received date '{received_date}' is not a valid YYYY-MM-DD date")

    # ---- category
    category, cat_hits, runner, top_s, second_s = detect_category(t)
    if category == C.UNCLEAR_CATEGORY:
        amb.append("incident type cannot be determined from the note wording")
        hard.append("category cannot be determined from the note")
        conf_notes.append((40, "category unclear"))
    elif runner and second_s and top_s - second_s < C.CATEGORY_TIE_MARGIN:
        amb.append(f"category is ambiguous between {category} and {runner}")
        hard.append(f"category ambiguous ({category} vs {runner})")
        conf_notes.append((20, "category ambiguous"))
    if user_sel:
        sel_cat = next((v for k, v in _SUBMITTER_CATEGORY_WORDS.items() if k in user_sel), None)
        if sel_cat and sel_cat != category:
            amb.append(f"submitter selected '{user_sel}' but the note text points to {category}")
            hard.append("submitter-selected category differs from the note text")
            conf_notes.append((10, "category mismatch with submitter selection"))
            tags.append("CATEGORY_MISMATCH")
    if category == "Third-Party Contact":
        hard.append("report comes from a third party; needs a human to clarify the sequence of events")

    # ---- remark-driven signals
    for tag, sentence in remarks:
        if tag == "RECHECK":
            hard.append("note asks for the category/fields to be re-checked manually"); tags.append("CATEGORY_RECHECK"); conf_notes.append((10, "note says category is not trusted"))
        elif tag == "HOLD":
            hard.append("note says not to send to final review until basic fields are cleaned"); tags.append("HOLD_UNTIL_CLEANED"); conf_notes.append((5, "note says fields need cleaning"))
        elif tag == "DUPLICATE":
            hard.append("note says a duplicate may exist in an earlier intake batch"); tags.append("POSSIBLE_DUPLICATE")
            amb.append("note says a duplicate may exist in an earlier intake batch"); conf_notes.append((5, "possible duplicate"))
        elif tag == "MIXED_INFO":
            conf_notes.append((5, "note itself says it contains mixed information"))
        elif tag == "COPIED_THREAD":
            tags.append("COPIED_FROM_THREAD"); conf_notes.append((5, "copied from an earlier thread; details may be stale"))
    if "CATEGORY_SELF_REPORTED" in remark_tags:
        tags.append("CATEGORY_SELF_REPORTED")

    # ---- core fields -> missing vs unclear
    core_issues = 0
    def core(label: str, fld, is_date: bool = False):
        nonlocal core_issues
        st = fld.date_status if is_date else fld.status
        ok = (st == "complete") if is_date else (st == "found")
        if ok:
            return
        core_issues += 1
        if st in ("missing", "unconfirmed"):
            reason = f" ({fld.detail})" if fld.detail and "not mentioned" not in fld.detail else ""
            miss.append(f"{label} missing{reason}")
            conf_notes.append((12, f"{label} missing"))
        else:
            what = fld.value if fld.value else "unreadable"
            amb.append(f"{label} is uncertain: '{what}'" + (f" - {fld.detail}" if fld.detail else ""))
            conf_notes.append((14 if st in ("invalid", "ambiguous") else 9, f"{label} {st}"))
    core("policy reference", policy)
    core("claimant reference", claimant)
    core("incident date", inc_date, is_date=True)
    core("location", location)
    if policy.status in ("missing", "unclear"):
        tags.append("MISSING_POLICY_REF")
    elif policy.status == "tentative":
        tags.append("UNCERTAIN_POLICY_REF")
    if claimant.status == "missing":
        tags.append("MISSING_CLAIMANT_REF")
    elif claimant.status in ("tentative", "unclear"):
        tags.append("UNCERTAIN_CLAIMANT_REF")
    if inc_date.date_status in ("missing", "unconfirmed"):
        tags.append("MISSING_INCIDENT_DATE")
    elif inc_date.date_status in ("invalid", "ambiguous"):
        tags.append("INVALID_OR_AMBIGUOUS_DATE")
        if inc_date.date_status == "invalid" or "more than one date" in (inc_date.detail or "") or len(inc_date.candidate_iso_dates) != 1:
            hard.append(f"incident date problem: {inc_date.detail or inc_date.value}")
    elif inc_date.date_status != "complete":
        tags.append("INCIDENT_DATE_INCOMPLETE")
    if location.status == "missing":
        tags.append("MISSING_LOCATION")
    elif location.status != "found":
        tags.append("UNCERTAIN_LOCATION")
    if policy.status == "unclear" and policy.value and "," in policy.value:
        hard.append("more than one policy reference in the note")
    if claimant.status == "unclear" and claimant.value and "," in claimant.value:
        hard.append("more than one claimant reference in the note")

    amb.extend(date_flags)
    if date_remark_missing and inc_date.date_status in ("complete", "approximate", "partial", "ambiguous", "invalid", "relative"):
        amb.append(f"an internal remark says the incident date is missing, but the note gives '{inc_date.value}'")
        hard.append("internal remark conflicts with the note (date said to be missing but a date is present)")
        conf_notes.append((8, "internal remark conflicts with the note"))
    if date_remark_missing and inc_date.date_status in ("missing", "unconfirmed") and "MISSING_INCIDENT_DATE" not in tags:
        tags.append("MISSING_INCIDENT_DATE")

    # ---- amount
    if amount.status == "missing":
        miss.append("amount/estimate not stated"); tags.append("AMOUNT_NOT_STATED")
    elif amount.status == "unclear" and amount.all_amounts_found:
        amb.append(f"several different amounts mentioned ({'; '.join(amount.all_amounts_found)}); unclear which applies")
        conf_notes.append((8, "several amounts"))
    elif amount.status == "unclear":
        miss.append("amount described in words only; no figure given"); tags.append("AMOUNT_NOT_STATED")

    # ---- documents / gaps
    miss.extend(gaps)
    if gaps:
        conf_notes.append((min(12, 3 * len(gaps)), f"{len(gaps)} document/information gap(s) stated in the note"))
    amb.extend(doc_flags)
    for fl in doc_flags:
        if fl.split(" ")[0] != "'" and "listed as provided" not in fl:   # hard info items such as 'incident sequence unclear'
            hard.append(fl)
    if any(d.status == "mentioned_conflicting" for d in docs):
        tags.append("DOCS_CONFLICTING"); conf_notes.append((8, "document listed as provided and also reported missing"))
    if any(d.status in ("reported_missing",) for d in docs):
        tags.append("DOCS_PENDING_OR_MISSING")
    if any(d.status == "mentioned_not_available" for d in docs):
        tags.append("ATTACHMENT_NOT_VISIBLE")
    if any(d.status == "quality_issue" for d in docs):
        tags.append("DOCS_QUALITY_ISSUE")
    if extras["no_attachments"]:
        tags.append("NO_ATTACHMENTS"); miss.append("no attachments found"); conf_notes.append((5, "no attachments"))
    if extras["unreadable_unspecified"]:
        tags.append("ATTACHMENT_UNREADABLE"); conf_notes.append((4, "unreadable attachment"))
    if extras["papers_not_ready"]:
        tags.append("DOCS_PENDING_OR_MISSING")
    for s in mismatches:
        amb.append(f"note states a mismatch: \"{s[:140]}\"")
        hard.append("note itself states that figures/documents do not match")
        tags.append("MISMATCH_STATED")
        conf_notes.append((8, "mismatch stated in note"))
    if any(tag in ("DOCS_CONFLICTING",) for tag in tags) and "document conflict" not in " ".join(hard):
        pass  # kept as a soft signal (needs more information), not a forced manual review

    # ---- follow-ups -> tags
    fu = " ".join(follow_ups).lower()
    if "call back requested" in fu:
        tags.append("CALLBACK_REQUESTED")
    if "email follow-up" in fu:
        tags.append("EMAIL_FOLLOWUP_PREFERRED")
    if "status update" in fu:
        tags.append("STATUS_UPDATE_REQUESTED")
    if "asks what" in fu or "asks whether" in fu:
        tags.append("CLAIMANT_QUESTION_OPEN")
    if "masked" in fu:
        miss.append("callback number masked/unavailable")
    if "claim decision" in fu:
        tags.append("DECISION_REQUESTED_BY_CLAIMANT")
    if "blame or misconduct" in fu:
        tags.append("NOTE_MENTIONS_BLAME")

    # ---- very short note
    if len(t) < C.VERY_SHORT_NOTE_CHARS:
        amb.append("note is very short; little information to structure")
        conf_notes.append((15, "very short note"))

    # ---- urgency
    urgency, basis = _urgency(t, follow_ups, amb)
    if urgency == "Urgent":
        tags.append("URGENT")

    # ---- manual review / queue / readiness
    if core_issues >= C.MANUAL_IF_CORE_ISSUES_AT_LEAST:
        hard.append(f"{core_issues} of 4 core fields (policy, claimant, incident date, location) are missing or uncertain")
    hard = list(dict.fromkeys(hard))
    manual = bool(hard)
    intended = C.CATEGORY_TO_QUEUE.get(category) if category not in (C.UNCLEAR_CATEGORY, "Third-Party Contact") else None
    queue = C.MANUAL_QUEUE if manual else C.CATEGORY_TO_QUEUE.get(category, C.MANUAL_QUEUE)
    blocking = core_issues > 0 or bool(gaps) or extras["no_attachments"] or extras["papers_not_ready"] or any(d.status != "mentioned" for d in docs)
    readiness = "Manual review before routing" if manual else ("Needs more information" if blocking else "Ready for ops review")

    # ---- confidence
    deduction = sum(d for d, _ in conf_notes)
    score = max(0, 100 - deduction)
    level = "High" if score >= C.CONFIDENCE_HIGH else "Medium" if score >= C.CONFIDENCE_MEDIUM else "Low"
    conf_reasons = [r for _, r in conf_notes] or ["all core fields found and no conflicts detected"]

    # ---- documents lists
    mentions = [d.name for d in docs if d.status != "reported_missing"]
    missing_docs = [d.name for d in docs if d.status in ("reported_missing", "mentioned_not_available")]

    facts = ExtractedFacts(
        policy_reference=policy, claimant_reference=claimant, incident_date=inc_date,
        received_date=received_date or "MISSING", location=location, amount_or_estimate=amount, source_channel=channel,
        incident_description_excerpt=description, user_selected_category=user_sel,
        supporting_document_mentions=mentions, documents_reported_missing=missing_docs, document_details=docs,
        gaps_stated_in_note=gaps, follow_up_requirements=follow_ups, internal_remarks=[s for _, s in remarks],
    )
    miss = list(dict.fromkeys(miss))
    amb = list(dict.fromkeys(amb))
    assessment = Assessment(
        detected_claim_category=category, category_basis=cat_hits, category_runner_up=runner if runner != category else None,
        missing_information_flags=miss, ambiguity_conflict_flags=amb, operational_tags=list(dict.fromkeys(tags)),
        urgency_indicator=urgency, urgency_basis=basis, recommended_reviewer_queue=queue, intended_queue_after_clarification=intended if manual else None,
        confidence_level=level, confidence_score=score, confidence_reasons=conf_reasons,
        manual_review_required="Yes" if manual else "No", manual_review_reasons=hard, readiness_status=readiness,
    )
    generated = _generate_text(note_id, facts, assessment)
    return ProcessedNote(claim_note_id=note_id, extracted_facts=facts, assessment=assessment, generated=generated)


# --------------------------------------------------------------------------- urgency
def _urgency(text: str, follow_ups: list[str], amb: list[str]) -> tuple[str, str]:
    m = re.search(r"expected\s+urgency\s+marked\s+(urgent|normal|low)\s+by\s+intake", text, re.I)
    marker = m.group(1).capitalize() if m else None
    cue = re.search(r"\b(urgent(?:ly)?|asap|immediately)\b", text, re.I)
    emergency = re.search(r"\bemergency\s+(?:admission|visit|hospitali[sz]ation)\b", text, re.I)
    low = re.search(r"\b(?:not\s+urgent|no\s+rush|low\s+priority)\b", text, re.I)
    if cue and not re.search(r"\bnot\s+urgent", text, re.I):
        if marker in ("Normal", "Low"):
            amb.append(f"intake marker says urgency '{marker.lower()}' but the note text says '{cue.group(0)}'")
        return "Urgent", f"note says '{cue.group(0)}'"
    if marker:
        return marker, "intake urgency marker in the note"
    if emergency:
        return "Urgent", f"note mentions '{emergency.group(0).lower()}' (medical emergency wording)"
    if low:
        return "Low", f"note says '{low.group(0)}'"
    if any("status update" in f.lower() for f in follow_ups):
        return "Normal", "claimant asked for a status update (follow-up pressure noted)"
    return "Normal", "default - no urgency cue in the note"


# --------------------------------------------------------------------------- generated text
def _safe(s: str) -> str:
    low = s.lower()
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in C.BANNED_DECISION_TERMS):
        return "[wording withheld: contains claim-decision terms - read the original note]"
    return s


def _val(f, default: str = "MISSING") -> str:
    if f.value is None:
        return default
    return f.value if f.status == "found" else f"{f.value} ({f.status})"


def _generate_text(note_id: str, facts: ExtractedFacts, a: Assessment) -> GeneratedText:
    d, loc = facts.incident_date, facts.location
    desc = (facts.incident_description_excerpt or "").strip().rstrip(".")
    first = (desc[:1].upper() + desc[1:]) if desc else "Incident description is not clear from the note"
    if d.date_status == "complete":
        dp = d.value
    elif d.value:
        dp = f"'{d.value}' ({d.detail or d.date_status})"
    else:
        dp = "not stated"
    lp = loc.value if loc.status == "found" else (f"'{loc.value}' (uncertain)" if loc.value else "not stated")
    summary = _safe(f"{first}. Incident date: {dp}; location: {lp}.")

    docs = ", ".join(facts.supporting_document_mentions) if facts.supporting_document_mentions else "none identified"
    attention = (a.manual_review_reasons + a.missing_information_flags + a.ambiguity_conflict_flags)
    attention = list(dict.fromkeys(attention))
    shown = attention[:4]
    more = f" (+{len(attention) - 4} more in the detailed fields)" if len(attention) > 4 else ""
    attn = "; ".join(shown) + more if shown else "nothing flagged"
    route = a.recommended_reviewer_queue + (f" (intended queue after clarification: {a.intended_queue_after_clarification})" if a.intended_queue_after_clarification else "")
    fu = f" Follow-up noted: {'; '.join(facts.follow_up_requirements)}." if facts.follow_up_requirements else ""
    handoff = _safe(
        f"{a.detected_claim_category} note via {facts.source_channel}, received {facts.received_date}. "
        f"Stated in note: policy {_val(facts.policy_reference)}; claimant {_val(facts.claimant_reference)}; "
        f"incident date {_val(d)}; location {_val(loc)}; amount {facts.amount_or_estimate.value or 'MISSING'}. "
        f"Documents mentioned: {docs}. Needs attention: {attn}. "
        f"Suggested queue: {route}; urgency {a.urgency_indicator}; manual review required: {a.manual_review_required}. Status: {a.readiness_status}.{fu} "
        f"First-pass preparation only - no claim decision implied."
    )
    grounding = (
        "Extracted facts (references, dates, location, amount, documents, follow-ups) are copied from the note text; the evidence "
        "snippet for each is in the JSON. Category, urgency, queue, confidence, tags and flags are rule-based assessments. The summary "
        "and handoff note are generated from those fields and add no facts beyond the note. No claim decision is made."
    )
    return GeneratedText(short_incident_summary=summary, reviewer_handoff_note=handoff, source_grounding_note=grounding)


# --------------------------------------------------------------------------- batch
def process_inputs(items: Iterable[NoteInput]) -> list[ProcessedNote]:
    """Process many notes, then apply cross-note checks (same claimant reference in several notes)."""
    prepared: list[tuple[str, NoteInput]] = []
    seen_ids: dict[str, int] = {}
    for i, it in enumerate(items, 1):
        nid = it.claim_note_id or f"NOTE-{i:04d}"
        if nid in seen_ids:                      # never silently merge two rows that share an id
            seen_ids[nid] += 1
            nid = f"{nid}#dup{seen_ids[nid]}"
        else:
            seen_ids[nid] = 1
        prepared.append((nid, it))
    first = [process_note(nid, it.intake_note_text, it.source_channel, it.received_date) for nid, it in prepared]
    by_ref: dict[str, list[int]] = defaultdict(list)
    for idx, res in enumerate(first):
        ref = res.extracted_facts.claimant_reference
        if ref.value and ref.status in ("found", "tentative"):
            by_ref[ref.value].append(idx)
    extra: dict[int, list[str]] = {}
    for ref, idxs in by_ref.items():
        if len(idxs) > 1:
            for i in idxs:
                others = ", ".join(prepared[j][0] for j in idxs if j != i)
                extra.setdefault(i, []).append(f"claimant reference {ref} also appears in {others} (possible duplicate or follow-up)")
    out: list[ProcessedNote] = []
    for idx, (nid, it) in enumerate(prepared):
        if idx not in extra:
            out.append(first[idx])
            continue
        res = process_note(nid, it.intake_note_text, it.source_channel, it.received_date, extra_ambiguity=extra[idx])
        a = res.assessment
        if "POSSIBLE_DUPLICATE" not in a.operational_tags:
            a.operational_tags.append("POSSIBLE_DUPLICATE")
        reason = "claimant reference is shared with another note in this batch"
        if reason not in a.manual_review_reasons:
            a.manual_review_reasons.append(reason)
        a.manual_review_required = "Yes"
        a.recommended_reviewer_queue = C.MANUAL_QUEUE
        if a.detected_claim_category not in (C.UNCLEAR_CATEGORY, "Third-Party Contact"):
            a.intended_queue_after_clarification = C.CATEGORY_TO_QUEUE.get(a.detected_claim_category)
        a.readiness_status = "Manual review before routing"
        a.confidence_score = max(0, a.confidence_score - 5)
        a.confidence_reasons.append("claimant reference shared with another note")
        a.confidence_level = "High" if a.confidence_score >= C.CONFIDENCE_HIGH else "Medium" if a.confidence_score >= C.CONFIDENCE_MEDIUM else "Low"
        res.generated = _generate_text(nid, res.extracted_facts, a)
        out.append(res)
    return out
