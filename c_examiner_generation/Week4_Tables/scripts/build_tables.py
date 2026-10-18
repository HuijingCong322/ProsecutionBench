#!/usr/bin/env python3
"""Build manuscript tables from saved Week 3 results. No model calls or rescoring.

Bootstrap intervals resample saved per-case numbers only. Python standard library.
Use --gpt-zip and --qwen-zip once, or rebuild from the bundled derived CSV/JSON.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
import statistics
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

SEED = 20261012
BOOTSTRAPS = 3000
MODELS = {"gpt": "GPT-5-mini", "qwen": "Qwen3.6-27B"}
DIMS = ("disposition", "grounds", "evidence", "reasoning", "overall")
NAMES = {
    "t01_pilot_summary": "Pilot results and scoring coverage",
    "t02_paired_comparison": "Comparison on the same 37 cases",
    "t03_judge_dimensions": "Where the judge scores differ",
    "t04_action_confusion": "Predicted action types versus the record",
    "t05_citation_audit": "Mechanical evidence-location audit",
    "t06_output_failures": "Output validity and failure categories",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def bootstrap(values):
    """Exact saved-run algorithm: paired case resampling, 3000 draws, fixed seed."""
    if not values:
        raise ValueError("Cannot bootstrap an empty set")
    rng = random.Random(SEED)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(BOOTSTRAPS))
    return [means[int(.025 * BOOTSTRAPS)], means[min(BOOTSTRAPS-1, int(.975 * BOOTSTRAPS))]]


def close(a, b, label):
    if not math.isclose(float(a), float(b), rel_tol=1e-11, abs_tol=1e-12):
        raise ValueError(f"Source reconciliation failed: {label}: {a} != {b}")


def archive_rows(gpt_zip, qwen_zip):
    sources = []
    with zipfile.ZipFile(gpt_zip) as gz, zipfile.ZipFile(qwen_zip) as qz:
        def load(z, prefix, relative, kind="json"):
            raw = z.read(prefix + "/" + relative)
            sources.append({"archive": Path(z.filename).name, "member": prefix+"/"+relative,
                            "sha256": digest(raw), "bytes": len(raw)})
            if kind == "bytes":
                return raw
            text = raw.decode("utf-8-sig")
            if kind == "jsonl":
                return [json.loads(line) for line in text.splitlines() if line.strip()]
            if kind == "csv":
                return list(csv.DictReader(text.splitlines()))
            return json.loads(text)

        gr, qr = "C_Examiner_Generation_Week3", "C_Qwen36_Week3"
        inputs = load(gz, gr, "inputs/generation_core.jsonl", "bytes")
        assert inputs == load(qz, qr, "inputs/generation_core.jsonl", "bytes"), "Input files differ"
        input_rows = [json.loads(s) for s in inputs.decode().splitlines() if s.strip()]
        gold_bytes = load(gz, gr, "gold/generation_targets.jsonl", "bytes")
        assert gold_bytes == load(qz, qr, "gold/generation_targets.jsonl", "bytes"), "Targets differ"
        gold = {r["sample_id"]: r for r in map(json.loads, gold_bytes.decode().splitlines())}
        gp = load(gz, gr, "outputs/C/examiner_generation_core_state_with_history.jsonl", "jsonl")
        qp = load(qz, qr, "outputs/C/examiner_generation_core_state_with_history.jsonl", "jsonl")
        gj = load(gz, gr, "outputs/C/judge_core_state_with_history.jsonl", "jsonl")
        qj = load(qz, qr, "outputs/C/judge_core_state_with_history.jsonl", "jsonl")
        gs = load(gz, gr, "metrics/C/generation_scores_core_state_with_history.csv", "csv")
        qs = load(qz, qr, "metrics/C/qwen_generation_scores_core.csv", "csv")
        gm = load(gz, gr, "metrics/C/generation_metrics_core_state_with_history.json")
        qm = load(qz, qr, "metrics/C/qwen_generation_metrics_core.json")
        gf = load(gz, gr, "config/frozen_protocol.json")
        qf = load(qz, qr, "config/frozen_protocol.json")
        for rel in ("prompts/examiner_generation.txt", "prompts/generation_judge.txt"):
            assert load(gz, gr, rel, "bytes") == load(qz, qr, rel, "bytes"), "Prompt files differ"
        assert gf["generation_prompt_hash"] == qf["generation_prompt_hash"]
        assert gf["judge_prompt_hash"] == qf["judge_prompt_hash"]
        assert digest(gz.read(gr+"/outputs/C/examiner_generation_core_state_with_history.jsonl")) == digest(qz.read(qr+"/baseline/gpt_generation_core.jsonl"))
        assert digest(gz.read(gr+"/outputs/C/judge_core_state_with_history.jsonl")) == digest(qz.read(qr+"/baseline/gpt_judge_core.jsonl"))

    arrays = {"gp": gp, "qp": qp, "gj": gj, "qj": qj, "gs": gs, "qs": qs}
    maps = {}
    ids = {x["sample_id"] for x in input_rows}
    assert len(input_rows) == len(ids) == 50
    for label, arr in arrays.items():
        idx = {x["sample_id"]: x for x in arr}
        assert len(idx) == len(arr) == 50, label + " contains missing or duplicate rows"
        assert set(idx) == ids, label + " sample IDs do not match"
        maps[label] = idx

    out = []
    for order, inp in enumerate(input_rows):
        sid = inp["sample_id"]
        row = {"case_order": order, "sample_id": sid, "app_id": inp["app_id"],
               "target_code": gold[sid]["target_code"], "target_doc_id": gold[sid]["target_doc_id"],
               "input_hash": inp["input_hash"]}
        for model, pkey, jkey, skey in [("gpt", "gp", "gj", "gs"), ("qwen", "qp", "qj", "qs")]:
            p, j, s = (maps[key][sid] for key in (pkey, jkey, skey))
            assert p["input_hash"] == inp["input_hash"]
            assert p["prompt_hash"] == gf["generation_prompt_hash"]
            assert s["status"] == p["status"]
            valid = p["status"] == "success"
            row[model+"_status"] = p["status"]
            row[model+"_validation_errors"] = "|".join(sorted(set(p.get("validation_errors") or [])))
            row[model+"_finish_reason"] = p.get("finish_reason") or ""
            row[model+"_prompt_hash"] = p["prompt_hash"]
            row[model+"_model_input_hash"] = p.get("model_input_hash") or ""
            row[model+"_next_action_type"] = p["parsed"]["next_action_type"] if valid else ""
            row[model+"_judge_status"] = j["status"]
            row[model+"_model"] = p.get("model") or ""
            for label, key in [("rougeL", "rougeL_full" if model == "gpt" else "qwen_rougeL"),
                               ("meteor", "meteor_full" if model == "gpt" else "qwen_meteor")]:
                row[model+"_"+label] = float(s[key]) if s.get(key) else ""
            if valid:
                assert j["status"] == "success"
                assert j["candidate_request_hash"] == p["request_hash"]
                assert j["prompt_hash"] == gf["judge_prompt_hash"]
                assert j["model"] == "gpt-5-mini-2025-08-07"
                for dim in DIMS:
                    score = j["parsed"][dim]
                    assert isinstance(score, int) and 1 <= score <= 5
                    row[model+"_judge_"+dim] = score
                close(s["judge_overall" if model == "gpt" else "qwen_judge"], row[model+"_judge_overall"], sid+" judge")
                a = p["citation_audit"]
                row[model+"_quoted_units"] = a["quoted_units"]
                row[model+"_matched_units"] = a["span_found_in_named_doc"]
                row[model+"_audit_flags"] = "|".join(a["flags"])
                assert 0 <= a["span_found_in_named_doc"] <= a["quoted_units"]
            else:
                for dim in DIMS:
                    row[model+"_judge_"+dim] = ""
                for key in ("quoted_units", "matched_units", "audit_flags"):
                    row[model+"_"+key] = ""
            if model == "gpt":
                row["copy_O1_rougeL"] = float(s["G0_rougeL_full"])
                row["copy_O1_meteor"] = float(s["G0_meteor_full"])
            elif maps["gp"][sid]["status"] == "success":
                close(s["gpt_rougeL"], maps["gs"][sid]["rougeL_full"], sid+" duplicated GPT R-L")
                close(s["gpt_meteor"], maps["gs"][sid]["meteor_full"], sid+" duplicated GPT METEOR")
        row["paired_valid"] = int(row["gpt_status"] == row["qwen_status"] == "success")
        if row["paired_valid"]:
            assert row["gpt_model_input_hash"] == row["qwen_model_input_hash"]
        out.append(row)

    meta = {"dataset": "data_v1 v1.2", "cohort": "gen_core", "eligible_n": 50,
            "inputs_and_gold_identical_bytes": True, "both_prompts_identical_bytes": True,
            "generation_prompt_hash": gf["generation_prompt_hash"], "judge_prompt_hash": gf["judge_prompt_hash"],
            "settings": {"GPT-5-mini": {"model": gf["settings"]["model"], "reasoning_effort": "low", "output_tokens": "8192; one length retry at 16384", "temperature": "not set"},
                         "Qwen3.6-27B": {"model": qf["generator_actual_model"], "catalog_version": "4", "precision_variant": "non-FP8", "thinking_sampling": "provider defaults", "output_tokens": "8192; one length retry at 16384"},
                         "judge": "gpt-5-mini-2025-08-07; low; same frozen rubric for both generators", "state": "fixed GPT-derived A1 state for both generators"},
            "archive_sha256": {Path(gpt_zip).name: digest(Path(gpt_zip).read_bytes()), Path(qwen_zip).name: digest(Path(qwen_zip).read_bytes())},
            "source_files": sources,
            "original_metrics": {"gpt": {k: gm[k] for k in ("full_text_primary", "G0_copy_O1", "substantive_diagnostic")},
                                 "qwen": {k: qm[k] for k in ("full_text_primary", "paired_comparison", "status_counts")}},
            "postprocessing": {"model_calls": 0, "text_metric_rescoring": False, "bootstrap_seed": SEED, "bootstrap_resamples": BOOTSTRAPS,
                               "analysis": "Means, counts, and paired case-bootstrap intervals from saved scores only"}}
    return out, meta


def number(row, key):
    return float(row[key])


def valid(rows, model):
    return [r for r in rows if r[model+"_status"] == "success"]


def average(rows, key):
    return statistics.mean(number(r, key) for r in rows)


def tex_escape(s):
    return str(s).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def table(root, name, align, headers, body, caption, note):
    lines = [r"% Generated from saved Week 3 outputs; no model calls.",
             r"\begin{table*}[t]", r"\centering", r"\small", r"\setlength{\tabcolsep}{6pt}",
             r"\renewcommand{\arraystretch}{1.14}", r"\begin{tabular}{"+align+"}", r"\toprule",
             " & ".join(headers)+r" \\", r"\midrule"]
    for row in body:
        lines.append(r"\midrule" if row is None else " & ".join(row)+r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\caption{"+caption+"}",
              r"\label{tab:cgen-"+name.split("_", 1)[0]+"}", r"\vspace{2pt}",
              r"\begin{minipage}{\textwidth}", r"\footnotesize "+note,
              r"\end{minipage}", r"\end{table*}", ""]
    (root/"tables"/(name+".tex")).write_text("\n".join(lines), encoding="utf-8")


def signed(x, digits=4):
    return f"{x:+.{digits}f}"


def ci_text(mean, ci, digits=4):
    return "$"+signed(mean, digits)+r"\;["+f"{ci[0]:.{digits}f}, {ci[1]:.{digits}f}"+"]$"


def build(root, rows, meta):
    for d in ("tables", "csv", "data", "previews"):
        (root/d).mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: int(r["case_order"]))
    assert len(rows) == len({r["sample_id"] for r in rows}) == 50
    assert len({r["app_id"] for r in rows}) == 50, "Bootstrap unit is application"
    paired = [r for r in rows if int(r["paired_valid"])]
    assert len(paired) == 37
    for model in MODELS:
        vr = valid(rows, model)
        for metric, key in [("R-L", "rougeL"), ("MET.", "meteor"), ("Judge", "judge_overall")]:
            original = meta["original_metrics"][model]["full_text_primary"][metric]
            close(average(vr, model+"_"+key), original["value"], model+" "+metric)
            assert len(vr) == original["scored_n"]
    check = {"eligible_n": 50, "common_scored_n": len(paired), "source_means_reconciled": True,
             "sample_ids_unique": True, "one_application_per_case": True,
             "no_model_calls": True, "no_text_metric_rescoring": True,
             "all_case_tables_n": 50, "paired_diagnostic_tables_n": 37,
             "same_input_prompt_target_checks": "passed at extraction; SHA-256 values in source_manifest.json"}

    # 1. Preserve reported per-model coverage; these rows use different subsets.
    summary, body = [], []
    for model, label in [("copy", "Copy O1"), *MODELS.items()]:
        vr = rows if model == "copy" else valid(rows, model)
        prefix = "copy_O1" if model == "copy" else model
        rl, met = average(vr, prefix+"_rougeL"), average(vr, prefix+"_meteor")
        judge = "" if model == "copy" else average(vr, model+"_judge_overall")
        summary.append({"system": label, "eligible_n": 50, "scored_n": len(vr), "scored_pct": 100*len(vr)/50,
                        "rougeL_full": rl, "meteor_full": met, "judge_overall": judge})
        body.append([label, f"{len(vr)}/50", f"{rl:.3f}", f"{met:.3f}", "n/a" if judge == "" else f"{judge:.2f}"])
    write_csv(root/"csv/t01_pilot_summary.csv", summary)
    table(root, "t01_pilot_summary", "lrrrr", ["System", "Scored", "ROUGE-L", "METEOR", "Judge"], body,
          "Examiner generation on the fixed 50-case pilot. Scores use the full historical next communication as reference.",
          "Means are conditional on successful scoring; failed cases are reported, not assigned zero. The model rows cover different subsets. Copy O1 is the existing baseline that returns the previous action; it was not judge-scored. Text overlap is on a 0--1 scale and judge scores are on a 1--5 scale. Higher overlap does not establish substantive correctness.")

    # 2. Same-case comparison and existing Copy-O1 baseline, with paired intervals.
    comparisons, body = [], []
    for label, key, old_key in [("ROUGE-L", "rougeL", "R-L"), ("METEOR", "meteor", "MET."), ("Overall judge", "judge_overall", "Judge")]:
        g, q = average(paired, "gpt_"+key), average(paired, "qwen_"+key)
        diff = [number(r, "qwen_"+key)-number(r, "gpt_"+key) for r in paired]
        delta, interval = statistics.mean(diff), bootstrap(diff)
        old = meta["original_metrics"]["qwen"]["paired_comparison"][old_key]
        assert [r["sample_id"] for r in paired] == old["paired_sample_ids"]
        close(delta, old["value"], "paired "+label)
        for a, b in zip(interval, old["bootstrap_95_ci"]):
            close(a, b, "paired CI "+label)
        copy = "" if key == "judge_overall" else average(paired, "copy_O1_"+key)
        comparisons.append({"metric": label, "paired_n": 37, "copy_O1": copy, "gpt_mean": g, "qwen_mean": q,
                            "qwen_minus_gpt": delta, "ci95_low": interval[0], "ci95_high": interval[1]})
        digs = 2 if key == "judge_overall" else 3
        body.append([label, "n/a" if copy == "" else f"{copy:.3f}", f"{g:.{digs}f}", f"{q:.{digs}f}", ci_text(delta, interval, 3)])
    write_csv(root/"csv/t02_paired_comparison.csv", comparisons)
    table(root, "t02_paired_comparison", "lrrrr", ["Metric", "Copy O1", "GPT-5-mini", "Qwen3.6-27B", r"$\Delta$ [95\% CI]"], body,
          "Matched comparison on the 37 cases successfully scored for both generators. All entries in a row use the same cases.",
          r"$\Delta$ is Qwen minus GPT. Intervals resample paired cases (3,000 draws; seed 20261012). They are conditional on joint success and are not adjusted for multiple comparisons. Both generators receive the same GPT-derived state; their reasoning and sampling settings differ. Both are scored by the same GPT-5-mini judge. Copy O1 has no judge score.")

    # 3. Judge's holistic score is independent, not the mean of dimensions.
    dimensions, body = [], []
    for dim, label in [("disposition", "Disposition / finality"), ("grounds", "Grounds and claims"),
                       ("evidence", "Evidence support"), ("reasoning", "Response reasoning"), ("overall", "Overall (holistic)")]:
        vals = [number(r, "qwen_judge_"+dim)-number(r, "gpt_judge_"+dim) for r in paired]
        g, q = average(paired, "gpt_judge_"+dim), average(paired, "qwen_judge_"+dim)
        delta, interval = statistics.mean(vals), bootstrap(vals)
        dimensions.append({"dimension": dim, "paired_n": 37, "gpt_mean": g, "qwen_mean": q, "qwen_minus_gpt": delta,
                           "ci95_low": interval[0], "ci95_high": interval[1]})
        if dim == "overall":
            body.append(None)
        body.append([label, f"{g:.2f}", f"{q:.2f}", ci_text(delta, interval, 2)])
    write_csv(root/"csv/t03_judge_dimensions.csv", dimensions)
    table(root, "t03_judge_dimensions", "lrrr", ["Judge dimension", "GPT-5-mini", "Qwen3.6-27B", r"$\Delta$ [95\% CI]"], body,
          "Judge dimensions on the same 37 jointly scored cases. Each dimension uses a 1--5 scale, with higher scores better.",
          r"All scores are automatically assigned by the same GPT-5-mini judge. Overall is a separate holistic judgment, not the arithmetic mean of the other dimensions. All 37 evidence scores are assessable for both models. $\Delta$ is Qwen minus GPT; intervals use 3,000 paired case-bootstrap draws (seed 20261012), without multiple-comparison adjustment. Possible judge preference for GPT remains uncontrolled.")

    # 4. Compare structured codes only; do not equate a code with claim allowance.
    confusion, body, accuracies = [], [], {}
    for model, label in MODELS.items():
        if model == "qwen":
            body.append(None)
        for truth in ["CTNF", "CTFR"]:
            group = [r for r in paired if r["target_code"] == truth]
            counts = Counter(r[model+"_next_action_type"] for r in group)
            assert set(counts) <= {"CTNF", "CTFR", "NOA"}
            item = {"model": label, "reference_code": truth, "reference_n": len(group),
                    "pred_CTNF": counts["CTNF"], "pred_CTFR": counts["CTFR"], "pred_NOA": counts["NOA"]}
            confusion.append(item)
            body.append([label, truth, str(counts["CTNF"]), str(counts["CTFR"]), str(counts["NOA"]), str(len(group))])
        correct = sum(r[model+"_next_action_type"] == r["target_code"] for r in paired)
        accuracies[label] = {"correct_n": correct, "n": 37, "accuracy": correct/37}
    write_csv(root/"csv/t04_action_confusion.csv", confusion)
    table(root, "t04_action_confusion", "llrrrr", ["Generator", "Actual", r"Pred.\ CTNF", r"Pred.\ CTFR", r"Pred.\ NOA", "Total"], body,
          "Action-code confusion counts on the 37 jointly scored cases. The reference contains 4 CTNF and 33 CTFR communications, with no NOA.",
          "CTNF denotes non-final action, CTFR final action, and NOA notice of allowance. Exact code agreement is 6/37 (16.2\\%) for GPT and 19/37 (51.4\\%) for Qwen. Counts use the structured next\\_action\\_type field, not a manual reading of the prose. A communication code does not establish whether individual claims are allowed or substantive rejections remain. This is an error diagnostic, not a class-balanced comparison.")

    # 5. Existing audit lowercases and token-normalizes; it is not literal matching.
    audits, stats = [], {}
    for model in MODELS:
        total = sum(int(r[model+"_quoted_units"]) for r in paired)
        found = sum(int(r[model+"_matched_units"]) for r in paired)
        flagged = sum(bool(r[model+"_audit_flags"]) for r in paired)
        noquote = sum(int(r[model+"_quoted_units"]) == 0 for r in paired)
        audits.append({"model": MODELS[model], "paired_n": 37, "quoted_units": total, "matched_units": found,
                       "unmatched_units": total-found, "pooled_match_rate": found/total,
                       "flagged_cases": flagged, "flagged_case_rate": flagged/37, "zero_quote_cases": noquote})
        stats[model] = (total, found, flagged)
    write_csv(root/"csv/t05_citation_audit.csv", audits)
    gt, gf, gflag = stats["gpt"]; qt, qf, qflag = stats["qwen"]
    body = [["Supplied evidence spans", str(gt), str(qt)],
            ["Located in named input", f"{gf}/{gt} ({100*gf/gt:.1f}\\%)", f"{qf}/{qt} ({100*qf/qt:.1f}\\%)"],
            ["Unmatched spans", str(gt-gf), str(qt-qf)],
            ["Cases with audit flags", f"{gflag}/37 ({100*gflag/37:.1f}\\%)", f"{qflag}/37 ({100*qflag/37:.1f}\\%)"]]
    table(root, "t05_citation_audit", "lrr", ["Mechanical audit", "GPT-5-mini", "Qwen3.6-27B"], body,
          "Citation-location checks on the same 37 cases. Span rates pool all supplied evidence units; case rates use 37 as denominator.",
          "The existing audit lowercases text and extracts ASCII alphanumeric tokens before searching for contiguous spans of at least three tokens in the named input document. Thus located spans are token-normalized matches, not verified literal quotations. Counts include claim-ground evidence and applicant-argument support spans; duplicate spans are not deduplicated. Location does not establish that evidence supports an argument. The models supply different numbers of spans, so this is not a recall measure or proof of overall evidence quality.")

    # 6. Strict recorded statuses retained, including substantive-looking taxonomy errors.
    categories = [
        ("Attempted", lambda r, m: True, "cohort"),
        ("Successfully scored", lambda r, m: r[m+"_status"] == "success", "status"),
        ("Invalid output", lambda r, m: r[m+"_status"] == "invalid_output", "status"),
        ("API failure", lambda r, m: r[m+"_status"] == "api_failed", "status"),
        ("Invalid ground only", lambda r, m: r[m+"_status"] == "invalid_output" and r[m+"_validation_errors"] == "invalid_ground", "schema_detail"),
        ("Invalid ground status only", lambda r, m: r[m+"_status"] == "invalid_output" and r[m+"_validation_errors"] == "invalid_ground_status", "schema_detail"),
        ("Both schema errors", lambda r, m: r[m+"_status"] == "invalid_output" and r[m+"_validation_errors"] == "invalid_ground|invalid_ground_status", "schema_detail"),
    ]
    failures, body = [], []
    for label, predicate, group in categories:
        counts = {m: sum(predicate(r, m) for r in rows) for m in MODELS}
        failures.append({"category": label, "group": group, "eligible_n": 50, "gpt_n": counts["gpt"], "qwen_n": counts["qwen"]})
        if label == "Invalid ground only":
            body.append(None)
        body.append([label, str(counts["gpt"]), str(counts["qwen"])])
    write_csv(root/"csv/t06_output_failures.csv", failures)
    table(root, "t06_output_failures", "lrr", ["Recorded category", "GPT-5-mini", "Qwen3.6-27B"], body,
          "Recorded output status for all 50 attempted cases. Successful scoring coverage is 78\\% for GPT and 88\\% for Qwen.",
          "The last three rows are a mutually exclusive breakdown of invalid output, not additional failures. Errors use the frozen schema: an invalid ground or status is an unaccepted output label, not necessarily an incorrect legal conclusion. Recorded statuses are retained for all attempted cases. Failed cases are not assigned zero scores.")

    write_json(root/"data/verification.json", {**check, "paired_original_intervals_reconciled": True, "action_code_accuracy": accuracies})
    write_json(root/"data/analysis_summary.json", {"pilot_summary": summary, "paired_comparison": comparisons,
               "judge_dimensions": dimensions, "action_confusion": confusion, "action_code_accuracy": accuracies,
               "citation_audit": audits, "output_failures": failures})

    # All float environments and paths compile in both one- and two-column articles.
    inputs = "\n".join(r"\input{C_Week4_Tables/tables/"+name+"}" for name in NAMES)
    (root/"all_tables.tex").write_text("% Requires \\usepackage{booktabs}; input from the paper root.\n"+inputs+"\n", encoding="utf-8")
    preamble = r"""\documentclass[10pt]{article}
