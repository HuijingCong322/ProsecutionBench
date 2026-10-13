# Generation cases to inspect

These are automatically selected by the frozen judge scores for error analysis, not human endorsements. Read the sources before using either as a paper example.

## Lower judge score diagnostic

- sample\_id: 14723918\_t1  
- actual O2: IWNJSWTWRXEAPX5  
- ROUGE-L: 0.0900155199172271; METEOR: 0.22837332385467635; Judge: 1  
- Judge rationale: The candidate predicted a non-final action maintaining the 102/103 rejections and inviting further amendment/argument. The actual O2 (CTFR) withdraws the rejections, states claims 1-9 are allowed and objects only claim 10 informally. This is a major contradiction in action and finality (disposition), and the candidate therefore fails to predict the observed outcome. The candidate also maintains statutory grounds (102/103) against the same claims that O2 found allowable, so the grounds are incorrect. Record citations were used but the candidate misapplied the outcome of the applicant's A1 remarks (the real examiner found the A1 persuasive and withdrew rejections), so reasoning and evidence use are unsound.  
- Mechanical flags:  
- Source material: inputs/generation\_core.jsonl and gold/generation\_targets.jsonl; candidate: outputs/C/examiner\_generation\_core\_state\_with\_history.jsonl.  
- C's checked explanation: The generated action maintains the 102/103 rejections and predicts CTNF, whereas the actual O2 is coded CTFR, withdraws the rejections, allows claims 1–9, and leaves only an informal objection to claim 10\. Although the response discusses the September 6 amendments, its claim-version references point to the earlier claim document rather than the amended listing, ISS0O53CRXEAPX3. The cited rejection passages can be located in O1, but they establish the previous examiner position rather than justify maintaining it after A1. The response largely repeats that position without adequately explaining why the applicant’s distinctions should be rejected. I agree with the low score because the main error concerns the disposition of the claims, not simply differences in wording.

&nbsp;

## Higher judge score diagnostic

- sample\_id: 13773735\_t1  
- actual O2: I0JRF7UPPXXIFW4  
- ROUGE-L: 0.21821257400620242; METEOR: 0.231658408830233; Judge: 5  
- Judge rationale: The candidate correctly predicted the examiner would maintain the §103 rejections over Walter/Hayes/Donnelly/Tonkovich, make the action final (CTFR), acknowledge the applicant's amendment/withdrawals and the correction to claim 16, and reject the applicant's traverses (batch vs continuous, single-tank/weir, hindsight) as unpersuasive. These elements match the actual O2 (CTFR dated 2014-09-26, doc\_id I0JRF7UPPXXIFW4) and are supported by the cutoff-available record (notably the examiner’s April 8, 2014 detailed rejection HTR7LS2ZPXXIFW4 and the applicant’s A1 reply HXDH5YBHPXXIFW3/HXDH5YCHPXXIFW3).  
- Mechanical flags: quote\_not\_found\_in\_named\_doc:HTR7LS2ZPXXIFW4;argument\_quote\_not\_found:HTR7LS2ZPXXIFW4;argument\_quote\_not\_found:HTR7LS2ZPXXIFW4;argument\_quote\_not\_found:HTR7LS2ZPXXIFW4  
- Source material: inputs/generation\_core.jsonl and gold/generation\_targets.jsonl; candidate: outputs/C/examiner\_generation\_core\_state\_with\_history.jsonl.  
- C's checked explanation: The generated action correctly predicts a final rejection of claims 3 and 10–16 over Walter, Hayes, Donnelly, and Tonkovich, matching the actual O2. It references the July 8 claim listing, recognizes the withdrawn claims, and acknowledges the correction to claim 16\. Its responses to the applicant’s arguments broadly match the examiner’s position, although the heading inconsistently mixes non-final and final terminology. Several citation spans are shortened paraphrases rather than exact quotations, and I could not locate the “manually pumped” passage in the named O1 document. I agree that this is a stronger prediction, but I consider 5/5 too generous given the remaining citation and procedural wording problems.

&nbsp;