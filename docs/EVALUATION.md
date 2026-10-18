# Evaluation summary

Run: `python scripts/run_evaluation.py` (numbers in `outputs/evaluation_results.json`). 85 synthetic notes + 7 extra notes written for testing.

**Important:** the dataset's starter labels are *reference points, not ground truth* (the pack says so). Disagreement is not automatically an error.

## Results on the 85 notes

| Check | Result |
|---|---|
| Runs end to end, one structured row per note (JSON, CSV, HTML) | 85 / 85; API, CLI and `.txt` exports give identical assessments |
| Output validates against the Pydantic schema | 85 / 85 |
| Every `found`/`tentative` reference, location, date and document appears in the note text (no invented details) | 85 / 85 (automated test) |
| Generated text free of decision wording (approve, reject, liable, fraud ...) | 85 / 85 (automated test) |
| Hand-checked gold notes (16: fields, category, manual flag, queue where relevant) | 16 / 16 |
| Dataset test cases TC-01..TC-08 | all pass |
| Category vs starter label | 84 / 85. The one difference, CI-2026-0081 ("accident happened last week", no vehicle mentioned), is deliberately **Unclear** instead of Motor |
| Starter `missing_detail_hint` visible in our flags | 84 / 85. The miss, CI-2026-0084, is correct: the note says third-party details are not applicable |
| Queue vs starter queue | 42 / 85 (see below) |
| Urgency vs starter urgency | 56 / 85 (see below) |
| Manual review vs starter flag | precision 0.77, recall 0.47 (we flag 39, starter 64) |

## Reading the disagreements
- **Manual review / queue.** The starter marks a note for manual review when even one document is pending. This workflow separates *Needs more information* (45 notes: follow up, then normal queue) from *Manual review* (39: conflicts, invalid dates, unclear category, explicit hold/re-check/duplicate, or 3+ of 4 core fields missing). If ops prefers the stricter reading, set `MANUAL_IF_CORE_ISSUES_AT_LEAST = 2`: 65 notes go to manual review, precision stays 0.77, recall rises to 0.78. Only one note (CI-2026-0084) is fully *Ready for ops review* - the synthetic data is deliberately gap-heavy.
- **Urgency.** Starter labels give "Urgent" to 16 notes, most with no cue in the text. We only mark urgency when the note says so (intake marker, "urgent", "emergency admission"), otherwise Normal with the basis "default - no urgency cue". The 6 we mark Urgent all have a visible cue.
- **Queue mismatches** follow from the manual-review difference (manual cases go to the Manual Clarification Queue); category-to-queue mapping itself matches the supplied table.

## Behaviour worth reviewing (found while testing, now handled)
- Remark vs note conflicts: CI-2026-0002 and 0011 say "incident date missing" although a date is written -> flagged as a conflict, not "missing".
- Documents "listed as sent" and also "pending" (e.g. 0035, 0071, 0077) -> conflict flag; "(one attachment unreadable)" is not pinned on a document.
- CI-2026-0083 (submitter chose travel, text says laptop; invalid date 2026-04-31) -> category corrected, date flagged, manual queue, intended queue Asset and Device Claims.
- Shared claimant references across notes (0005/0022, 0030/0050) -> possible-duplicate flag.
- Custom notes: long forwarded email (quoted reply and signature ignored, two dates -> manual), ambiguous note (two policies, two amounts, two places -> nothing picked), very short note (Low confidence), and a note that demands approval and blames someone (neither echoed nor evaluated; tagged).

## Not measured
No time/cost benchmark against manual reading, no inter-reviewer agreement, no data beyond the synthetic pack. Next step would be a pilot on a week of real notes with reviewers marking each field right/wrong.