\usepackage[paperwidth=190mm,paperheight=145mm,margin=12mm]{geometry}
\usepackage{booktabs}
\usepackage[T1]{fontenc}
\usepackage{mathptmx}
\usepackage{caption}
\captionsetup{font=small,labelfont=bf}
\pagestyle{empty}
\begin{document}
"""
    preview = preamble + "\n".join(r"\input{tables/"+name+"}\n"+r"\clearpage" for name in NAMES) + "\n\\end{document}\n"
    (root/"tables_preview.tex").write_text(preview, encoding="utf-8")
    (root/"paper_results_paragraph.tex").write_text(r"""% Optional text. These comparisons are conditional on successful output.
On the 37 cases scored for both generators, GPT-5-mini has higher ROUGE-L and METEOR, while Qwen3.6-27B receives a higher overall judge score (Table~\ref{tab:cgen-t02}). The judge breakdown shows that Qwen's advantage is concentrated in disposition and finality; its grounds, evidence, and reasoning scores are lower (Table~\ref{tab:cgen-t03}). GPT predicts a non-final action on 35 of these cases, although only four reference communications are coded non-final (Table~\ref{tab:cgen-t04}). The disagreement between text-overlap measures and the judge therefore warrants reporting both, rather than treating either as a complete measure of generation quality. These pilot comparisons use fixed GPT-derived states and a shared GPT-5-mini judge, with different generator reasoning settings and incomplete output coverage.
""", encoding="utf-8")

    markdown_tables = []
    for name in NAMES:
        markdown_tables.append(f"### {name}: {NAMES[name]}\n\n[LaTeX](tables/{name}.tex) | [CSV](csv/{name}.csv)\n\n![{NAMES[name]}](previews/{name}.png)\n")
    readme = f"""# C examiner generation: additional tables from Week 3

