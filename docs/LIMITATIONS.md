# Limitations

- **Rule-based extraction is brittle on new phrasing.** It was tuned on 6 recurring templates plus 5 free-text notes in the pack and 7 extra notes I wrote. Real inboxes will have formats it has not seen; expect to add patterns in `config.py` / `extractors.py` (the evaluation + gold tests show where it breaks).
- **Small gold set.** 16 notes were checked by hand; the other 69 are checked only by invariants (every found value appears in the note, no decision words, schema valid) and by comparison with starter labels, which are themselves unreliable.
- **Category keywords** are English and coarse. Mixed-incident notes (e.g. burnt smell from a UPS) can tie; ties are sent to manual review instead of guessed.
- **Dates:** no year inference, no relative-date resolution, and `dd/mm` vs `mm/dd` is flagged rather than resolved. Two dates in one note always need a human.
- **Locations** use labels (`Loc:`, `City:` ...) and a small city list; a street address or an unlisted town in free text may be missed (reported `missing`, never invented).
- **Document conflicts** compare document *types* (e.g. "garage estimate" vs "repair estimate" are treated as the same type), which can over-flag.
- **Urgency** only reflects explicit cues; many real urgent notes carry none, so they default to Normal (the basis says so). The starter urgency labels agree on only 56/85 notes for this reason.
- **No attachments are read.** "Photos attached" means the note says so; the tool cannot verify the files exist.
- **Not a decision tool.** It does not read policy terms, coverage, liability, fraud signals or amounts against limits. Statements about blame in a note are only tagged.
- **Cross-note checks** cover only the batch given (shared claimant reference); there is no lookup against earlier batches or a claims system.
- **LLM option** is a thin, guarded summary rewrite; its live call is untested here, and it never touches facts or flags.
- Thresholds (3 core issues, confidence cut-offs) are judgement calls - confirm them with ops before use.
