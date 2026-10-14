# Table3 pilot integration

Rebuild: from d_trajectory/code run `python build_table3.py --root ..` (requires pandas). Submissions A/B/C are read from results/submissions;D is read from metrics/D/trajectory_metrics.json. C_metrics.csv combines the GPT and Qwen C submissions from c_examiner_generation/gpt5mini/results/C_metrics.csv and c_examiner_generation/qwen36_27b/results/C_metrics_Qwen36_27B.csv. B_metrics.csv contains GPT and separately labelledQwen results.

Generated table3_pilot.tex uses booktabs and the `\na` macro;in Overleaf include `\usepackage{booktabs}` and define `\newcommand{\na}{N/A}` if absent. The snippet is a tabular,not a standalone document. GPT ΔR-L is −0.0063 on6/8 valid pairs;Qwen ΔR-L and its unrun A/D cells remain N/A,never zero. Wide table rounds to2 decimals;full precision and coverage in table3_pilot.csv/json.

B effectiveN: Occ/Type99,Grnd62,ΔOcc14,GPT ΔR-L6 scored of8 candidates (2 original C schema failures);Qwen ΔR-L0 scored of8 prepared. A restriction is excluded from three-class scoring;unknown ground labels and112d conflict are not treated as empty. B human6-state/5-ground reviews are pending. Generated task_status `done` means a numeric metric was submitted,not expert/human validation;read notes. A's support judge remains uncalibrated pending student labels as its submission notes state.

Qwen shares GPT-derived states/frozen prediction prompt but uses provider-default thinking/sampling rather than GPT low;this is not a same-reasoning-setting model comparison. B reference baseline Occ scores are supplementary in b_examiner_prediction/results/baseline_comparison.draft.csv,not invented Type/Grnd cells. Detailed B provenance/results: b_examiner_prediction/results/. Weekly summary onlyB sections updated;C/D authored conclusions retained.


C generation coverage: GPT 39/50; Qwen 44/50 (5 invalid outputs, 1 API failure). Means are over each model’s scored cases; paired model comparisons use 37 common valid cases. Qwen-minus-GPT differences are not the profile dR-L metric. Both generators use GPT-derived state and the fixed GPT-5-mini judge; provider settings differ. The two Qwen example explanations are record-based AI-assisted review, not expert validation.