This package reformats the existing GPT-5-mini and Qwen3.6-27B results. It contains **no new model runs, no new examples, and no text-metric rescoring**. Means, counts, and bootstrap intervals are calculated from the saved records. Original predictions, prompts, labels, and statuses are unchanged.

## Main findings

- Both generators attempted the same 50 cases. GPT has 39 scored outputs (78%); Qwen has 44 (88%). Their jointly scored subset contains 37 cases.
- On those 37 cases, GPT has higher ROUGE-L (0.168 vs 0.145) and METEOR (0.218 vs 0.111), while Qwen has a higher overall judge score (2.68 vs 2.08).
- The judge scores Qwen higher on disposition/finality, but lower on grounds, evidence, and response reasoning. The overall score is a separate holistic judgment.
- GPT predicts CTNF on 35/37 matched cases, compared with 9/37 for Qwen and 4/37 in the record. Qwen also predicts nine NOAs although the matched reference has no NOA. These are communication codes, not claim-level allowance labels.
- The existing citation audit locates 167/300 GPT spans and 129/167 Qwen spans after token normalization. These counts do not measure whether an argument is supported.

## Which tables to use

| Table | Purpose | Suggested location |
|---|---|---|
| 01 | Original pilot means, coverage, and existing Copy-O1 baseline | Appendix; omit if Table 3 already covers it |
| 02 | Same-case comparison and paired intervals | Main results |
| 03 | Judge dimension breakdown | Main results or error analysis |
| 04 | Action-code confusion counts | Error analysis |
| 05 | Mechanical evidence-location diagnostic | Appendix |
| 06 | Output failures and schema categories | Appendix |

