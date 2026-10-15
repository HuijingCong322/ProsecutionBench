# Applicant Response — examples (gpt-5-mini, prompt applicant_response.txt b5ab5de0e7, reasoning_effort low)

Input: record up to the O1 mail date + predicted O1 state (state-tracking step); no A1 material; no prior-art full text.
Scores on the 10 gold apps: Strat macro-F1 0.52 (amendment 0.89, argument 0.95, cancellation 0.00, other 0.25);
Edit P/R/F1 0.45 / 0.10 / 0.16 (182 reference limitation units, 40 predicted); Supp 0.53 (26 of 49 cited units supported;
4 units 'insufficient_evidence'; support judged by a GPT-5-mini judge, span existence by rule; on C's 10 calibration labels the judge agrees on 6 and is
lenient in all 4 disagreements).

## Strategy
- 14838440 (good): real reply = new claims 24-25 + arguments + terminal disclaimer for the double-patenting rejection.
  The model also proposes amendment + argument + other (terminal disclaimer) — all three labels correct.
- 14239985 (miss): the real reply amends claims after an examiner interview (REM lines 5-8) and gives no arguments.
  The model proposes argument only, no amendment and no interview.
- Cancellation is never predicted where it happened (13151341, 14229448) and predicted where it did not (14420580, 14460009,
  14723918): F1 0.00.

## Edits (historical agreement, limitation units)
- 13575141 (best): the real reply rewrites several limitations of claims 1-11; all 6 predicted units match real units
  (e.g. the 'copy designation' -> 'copy destination' correction the examiner asked for).
- 14239985: real reply amends 8 claims (19 units); the model proposes no edit at all.
- 14950996 (no-edit reply): the real reply only argues; the model amends 2 claims, so the empty-set rule counts it wrong.
- Low recall is expected: a rejection can be answered by many valid amendments; Edit measures agreement with the
  applicant's actual amendment, not legal quality.

## Support (Supp)
- 14460009_u3 supported: the assertion that ratios of silicate/polymer/initiator control gel time is backed by the quoted
  specification passage (judge reason: the passage 'explicitly states that ingredients may be combined in predetermined ratios').
- 14723918_u4 not_supported: the unit argues that Young does not suggest a feature, but quotes the examiner's sentence about
  MIT; prior-art full text is not in the record, so this is not verified support.
- 13151341_u3 not_supported: the span about bottles spaced with gaps does not mention 'transverse rows', which the
  assertion relies on.
- 9 units quote passages that do not occur verbatim anywhere in the record (rule: not_supported).
