"""Compare outputs with the dataset's starter labels (a *reference*, not ground truth) and run grounding checks."""
import json, pathlib, re, sys
import pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claims_intake.io_utils import load_notes
from claims_intake.pipeline import process_inputs

df = pd.read_csv(ROOT / "data" / "claim_intake_notes.csv", dtype=str, keep_default_na=False)
res = {r.claim_note_id: r for r in process_inputs(load_notes(ROOT / "data" / "claim_intake_notes.csv"))}
df["cat"] = [res[i].assessment.detected_claim_category for i in df.claim_note_id]
df["queue"] = [res[i].assessment.recommended_reviewer_queue for i in df.claim_note_id]
df["urg"] = [res[i].assessment.urgency_indicator for i in df.claim_note_id]
df["man"] = [res[i].assessment.manual_review_required for i in df.claim_note_id]
df["conf"] = [res[i].assessment.confidence_level for i in df.claim_note_id]

STOP = {"not", "to", "be", "the", "and", "a", "of", "as", "per", "note", "in", "is", "by"}
def words(s): return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP}
def hint_hit(i, hint):
    blob = " ".join(res[i].assessment.missing_information_flags + res[i].assessment.ambiguity_conflict_flags + res[i].assessment.manual_review_reasons).lower()
    hw = words(hint)
    return bool(hw) and len(hw & words(blob)) / len(hw) >= 0.6
hinted = df[df.missing_detail_hint != ""]
hits = [hint_hit(r.claim_note_id, r.missing_detail_hint) for r in hinted.itertuples()]

tp = ((df.man == "Yes") & (df.expected_manual_review == "Yes")).sum()
fp = ((df.man == "Yes") & (df.expected_manual_review == "No")).sum()
fn = ((df.man == "No") & (df.expected_manual_review == "Yes")).sum()
tn = ((df.man == "No") & (df.expected_manual_review == "No")).sum()

def rate(col): return int((df[col[0]] == df[col[1]]).sum())
out = {
    "notes": len(df),
    "category_agreement": {"match": rate(("cat", "starter_claim_category_label")), "of": len(df),
                           "differs": df[df.cat != df.starter_claim_category_label][["claim_note_id", "cat", "starter_claim_category_label"]].to_dict("records")},
    "queue_agreement_with_starter": {"match": rate(("queue", "recommended_queue_label")), "of": len(df)},
    "urgency_agreement_with_starter": {"match": rate(("urg", "starter_urgency_label")), "of": len(df)},
    "manual_review_vs_starter": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
                                 "precision": round(tp / (tp + fp), 2), "recall": round(tp / (tp + fn), 2)},
    "starter_missing_hint_found_in_our_flags": {"found": int(sum(hits)), "of": len(hits)},
    "our_distribution": {
        "manual_review": df.man.value_counts().to_dict(), "confidence": df.conf.value_counts().to_dict(), "urgency": df.urg.value_counts().to_dict(),
        "readiness": pd.Series([r.assessment.readiness_status for r in res.values()]).value_counts().to_dict(),
        "queues": df["queue"].value_counts().to_dict(),
    },
    "missed_hints": [(r.claim_note_id, r.missing_detail_hint) for r, h in zip(hinted.itertuples(), hits) if not h],
}
(ROOT / "outputs" / "evaluation_results.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
print(json.dumps(out, indent=2, default=str))