All six are supplied for selection. They need not all go into the paper.

## Read the denominators correctly

Table 01 preserves the original per-model valid subsets (39 and 44). Tables 02-05 use **exactly the same 37 cases** for both generators. Table 06 uses all 50 attempted cases. Failures are not scored as zero. The 37-case comparison is conditional on joint success and does not establish unconditional quality across the full cohort. There is one application per case.

The full-text metrics compare generated prose with the full historical O2. Copy O1 was already evaluated in Week 3 and is recomputed here only by averaging its saved per-case scores. Its large overlap does not establish that repeating an old action is substantively sound, and no saved judge score exists for that baseline. Substantive-reference metrics are not substituted for full-text scores.

## Protocol and limits

- Data: data_v1 v1.2, fixed `gen_core` cohort, 50 applications. No dev examples are included.
- GPT generator: `gpt-5-mini-2025-08-07`, reasoning `low`, no temperature; 8,192 output-token cap with one 16,384 length retry.
- Qwen generator: `qwen--qwen3.6-27b`, catalog version 4, non-FP8, provider-default thinking/sampling; same output caps. Provider defaults are not equivalent to GPT low reasoning.
- Both use the same fixed GPT-derived A1 state and cutoff-visible inputs. Input and gold files are byte-identical, as are the two prompt files. Model input hashes also match for the common successful cases.
- Judge: the same `gpt-5-mini-2025-08-07` and frozen rubric for both models. Scores are automatic judgments, with possible model preference and limited review. A's separate 10-item support-label calibration is not calibration of these generation scores.
- Overall is not an average of the judge dimensions. All matched evidence dimensions have numeric scores; none is imputed.
- Action counts read the structured `next_action_type` field. CTNF = non-final action, CTFR = final action, NOA = notice of allowance. These labels alone do not establish claim-level allowance or substantive rejection.
- Citation matches use the original audit's lowercasing and ASCII alphanumeric token normalization. They are **not literal-quotation verification, support judgments, or citation recall**. Repeated spans remain repeated units.
- Paired intervals use 3,000 case-bootstrap draws, seed 20261012. Table 02 reproduces the saved Week 3 intervals exactly. Table 03 applies the same postprocessing to the saved dimension scores. These are descriptive pilot intervals, conditional on the observed subset, without multiple-comparison adjustment.
- No cost or latency comparison is made: Qwen GPU-time billing and GPT token billing are not comparable from these files alone.

