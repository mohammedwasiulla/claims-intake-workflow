"""Rule-based extraction of predictable fields. Every value returned carries the evidence it came from.

Principle: if the note does not say it, the field is ``missing`` - never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

from . import config as C
from .schema import AmountField, DateField, DocumentMention, ExtractedField

# --------------------------------------------------------------------------- text preparation
_SIGNATURE_RE = re.compile(r"^\s*(?:--\s*$|regards\b|thanks\b|thank you\b|best regards\b|sent from my\b|warm regards\b)", re.I)
_DISCLAIMER_RE = re.compile(r"^\s*(?:this (?:e-?mail|message) (?:is|may)|confidential|disclaimer|please consider the environment)", re.I)


def clean_note(text: str) -> str:
    """Normalise unicode/whitespace and drop obvious email noise (quoted replies, signatures, disclaimers)."""
    text = unicodedata.normalize("NFKC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    kept: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            continue
        if _SIGNATURE_RE.match(line) or _DISCLAIMER_RE.match(line):
            break  # everything after a signature/disclaimer is boilerplate
        kept.append(line.rstrip())
    out = "\n".join(kept)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", out)).strip()


def split_clauses(text: str) -> list[str]:
    """Split into sentence-like clauses (newlines, sentence stops, semicolons)."""
    parts: list[str] = []
    for line in text.split("\n"):
        for p in re.split(r"(?<=[.;!?])\s+", line):
            p = p.strip()
            if p:
                parts.append(p)
    return parts


def snippet(text: str, start: int, end: int, pad: int = 25, limit: int = 140) -> str:
    s = text[max(0, start - pad): min(len(text), end + pad)].replace("\n", " ").strip()
    return s if len(s) <= limit else s[:limit].rstrip() + "..."


def is_missing_value(v: str) -> bool:
    v = (v or "").strip().strip(".:;,-").lower()
    if not v or v in {"?", "n/a", "na", "nil", "none", "blank", "unknown", "tbd", "missing", "unclear"}:
        return True
    return bool(re.search(r"\b(?:n/a|not\s+(?:stated|captured|shared|mentioned|given|provided|available|confirmed|visible|readable|known|clear)|blank|unknown)\b", v)) or v.startswith("location n/a") or v.startswith("date n/a")


def missing_reason(v: str) -> str:
    v = (v or "").strip().strip(".:;,").strip()
    return f"note says '{v}'" if v else "no value given in the note"


# --------------------------------------------------------------------------- references
_POL_RE = re.compile(r"\bPOL[-\s]?(\d{3,8})\b", re.I)
_CLM_RE = re.compile(r"\bCLMNT[-\s]?(\d{3,8})\b", re.I)


def _id_field(text: str, regex: re.Pattern, prefix: str, tentative_words: str, missing_patterns: list[tuple[str, str, str]]) -> ExtractedField:
    found: dict[str, tuple[int, int, bool]] = {}
    for m in regex.finditer(text):
        norm = f"{prefix}-{m.group(1)}"
        before = text[max(0, m.start() - 30): m.start()].lower()
        tent = bool(re.search(tentative_words, before))
        if norm not in found or (found[norm][2] and not tent):
            found[norm] = (m.start(), m.end(), tent)
    if len(found) > 1:
        ids = sorted(found)
        ev = " / ".join(snippet(text, found[i][0], found[i][1], 15, 60) for i in ids)
        return ExtractedField(value=", ".join(ids), status="unclear", evidence=ev, detail=f"multiple different references found: {', '.join(ids)}")
    if len(found) == 1:
        norm, (s, e, tent) = next(iter(found.items()))
        ev = snippet(text, s, e, 30, 90)
        if tent:
            return ExtractedField(value=norm, status="tentative", evidence=ev, detail="note presents this reference as uncertain or a placeholder")
        return ExtractedField(value=norm, status="found", evidence=ev)
    for pat, status, reason in missing_patterns:
        m = re.search(pat, text, re.I)
        if m:
            return ExtractedField(value=None, status=status, evidence=snippet(text, m.start(), m.end(), 10, 80), detail=reason)  # type: ignore[arg-type]
    return ExtractedField(value=None, status="missing", detail="not mentioned in the note")


def extract_policy(text: str) -> ExtractedField:
    return _id_field(
        text, _POL_RE, "POL", r"(?:maybe|possibly|probably|perhaps|unclear|\?)\W*(?:\w+\W+){0,2}$",
        [
            (r"policy[^.;\n]{0,30}\b(?:not\s+readable|unreadable)", "unclear", "policy reference present but not readable"),
            (r"policy(?:\s+holder)?\s+ref(?:erence)?\s*:?\s*blank", "missing", "policy field left blank"),
            (r"policy[^.;\n]{0,25}not\s+visible", "missing", "policy not visible in the source email"),
            (r"policy\s+ref[^.;\n]{0,20}not\s+given", "missing", "policy reference not given"),
            (r"no\s+policy\s+(?:number|ref\w*)", "missing", "note says no policy number was given"),
            (r"policy[^.;\n]{0,15}maybe\s+missing", "missing", "note says policy is missing"),
            (r"\bpol(?:icy|\.)?\s*\?", "missing", "policy shown as '?'"),
        ],
    )


def extract_claimant(text: str) -> ExtractedField:
    f = _id_field(
        text, _CLM_RE, "CLMNT", r"placeholder\W*(?:\w+\W+){0,1}$",
        [(r"no\s+claimant\s+(?:ref|id)\w*", "missing", "note says no claimant reference")],
    )
    return f


# --------------------------------------------------------------------------- dates
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMON = re.compile(r"\b(\d{1,2})[\s\-/]([A-Za-z]{3,9})\.?(?:[\s\-/,]+(\d{4}|\d{2}))?\b")
_NUM = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b")
_REL = re.compile(r"\b(last\s+(?:week|month|night)|yesterday|today|day\s+before\s+yesterday|a\s+few\s+days\s+ago|\d+\s+days?\s+ago)\b", re.I)
_DATE_LABEL = re.compile(
    r"(?:\b(?:loss|incident|accident)\s+date|\bdate\s+of\s+(?:loss|incident|accident)|\bdate\b)"
    r"(?:\s+field)?(?:\s+(?:filled\s+as|entered\s+as|approx\.?|approximately|is|was))?\s*[:\-]?\s*(?P<v>[^;|\n,]*)", re.I)
_HAPPENED_ON = re.compile(r"happened\s+(?:at|in)\s+.+?\s+on\s+(?P<v>[^.;\n|]+)", re.I)
_MISSING_DATE_REMARK = re.compile(r"\b(?:incident|loss)\s+date\s+(?:missing|not\s+(?:given|captured|provided|clear))", re.I)


def _valid_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def classify_date_text(v: str, received: Optional[date] = None) -> tuple[str, Optional[str], str]:
    """Return (date_status, iso_or_None, note). Never resolves a missing year or an ambiguous dd/mm."""
    raw = v.strip().strip(".")
    if is_missing_value(raw):
        return ("unconfirmed" if re.search(r"not\s+confirmed", raw, re.I) else "missing"), None, f"note says '{raw or 'blank'}'"
    approx = bool(re.search(r"\b(?:approx\w*|around|about)\b", v, re.I))
    m = _ISO.search(raw)
    if m:
        y, mo, d = map(int, m.groups())
        dt = _valid_date(y, mo, d)
        if not dt:
            return "invalid", None, "not a real calendar date"
        return ("approximate" if approx else "complete"), dt.isoformat(), ""
    m = _NUM.search(raw)
    if m:
        a, b, y = m.groups()
        a, b = int(a), int(b)
        y = int(y) + 2000 if len(y) == 2 else int(y)
        if a > 12 and b <= 12:      # day-first is the only possible reading
            dt = _valid_date(y, b, a)
        elif b > 12 and a <= 12:    # month-first is the only possible reading
            return "ambiguous", None, f"{raw}: day/month order unclear"
        elif a == b:
            dt = _valid_date(y, b, a)
        else:
            return "ambiguous", None, f"{raw}: could be day/month or month/day"
        if not dt:
            return "invalid", None, "not a real calendar date"
        return "complete", dt.isoformat(), ""
    m = _DMON.search(raw)
    if m and m.group(2)[:3].lower() in _MONTHS:
        d, mon, y = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], m.group(3)
        if y is None:
            return "partial", None, "year not stated in the note"
        yy = int(y) + 2000 if len(y) == 2 else int(y)
        dt = _valid_date(yy, mon, d)
        if not dt:
            return "invalid", None, "not a real calendar date"
        return ("approximate" if approx else "complete"), dt.isoformat(), ""
    if _REL.search(raw):
        return "relative", None, "only a relative time reference"
    return "missing", None, f"no recognisable date in '{raw}'"


def numeric_readings(raw: str, received: Optional[date]) -> list[str]:
    """For dd/mm vs mm/dd ambiguity: the readings that are real dates and not later than the received date."""
    m = _NUM.search(raw)
    if not m:
        return []
    a, b, y = m.groups()
    y = int(y) + 2000 if len(y) == 2 else int(y)
    out: list[str] = []
    for dd, mm in ((int(a), int(b)), (int(b), int(a))):
        dt = _valid_date(y, mm, dd)
        if dt and (received is None or dt <= received) and dt.isoformat() not in out:
            out.append(dt.isoformat())
    return out


_PRIORITY = {"complete": 0, "approximate": 1, "partial": 2, "ambiguous": 3, "invalid": 4, "relative": 5, "unconfirmed": 6, "missing": 7}


def extract_incident_date(text: str, received: Optional[date]) -> tuple[DateField, list[str], bool]:
    """Return (field, extra_flags, remark_says_missing). Flags cover multiple/future dates; invalid/ambiguous are reported by the caller."""
    cands: list[tuple[int, str, str, str, str, str]] = []  # (pos, status, iso, note, raw, evidence)
    for rx in (_DATE_LABEL, _HAPPENED_ON):
        for m in rx.finditer(text):
            v = re.split(r"\.\s|\.$|\s//\s", m.group("v").strip())[0].strip()
            v = re.split(r"\s+(?:at|in|near)\s+", v)[0].strip()          # "06-Jun-2026 at Pune" -> "06-Jun-2026"
            st, iso, note = classify_date_text(v, received)
            cands.append((m.start("v"), st, iso or "", note, v, snippet(text, m.start(), m.end(), 5, 100)))
    remark_missing = bool(_MISSING_DATE_REMARK.search(text))
    real = [c for c in cands if c[1] not in ("missing", "unconfirmed")]
    if not real:  # unlabeled fallbacks
        for rx in (_ISO, _NUM, _DMON, _REL):
            for m in rx.finditer(text):
                if rx is _DMON and m.group(2)[:3].lower() not in _MONTHS:
                    continue
                if rx is _REL and not re.search(r"(?:accident|incident|happened|occurred|damage[d]?|loss|fell|hit|collision|broke)\W+(?:\w+\W+){0,6}$", text[max(0, m.start() - 60): m.start()], re.I):
                    continue   # "approve my claim today" is not an incident date
                st, iso, note = classify_date_text(m.group(0), received)
                if st != "missing":
                    cands.append((m.start(), st, iso or "", note, m.group(0), snippet(text, m.start(), m.end(), 30, 100)))
        real = [c for c in cands if c[1] not in ("missing", "unconfirmed")]
    flags: list[str] = []
    if real:
        # de-duplicate the same date written twice (same ISO date or identical text), keeping note order
        distinct: dict[str, tuple] = {}
        for c in sorted(real, key=lambda c: c[0]):
            key = c[2] or c[4].lower()
            distinct.setdefault(key, c)
        if len(distinct) > 1:
            raws = [c[4] for c in distinct.values()]
            isos = [c[2] for c in distinct.values() if c[2]]
            first = next(iter(distinct.values()))
            return (DateField(value=" / ".join(raws), status="unclear", evidence=" | ".join(c[5] for c in distinct.values())[:200],
                              detail="more than one date reference in the note", iso_date=None, date_status="ambiguous", candidate_iso_dates=isos),
                    [f"more than one date reference found ({' / '.join(raws)}); unclear which is the incident date"], remark_missing)
        best = min(real, key=lambda c: _PRIORITY[c[1]])
        _, st, iso, note, raw, ev = best
        status_map = {"complete": "found", "approximate": "tentative", "partial": "unclear", "ambiguous": "unclear", "invalid": "invalid", "relative": "unclear"}
        fld = DateField(value=raw, status=status_map[st], evidence=ev, detail=note or None, iso_date=iso or None, date_status=st)  # type: ignore[arg-type]
        if st == "ambiguous":
            fld.candidate_iso_dates = numeric_readings(raw, received)
            if len(fld.candidate_iso_dates) == 1:
                fld.detail = f"{raw}: day/month order unclear; only {fld.candidate_iso_dates[0]} is not later than the received date (not auto-resolved)"
        if iso and received and date.fromisoformat(iso) > received:
            flags.append(f"incident date {iso} is later than the received date {received.isoformat()}")
        return fld, flags, remark_missing
    if cands:
        c = cands[0]
        return DateField(value=None, status="missing", evidence=c[5], detail=c[3], date_status="unconfirmed" if c[1] == "unconfirmed" else "missing"), flags, remark_missing
    return DateField(value=None, status="missing", detail="not mentioned in the note", date_status="missing"), flags, remark_missing


# --------------------------------------------------------------------------- location
_LOC_PATTERNS = [
    re.compile(r"\bLocation(?:\s+field)?\s*[:\-]?\s*(?P<v>[^;|\n,.]+)", re.I),
    re.compile(r"\bLoc\s*[:\-]\s*(?P<v>[^;|\n.]+)", re.I),
    re.compile(r"\bCity\s*[:\-]\s*(?P<v>[^;|\n.]+)", re.I),
    re.compile(r"\bplace\s+(?P<v>[^,;\n]+?)\s*,\s*date", re.I),
    re.compile(r"happened\s+(?:at|in)\s+(?P<v>.+?)\s+on\s+", re.I),
]
_NO_LOC = re.compile(r"\bno\s+(?:incident\s+)?location\b", re.I)


def extract_location(text: str) -> ExtractedField:
    vals: list[tuple[str, str]] = []
    miss: Optional[tuple[str, str]] = None
    for rx in _LOC_PATTERNS:
        for m in rx.finditer(text):
            v = re.split(r"\s+on\s+\d", m.group("v").strip().strip("."))[0].strip()   # "n/a on 19 Mar" -> "n/a"
            ev = snippet(text, m.start(), m.end(), 5, 100)
            if is_missing_value(v):
                miss = miss or (v, ev)
            else:
                vals.append((v, ev))
    uniq = {v.lower(): (v, ev) for v, ev in vals}
    if len(uniq) > 1:
        return ExtractedField(value=" / ".join(v for v, _ in uniq.values()), status="unclear", evidence=" | ".join(ev for _, ev in uniq.values()), detail="more than one different location in the note")
    if uniq:
        v, ev = next(iter(uniq.values()))
        return ExtractedField(value=v, status="found", evidence=ev)
    m = _NO_LOC.search(text)
    if m:
        return ExtractedField(value=None, status="missing", evidence=snippet(text, m.start(), m.end(), 5, 60), detail="note says no location was given")
    if miss:
        return ExtractedField(value=None, status="missing", evidence=miss[1], detail=missing_reason(miss[0]))
    hits: list[tuple[int, int, str]] = []
    for city in sorted(C.KNOWN_CITIES, key=len, reverse=True):   # longest first so "Delhi NCR" wins over "Delhi"
        for m in re.finditer(rf"\b{re.escape(city)}\b", text):
            if not any(m.start() < e and m.end() > st for st, e, _ in hits):
                hits.append((m.start(), m.end(), city))
    hits.sort()
    cities = list(dict.fromkeys(c for _, _, c in hits))
    if len(cities) > 1:
        return ExtractedField(value=" / ".join(cities), status="unclear", evidence=snippet(text, hits[0][0], hits[-1][1], 15, 120), detail="more than one place named in the note")
    if cities:
        st, e, c = hits[0]
        return ExtractedField(value=c, status="found", evidence=snippet(text, st, e, 25, 90), detail="city name mentioned without a field label")
    return ExtractedField(value=None, status="missing", detail="not mentioned in the note")


# --------------------------------------------------------------------------- amount
_AMT = re.compile(r"(?P<q>around|approx(?:imately)?\.?|about|est(?:imated)?\.?)?\s*(?:₹|rs\.?|inr)\s?(?P<n>\d[\d,]*(?:\.\d+)?)\s?(?P<u>k|l|lakhs?|lacs?|cr|crore)?(?![A-Za-z])(?P<after>\s+quoted)?", re.I)
_UNIT = {"k": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "cr": 1e7, "crore": 1e7}


def extract_amount(text: str) -> AmountField:
    found: list[tuple[str, float, str, int, int]] = []
    for m in _AMT.finditer(text):
        try:
            n = float(m.group("n").replace(",", "").rstrip("."))
        except ValueError:
            continue
        n *= _UNIT.get((m.group("u") or "").lower(), 1)
        qual = (m.group("q") or "").strip().lower().rstrip(".") or ("quoted" if m.group("after") else "")
        found.append((m.group(0).strip(), n, qual, m.start(), m.end()))
    if found:
        uniq = {round(x[1]): x for x in found}
        first = found[0]
        all_raw = [x[0] for x in uniq.values()]
        fld = AmountField(value=first[0] if len(uniq) == 1 else "; ".join(all_raw), status="found" if len(uniq) == 1 else "unclear",
                          evidence=snippet(text, first[3], first[4], 15, 90), amount_inr=first[1] if len(uniq) == 1 else None,
                          qualifier=first[2] or None, all_amounts_found=all_raw)
        if len(uniq) > 1:
            fld.detail = "several different amounts in the note"
        elif first[2] in ("around", "approx", "approximately", "about", "est", "estimated"):
            fld.status = "tentative"
            fld.detail = "approximate figure"
        return fld
    m = re.search(r"small\s+amount(?:\s+as\s+per\s+\w+)?", text, re.I)
    if m:
        return AmountField(value=m.group(0), status="unclear", evidence=snippet(text, m.start(), m.end(), 10, 80), detail="described in words only; no figure given")
    m = re.search(r"(?:amount|amt|est(?:imate)?)\s*(?:amt)?\s*:?\s*(?:not\s+(?:yet\s+)?(?:stated|estimated|given|known)|n/a)|not\s+yet\s+estimated|amount\s+not\s+stated", text, re.I)
    if m:
        return AmountField(value=None, status="missing", evidence=snippet(text, m.start(), m.end(), 10, 80), detail=f"note says '{m.group(0).strip()}'")
    return AmountField(value=None, status="missing", detail="not mentioned in the note")


# --------------------------------------------------------------------------- documents & information items
def _compile(terms: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    return [(re.compile(rf"\b(?:{p})\b", re.I), g) for p, g in sorted(terms.items(), key=lambda kv: -len(kv[0]))]


_DOC_RX, _INFO_RX = _compile(C.DOC_TERMS), _compile(C.INFO_TERMS)
_AVAIL_RX = [(re.compile(p, re.I), n) for p, n in C.AVAILABILITY_CUES.items()]
_QUAL_RX = [(re.compile(p, re.I), n) for p, n in C.QUALITY_CUES.items()]
_SENT_WORDS = re.compile(r"(?<!not\s)\b(?:sent|attached|uploaded|submitted|shared|forwarded|enclosed)\b", re.I)
_UNREADABLE_GENERIC = re.compile(r"\(?\s*(?:one\s+)?attachments?\s+(?:is\s+)?unreadable\s*\)?", re.I)


def _term_spans(clause: str, rxs: list[tuple[re.Pattern, str]]) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    for rx, group in rxs:
        for m in rx.finditer(clause):
            if any(m.start() < e and m.end() > s for s, e, _, _ in spans):
                continue  # longer term already claimed this text
            spans.append((m.start(), m.end(), m.group(0).lower(), group))
    return sorted(spans)


def _cue_after(clause: str, end: int, all_spans: list[tuple[int, int, str, str]]) -> Optional[tuple[str, str, int]]:
    """Nearest availability/quality cue after a term, within 6 words and without crossing another term."""
    best: Optional[tuple[int, str, str]] = None
    for kind, rxs in (("availability", _AVAIL_RX), ("quality", _QUAL_RX)):
        for rx, norm in rxs:
            m = rx.search(clause, end)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), kind, norm)
    if not best:
        return None
    gap = clause[end:best[0]]
    if len(gap.split()) > 6 or any(s >= end and s < best[0] for s, _, _, _ in all_spans):
        return None
    return best[1], best[2], best[0]


def extract_documents(text: str) -> tuple[list[DocumentMention], list[str], list[str], dict]:
    """Return (document_details, gaps_stated, flags, extras).

    * a document in a positive clause is 'mentioned'
    * a document followed by an availability cue is 'reported_missing' (or 'mentioned_not_available' when the same
      clause says it was sent)
    * a document that is both listed and reported missing in different clauses is 'mentioned_conflicting'
    * the generic remark "(one attachment unreadable)" is NOT attached to a specific document (the note does not say which)
    """
    docs: dict[str, dict] = {}
    gaps: list[str] = []
    flags: list[str] = []
    extras = {"no_attachments": False, "unreadable_unspecified": False, "third_party_not_applicable": False, "papers_not_ready": False}
    order: list[str] = []
    unreadable_clauses: set[int] = set()
    for ci, raw_clause in enumerate(split_clauses(text)):
        clause = raw_clause
        if re.search(r"\bno\s+attachments?(?:\s+found)?\b", clause, re.I):
            extras["no_attachments"] = True
        if re.search(r"\bpapers?\s+(?:are\s+)?not\s+ready\b", clause, re.I):
            extras["papers_not_ready"] = True
        if _UNREADABLE_GENERIC.search(clause):
            extras["unreadable_unspecified"] = True
            unreadable_clauses.add(ci)
            clause = _UNREADABLE_GENERIC.sub(lambda m: " " * len(m.group(0)), clause)  # keep indices stable
        spans = sorted(_term_spans(clause, _DOC_RX) + _term_spans(clause, _INFO_RX))
        for s, e, surface, group in spans:
            is_info = group in C.INFO_TERMS.values()
            cue = _cue_after(clause, e, spans)
            # "No third-party info since damage was noticed later": stated as not applicable, not a gap
            pre = clause[max(0, s - 6): s].lower()
            if is_info and re.search(r"\bno\s+$", pre) and re.search(r"\b(?:since|because|as)\b", clause[e:], re.I):
                extras["third_party_not_applicable"] = True
                continue
            d = docs.setdefault(group, {"name": surface, "info": is_info, "pos": [], "avail": [], "qual": []})
            if group not in order:
                order.append(group)
            if cue is None:
                if not is_info:
                    d["pos"].append((ci, raw_clause))
                continue
            kind, norm, cue_start = cue
            gaps.append(f"{surface} {norm}")
            if kind == "quality":
                d["qual"].append((ci, raw_clause, norm))
                if not is_info:
                    d["pos"].append((ci, raw_clause))
            else:
                region_start = max(clause.rfind(",", 0, s), clause.rfind(":", 0, s)) + 1
                sent_same_clause = (not is_info) and bool(_SENT_WORDS.search(clause[region_start:cue_start]))
                d["avail"].append((ci, raw_clause, norm, sent_same_clause))
    details: list[DocumentMention] = []
    for key in order:
        d = docs[key]
        if d["info"]:
            continue  # information items surface as gaps/flags, not as documents
        pos_clauses = {c for c, _ in d["pos"]}
        avail_other = [a for a in d["avail"] if a[0] not in pos_clauses and not a[3]]
        avail_same = [a for a in d["avail"] if a[3]]
        if avail_same:
            status, ev, det = "mentioned_not_available", avail_same[0][1], f"sent/mentioned but {avail_same[0][2]}"
        elif d["pos"] and avail_other:
            status, ev = "mentioned_conflicting", avail_other[0][1]
            det = f"listed as provided in one place but reported {avail_other[0][2]} in another (may be an earlier state)"
            flags.append(f"'{d['name']}' is listed as provided but also reported {avail_other[0][2]}; verify which is current")
        elif d["avail"]:
            status, ev, det = "reported_missing", d["avail"][0][1], f"reported {d['avail'][0][2]}"
        elif d["qual"] and extras["no_attachments"]:
            status, ev, det = "reported_missing", d["qual"][0][1], f"reported {d['qual'][0][2]}; note also says no attachments found"
        elif d["qual"]:
            status, ev, det = "quality_issue", d["qual"][0][1], f"present but {d['qual'][0][2]}"
        else:
            status, ev, det = "mentioned", d["pos"][0][1], None
            if any(c in unreadable_clauses for c, _ in d["pos"]):
                det = "one attachment in this list is unreadable (the note does not say which)"
        details.append(DocumentMention(name=d["name"], status=status, evidence=ev[:160], detail=det))  # type: ignore[arg-type]
    for key in order:
        d = docs[key]
        if d["info"] and key in C.HARD_INFO_ITEMS and (d["avail"] or d["qual"]):
            cue = (d["avail"] or d["qual"])[0]
            flags.append(f"{d['name']} {cue[2]}")
    seen: set[str] = set()
    gaps = [g for g in gaps if not (g in seen or seen.add(g))]
    if extras["unreadable_unspecified"]:
        gaps.append("one attachment unreadable (document not identified in the note)")
    if extras["papers_not_ready"]:
        gaps.append("supporting papers not ready")
    return details, gaps, flags, extras


_MISMATCH = re.compile(r"[^.;\n]*\b(?:do(?:es)?\s+not\s+match|don't\s+match|doesn't\s+match|mismatch\w*|discrepanc\w+)\b[^.;\n]*", re.I)


def extract_mismatch_statements(text: str) -> list[str]:
    return [m.group(0).strip() for m in _MISMATCH.finditer(text)]


# --------------------------------------------------------------------------- follow-ups, remarks, category hints
_FOLLOWUPS: list[tuple[str, str]] = [
    (r"\bno\s+call\s*back\s+needed\b", "No call back needed"),
    (r"\bcall\s*back\s+requested\b", "Call back requested"),
    (r"\bemail\s+follow-?up\s+preferred\b", "Email follow-up preferred"),
    (r"\b(?:reachable|call\s+(?:him|her|them|me|back)?)\s*after\s+[\d:.]+\s*(?:am|pm)\b", "Reachable only after the time stated in the note"),
    (r"\b(?:please\s+)?(?:approve|settle|pay|release\s+(?:the\s+)?payment)\b[^.\n]{0,30}\bclaim\b|\bapprove\s+my\b", "Claimant asks for a claim decision or payment - outside this workflow, for the reviewer"),
    (r"\b(?:at\s+fault|fraud|blame\w*|liab\w+)\b", "Note contains statements about blame or misconduct - not assessed here"),
    (r"\basked\s+for\s+(?:a\s+)?status\s+update\b", "Claimant asked for a status update"),
    (r"\bneed\s+to\s+know\s+what\s+else\s+is\s+required\b", "Claimant asks what else is required"),
    (r"\bwants\s+to\s+know\s+whether\s+inspection\s+is\s+required\b", "Caller asks whether an inspection is required"),
    (r"\bsender\s+asking\s+for\s+call\s*back\s+but\s+number\s+masked\b", "Callback requested but the phone number is masked"),
    (r"\bplease\s+verify\s+docs\b", "Verify the listed documents"),
    (r"\bbranch\s+asked\s+ops\s+to\s+review\s+docs\b", "Branch asked ops to review documents before forwarding"),
    (r"\bplease\s+re-?classify\b", "Submitter/ops asked for the category to be re-classified"),
    (r"\bflag\s+date\s+issue\b", "Ops asked for the date issue to be flagged"),
    (r"\brepair\s+quot(?:e|ation)\s+to\s+be\s+sent\s+\w+", "Repair quote promised later"),
]
_REMARKS: list[tuple[str, str]] = [
    (r"[^.\n]*\bre-?check\s+manually\b[^.\n]*\.?", "RECHECK"),
    (r"[^.\n]*\bplease\s+re-?classify\b[^.\n]*\.?", "RECHECK"),
    (r"[^.\n]*\bdo\s+not\s+send\s+to\s+final\s+review\b[^.\n]*\.?", "HOLD"),
    (r"[^.\n]*\bduplicate\s+note\s+may\s+exist\b[^.\n]*\.?", "DUPLICATE"),
    (r"[^.\n]*\bcategory\s+selected\s+by\s+user\s+may\s+be\s+inaccurate\b[^.\n]*\.?", "CATEGORY_SELF_REPORTED"),
    (r"[^.\n]*\bclaim\s+note\s+has\s+mixed\s+info\b[^.\n]*\.?", "MIXED_INFO"),
    (r"[^.\n]*\bops\s+copied\s+from\s+prior\s+mail\s+thread\b[^.\n]*", "COPIED_THREAD"),
    (r"[^.\n]*\bmain\s+issue\s+appears\s+to\s+be\b", None),  # not an instruction; ignored
]


def extract_follow_ups(text: str) -> list[str]:
    out: list[str] = []
    for pat, label in _FOLLOWUPS:
        m = re.search(pat, text, re.I)
        if m and label.startswith("Reachable"):
            label = f"Contact window stated in note: '{m.group(0).strip()}'"
        if m and label not in out:
            out.append(label)
    if re.search(r"\bno\s+call\s*back\s+needed\b", text, re.I) and "Call back requested" in out:
        out.remove("Call back requested")  # "no call back needed" contains "call back"; keep the stronger reading
    return out


def extract_remarks(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for pat, tag in _REMARKS:
        if tag is None:
            continue
        for m in re.finditer(pat, text, re.I):
            out.append((tag, m.group(0).strip()))
    return out


_USER_SELECTED = re.compile(r"\buser\s+selected\s+(?P<c>[A-Za-z/ ]+?)\s+category\b", re.I)


def extract_user_selected_category(text: str) -> Optional[str]:
    m = _USER_SELECTED.search(text)
    return m.group("c").strip().lower() if m else None


# --------------------------------------------------------------------------- incident description
_INCIDENT_PATTERNS = [
    re.compile(r"Incident details entered:\s*(?P<v>[^.\n]+)", re.I),
    re.compile(r"Main issue appears to be:\s*(?P<v>[^;\n]+)", re.I),
    re.compile(r"Please register claim\.\s*(?P<v>[^.\n]+?)\.\s*I have sent", re.I),
    re.compile(r"CLMNT-\d+\s+says\s+(?P<v>[^.\n]+)", re.I),
    re.compile(r"CLMNT-\d+\s+-\s+(?P<v>[^.\n]+)", re.I),
    re.compile(r"^(?P<v>[^;\n]+?);\s*happened\s+(?:at|in)\b", re.I | re.M),
]
_LEAD_STRIP = re.compile(r"^\s*(?:Only message received:\s*['\"]?|Source [A-Za-z ]+\.|Branch note:|Partner uploaded:|Web intake form[^:]*:|CALL LOG /[^:]*:|FWD from service inbox[^\n]*\n|Customer message:)\s*", re.I)


_USER_SEL_PREFIX = re.compile(r"^user\s+selected\s+[A-Za-z/ ]+?\s+category\s+but\s+(?:the\s+)?note\s+says\s+", re.I)


def extract_incident_description(text: str) -> Optional[str]:
    d = _extract_incident_description(text)
    return _USER_SEL_PREFIX.sub("", d).strip() if d else d


def _extract_incident_description(text: str) -> Optional[str]:
    for rx in _INCIDENT_PATTERNS:
        m = rx.search(text)
        if m:
            v = m.group("v").strip().strip('"').strip()
            if len(v) >= 8:
                return v
    body = text
    body = re.sub(r"^\s*(?:subject|from|to|cc|date|sent)\s*:.*$", "", body, flags=re.I | re.M)       # email header lines
    body = re.sub(r"^\s*(?:hello|hi|dear|good\s+(?:morning|afternoon|evening))\b[^,\n]{0,30},?\s*", "", body, flags=re.I | re.M)
    for _ in range(3):
        body = _LEAD_STRIP.sub("", body)
    sentences = [s for s in split_clauses(body) if len(s) > 12 and not re.match(r"^(?:Ref|Policy|Docs|Attached|Reviewer|System|Ops note|Need check)\b", s, re.I)]
    if not sentences:
        return None

    def kw_score(sent: str) -> int:   # sentence that carries the most incident vocabulary is the incident sentence
        return sum(1 for rules in C.CATEGORY_RULES.values() for rx, w in rules if w >= 2 and re.search(rx, sent, re.I))
    best = max(range(len(sentences)), key=lambda i: (kw_score(sentences[i]), -i))
    if kw_score(sentences[best]) == 0:
        best = 0
    out = sentences[best]
    if kw_score(out) == 0 and len(out) < 30 and len(sentences) > best + 1 and len(out) + len(sentences[best + 1]) < 200:
        out = out + " " + sentences[best + 1]
    return out.strip("'\" ")[:260]
