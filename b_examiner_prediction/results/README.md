# B examiner-prediction results

GPT and Qwen core100/profile14 runs are complete. Scores remain automatic-gold drafts: B's independent6-state and5-ground human reviews are pending. Occ/Type use99 cases; Grnd uses62. Qwen shares the frozen prediction prompt and GPT-derived state, but uses provider-default thinking/sampling rather than GPT low. Prediction ΔOcc is a within-model14-pair comparison.

GPT generation ΔR-L is now −0.0063364337 on6 common valid pairs out of8 fixed candidates. Full-text R-L is0.1859246914 without profile and0.1795882577 with profile. Two original C baseline schema failures are retained; no replacement or baseline rerun. All6 new profile candidates succeeded, with one truncation retry. C's exact generation base/prompt, low8192/16384 configuration and surface_format_v1 scoring policy are reused. This small partial-coverage pilot does not establish a significant or general effect. Qwen generation ΔR-L remains unrun.

Metric JSONs include coverage/confusion matrices. Generation per-case scores and provenance are in gpt5mini_generation_profile_* files. Aggregate logs/configuration are in metric_provenance.json; API keys and raw requests are not uploaded. Local traces remain with B. Binary baselines use train445/test99; raw LR-reply is separately labelled and has no Type/Grnd predictions.

B_metrics.csv is in d_trajectory/results/submissions/. C's original submission is mirrored there byte-for-byte for rebuilding.