## Files

- `tables/`: six editable LaTeX `table*` fragments. Only `booktabs` is required.
- `csv/`: one numeric CSV per table, without rounded source values.
- `data/cases.csv`: compact, 50-row derived source table, including status, hashes, saved scores, structured action types, and citation counts. No patent document text, credentials, or endpoint URLs are copied.
- `data/source_manifest.json`: archive/member SHA-256 hashes, original metric summaries, settings, and postprocessing specification.
- `data/verification.json`: reconciliation checks and code agreement.
- `data/analysis_summary.json`: full-precision aggregated values.
- `previews/`: six PNG previews generated from the LaTeX PDF.
- `tables_preview.pdf`: readable preview of the exact LaTeX tables, one per page.
- `tables_preview.tex`: standalone preview source.
- `all_tables.tex`: optional include file for all six tables.
- `paper_results_paragraph.tex`: optional short results paragraph for adaptation.
- `scripts/build_tables.py`: standard-library-only table builder. It imports no model SDK and makes no network calls.
- `UPLOAD_GUIDE_CN.md`: GitHub and Overleaf instructions.

## Rebuild without original archives

From this directory:

```bash
python scripts/build_tables.py
```

This reads the bundled derived CSV and source manifest and regenerates the six LaTeX/CSV tables. It does not run experiments or recalculate ROUGE/METEOR from text.

If `pdflatex` and `pdftoppm` are installed:

```bash
python scripts/build_tables.py --compile-preview
```

To derive the same source rows directly from the original submission archives:

```bash
python scripts/build_tables.py \\
  --gpt-zip /path/to/C_gpt5mini_Week3_Submission.zip \\
  --qwen-zip /path/to/C_Qwen36_Week3_Submission.zip \\
  --compile-preview
```

The archive route checks IDs, input/prompt equality, paired input hashes, judge-to-candidate linkage, original metric means, duplicated GPT baseline scores, and the saved paired intervals. The bundled data route preserves the resulting checks and rechecks aggregate consistency.

## Overleaf

Upload this directory as `C_Week4_Tables/` at the paper root. Add `\\usepackage{{booktabs}}` to the preamble if needed. At the desired point in the results section:

```latex
\\input{{C_Week4_Tables/tables/t02_paired_comparison}}
\\input{{C_Week4_Tables/tables/t03_judge_dimensions}}
\\input{{C_Week4_Tables/tables/t04_action_confusion}}
```

The fragments use `table*` for a two-column paper. Floats may move to the next page; do not put them inside another `table` environment. Table labels are `tab:cgen-t01` through `tab:cgen-t06`. Each table can be included independently. To include all six, use `\\input{{C_Week4_Tables/all_tables}}` instead of the individual inputs. Renumbering is automatic. Do not manually name them Table 4/5/6.

## Preview

""" + "\n".join(markdown_tables)
    (root/"README.md").write_text(readme, encoding="utf-8")
    guide = """# C 部分表格：上传与使用

## 你现在要做什么

1. 先打开 `tables_preview.pdf`，阅读六张表。全部来自上周已有结果，不需要运行 Colab、不需要 API key，也不产生新的模型费用。
2. GitHub 建议完整保留本文件夹，放在项目现有 C 目录下。这样组员能看到表格、原始分母、CSV 和生成依据。
3. Overleaf 只需要 `tables/` 中想使用的 `.tex` 文件。建议正文先看 02、03、04；01 与已有 Table 3 重复时可以不放，05、06 可放附录。

## 六张表看什么

| 文件前缀 | 内容 | 主要用途 |
|---|---|---|
| t01 | GPT、Qwen、已有 Copy-O1 的总分与覆盖率 | 保留上周正式口径，避免隐藏失败 |
| t02 | 同一 37 件上的模型比较与配对区间 | 比直接比较 39 件和 44 件的均值更清楚 |
| t03 | disposition、grounds、evidence、reasoning、overall | 解释 Qwen 总 judge 分更高，但各维度并非都更高 |
| t04 | 真实动作类型与预测动作类型的混淆 | 展示 GPT 偏向 non-final；Qwen 也有与记录不符的 NOA 类型预测 |
| t05 | 已保存的引文机械定位检查 | 展示引用片段能否在所指输入文件中定位 |
| t06 | 50 件中的成功、schema 失败、API 失败 | 解释 39/50 和 44/50 的来源 |

01 使用各自可评分样本：GPT 39、Qwen 44、Copy-O1 50。02 至 05 统一使用共同可评分的 37 件。06 使用全部 50 件。37 件的均值与上周 39/44 件的均值不同是正常的，不要覆盖 D 已汇总的 Table 3。

## GitHub 网页上传

1. 下载并解压本 ZIP。
2. 进入共享 repo，再进入你们现有的 C 目录。
3. 点击 `Add file` → `Upload files`。
4. 将解压后的 `C_Week4_Tables` 整个文件夹拖入上传区域。上传后的结构应为 `你们的C目录/C_Week4_Tables/README.md`，并包含 `tables/`、`csv/`、`data/`、`previews/` 和 `scripts/`。
5. 检查预览中有 `.tex` 和 `.csv` 等实际文件，不要只上传 ZIP。
6. commit message 可写：`Add examiner generation analysis tables from existing pilot outputs`。
7. 打开新文件夹的 README，确认六张 PNG 预览能够显示。

GitHub 不需要再次上传原来的两个大成果 ZIP，也不需要再次上传专利输入、缓存和 notebook。这里的生成脚本只处理保存结果，体积很小；建议保留用于解释表格来源，不需要你手动运行。

## Overleaf 上传

1. 在现有 paper 项目根目录创建 `C_Week4_Tables` 文件夹。
2. 在其中创建 `tables` 子文件夹，将这次六个 `.tex` 文件上传进去。保留文件名。
3. 在 `main.tex` 的导言区，也就是 `\\begin{document}` 之前，确认有：

```latex
\\usepackage{booktabs}
```

已有这行就不要重复添加。

4. 在 Results 或 Error Analysis 中需要表格的地方加入：

```latex
\\input{C_Week4_Tables/tables/t02_paired_comparison}
\\input{C_Week4_Tables/tables/t03_judge_dimensions}
\\input{C_Week4_Tables/tables/t04_action_confusion}
```

5. 若需要附录，再在附录加入 05 和 06，必要时也加入 01。不要把 `\\input` 放进另一个 `table` 环境。
6. 点击 Recompile。这里使用 `table*`，适合 ACL 等双栏论文跨两栏显示，表格出现在后续页顶属于 LaTeX 的正常浮动行为。
7. 表格编号由论文自动生成。使用 `\\ref{tab:cgen-t02}` 等引用，不要写死编号。六张表可以分别独立插入。

如果只想先独立看编译效果，可新建空白 Overleaf 项目，上传本文件夹的全部内容，将 `tables_preview.tex` 设为 Main document，然后编译。现有 paper 不要把这个预览文件设为主文档。

## 和组员对接时说明

这些是上周 GPT/Qwen 结果的补充表，没有重跑实验。原 Table 3 保持各自 39/44 件的口径；新的同案分析用共同成功的 37 件。建议 D 先选 02、03、04 看哪几张适合正文，其余可以放附录。表中 judge 是原有自动评分，引文定位也不是人工支持性验证。
"""
    (root/"UPLOAD_GUIDE_CN.md").write_text(guide, encoding="utf-8")
    return {"eligible_n": len(rows), "paired_n": len(paired), "tables": len(NAMES), "paired_differences": comparisons}


def compile_preview(root):
    if not shutil.which("pdflatex") or not shutil.which("pdftoppm"):
        raise RuntimeError("PDF/PNG preview needs pdflatex and pdftoppm; LaTeX/CSV output already exists")
    for _ in range(2):
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "tables_preview.tex"], cwd=root, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(proc.stdout[-6000:])
    log = (root/"tables_preview.log").read_text(errors="replace")
    if "Overfull" in log or "undefined references" in log:
        raise RuntimeError("Preview has overflow or unresolved references; inspect tables_preview.log")
    for i, name in enumerate(NAMES, 1):
        subprocess.run(["pdftoppm", "-f", str(i), "-l", str(i), "-scale-to", "1500", "-png", "-singlefile", str(root/"tables_preview.pdf"), str(root/"previews"/name)], check=True, capture_output=True)
    for ext in ("aux", "log", "out"):
        (root/("tables_preview."+ext)).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpt-zip", type=Path)
    parser.add_argument("--qwen-zip", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--compile-preview", action="store_true")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if bool(args.gpt_zip) != bool(args.qwen_zip):
        parser.error("Supply both original archives, or neither")
    if args.gpt_zip:
        rows, meta = archive_rows(args.gpt_zip, args.qwen_zip)
        write_csv(root/"data/cases.csv", rows)
        write_json(root/"data/source_manifest.json", meta)
    else:
        rows = read_csv(root/"data/cases.csv")
        meta = json.loads((root/"data/source_manifest.json").read_text())
    summary = build(root, rows, meta)
    if args.compile_preview:
        compile_preview(root)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
