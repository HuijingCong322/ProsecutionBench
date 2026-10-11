"""Merge everyone's results into the Table 3 pilot (D's integration job).

Each member drops ONE csv in results/submissions/ named <owner>_metrics.csv (A_metrics.csv, B_metrics.csv,
C_metrics.csv), using results/metrics_submission_template.csv. D's trajectory numbers are read automatically from
metrics/D/trajectory_metrics.json.

Usage: python build_table3.py --root path/to/D_trajectory
Writes results/table3_pilot.csv (long), .json, .tex (wide, one row per model), results/task_status.csv,
and results/merge_problems.txt. Missing cells are N/A, never 0.00.
"""
import argparse, glob, json, os
import pandas as pd

COLUMNS = [  # (Table 3 column, owner, category, metric definition fixed in the week plan, section 13)
    ("Occ.", "B", "Examiner Prediction", "AUROC of next-OA occurrence probability"),
    ("Type", "B", "Examiner Prediction", "macro-F1 over CTNF/CTFR/NOA"),
    ("Grnd.", "B", "Examiner Prediction", "micro-F1 of verifiable claim-ground pairs (NOA = empty set)"),
    ("R-L", "C", "Examiner Generation", "ROUGE-L of generated OA vs actual O2, per-case mean"),
    ("MET.", "C", "Examiner Generation", "METEOR of generated OA vs actual O2, per-case mean"),
    ("Judge", "C", "Examiner Generation", "fixed GPT-5-mini judge, overall score mean, 1-5"),
    ("Strat.", "A", "Applicant Response", "multi-label macro-F1 over fixed strategy labels"),
    ("Edit", "A", "Applicant Response", "micro-F1 of frozen limitation edit units"),
    ("Supp.", "A", "Applicant Response", "supported / verifiable argument units; GPT-5-mini judge with a fixed rubric, calibrated on 10 student-labelled units (not expert validation)"),
    ("C-idx", "D", "Trajectory Forecasting", "IPCW concordance, first NOA or abandonment, tau = 24 months"),
    ("IBS", "D", "Trajectory Forecasting", "integrated Brier score, monthly grid to 24 months (lower is better)"),
    ("Claim", "A", "State Tracking", "share of verifiable claim records with matching ID, version, text, status"),
    ("Rej.", "A", "State Tracking", "macro-F1 of claim-ground-status tuples"),
    ("dOcc.", "B", "Personalized Modeling", "profile AUROC - no-profile AUROC, same paired subset"),
    ("dR-L", "B", "Personalized Modeling", "profile ROUGE-L - no-profile ROUGE-L, same paired subset"),
]
COLS = [c[0] for c in COLUMNS]
TEMPLATE_COLS = ["owner", "table3_column", "model", "input_setting", "sample_set", "value", "eligible_n", "scored_n",
                 "failed_n", "excluded_reason", "split_detail", "prompt_version", "run_id", "source_file", "notes"]
MAIN_MODEL = "gpt-5-mini"


def d_rows(root):
    p = os.path.join(root, "metrics", "D", "trajectory_metrics.json")
    if not os.path.exists(p):
        return []
    rows = []
    for r in json.load(open(p))["results"]:
        is_llm = r["method"].startswith("llm_")
        model = (r.get("model") or "") if is_llm else f"reference: {r['method']}"
        for col, key in (("C-idx", "c_index"), ("IBS", "ibs")):
            rows.append(dict(owner="D", table3_column=col, model=model, input_setting=r.get("input_setting"),
                             sample_set="test_core", value=r.get(key), eligible_n=r["eligible_n"],
                             scored_n=r["scored_n"], failed_n=r["failed_n"],
                             excluded_reason=r.get("excluded_reason", ""), split_detail="test_core 100; train <= 2013-12-31",
                             prompt_version="", run_id="", source_file="metrics/D/trajectory_metrics.json",
                             notes=r.get("note", "")))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--main-model", default="gpt-5-mini", help="model reported in task_status (normalized spelling)")
    args = ap.parse_args()
    R = args.root
    global MAIN_MODEL
    MAIN_MODEL = args.main_model.strip().lower().replace("_", "-").replace(" ", "-")
    res = os.path.join(R, "results")
    os.makedirs(os.path.join(res, "submissions"), exist_ok=True)
    problems, rows = [], d_rows(R)
    for f in sorted(glob.glob(os.path.join(res, "submissions", "*_metrics.csv"))):
        df = pd.read_csv(f, dtype=str).fillna("")
        miss = [c for c in TEMPLATE_COLS if c not in df.columns]
        if miss:
            problems.append(f"{os.path.basename(f)}: missing columns {miss}")
            continue
        for _, r in df.iterrows():
            if r.table3_column not in COLS:
                problems.append(f"{os.path.basename(f)}: unknown column '{r.table3_column}'"); continue
            owner = dict((c[0], c[1]) for c in COLUMNS)[r.table3_column]
            if r.owner != owner:
                problems.append(f"{os.path.basename(f)}: {r.table3_column} is owned by {owner}, file says {r.owner}")
            rows.append(r.to_dict())
    L = pd.DataFrame(rows, columns=TEMPLATE_COLS)
    # one spelling per model: "GPT-5-mini", "gpt_5_mini " -> "gpt-5-mini"
    norm = lambda m: m if str(m).startswith("reference") else str(m).strip().lower().replace("_", "-").replace(" ", "-")
    L["model"] = L["model"].map(norm)
    L["value"] = pd.to_numeric(L["value"], errors="coerce")
    for c in ["eligible_n", "scored_n", "failed_n"]:
        L[c] = pd.to_numeric(L[c], errors="coerce")
    # sanity checks
    for _, r in L.iterrows():
        if pd.notna(r.value):
            lo, hi = (-1, 1) if r.table3_column in ("dOcc.", "dR-L") else ((1, 5) if r.table3_column == "Judge" else (0, 1))
            if not lo <= r.value <= hi:
                problems.append(f"{r.owner} {r.table3_column} {r.model}: value {r.value} outside [{lo}, {hi}]")
        if pd.isna(r.scored_n) or pd.isna(r.eligible_n):
            problems.append(f"{r.owner} {r.table3_column} {r.model}: eligible_n / scored_n missing")
    dup = L[L.duplicated(["table3_column", "model", "input_setting", "sample_set"], keep=False)]
    for _, r in dup.iterrows():
        problems.append(f"duplicate entry: {r.table3_column} / {r.model} / {r.input_setting} / {r.sample_set}")
    L.to_csv(os.path.join(res, "table3_pilot.csv"), index=False)
    json.dump(dict(columns=[dict(column=c, owner=o, category=g, definition=d) for c, o, g, d in COLUMNS],
                   entries=json.loads(L.to_json(orient="records"))), open(os.path.join(res, "table3_pilot.json"), "w"), indent=1)

    # wide table: one row per model (main input setting = the one each owner reports for that model)
    models = [m for m in L.model.dropna().unique() if not str(m).startswith("reference")]
    models = sorted(models, key=lambda m: (m != MAIN_MODEL, m))
    refs = [m for m in L.model.dropna().unique() if str(m).startswith("reference")]

    def cell(model, col):
        x = L[(L.model == model) & (L.table3_column == col) & L.value.notna()]
        if x.empty:
            return None
        pref = x[x.input_setting.astype(str).str.contains("state")]  # prefer state-with-history if both exist
        return float((pref if len(pref) else x).value.iloc[0])

    def fmt(v):
        return r"\na" if v is None else f"{v:.2f}"
    head = " & ".join([r"\textbf{Model}"] + COLS).replace("dOcc.", r"$\Delta$Occ.").replace("dR-L", r"$\Delta$R-L").replace("IBS", r"IBS$\downarrow$")
    lines = [r"\begin{tabular}{@{}l " + "c" * len(COLS) + "@{}}", r"\toprule", head + r" \\", r"\midrule"]
    for m in models:
        lines.append(f"{m} & " + " & ".join(fmt(cell(m, c)) for c in COLS) + r" \\")
    if refs:
        lines += [r"\midrule", r"\multicolumn{%d}{@{}l}{\textit{Reference (no language model)}} \\" % (len(COLS) + 1)]
        for m in refs:
            lines.append(m.replace("reference: ", "").replace("_", r"\_") + " & " + " & ".join(fmt(cell(m, c)) for c in COLS) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(res, "table3_pilot.tex"), "w").write(
        "% Table 3 pilot, generated by build_table3.py. \\na = not run / not estimable (see task_status.csv).\n"
        "% Pilot sample: test_core 100 (gen_core 50, gold 10). Not the full benchmark.\n" + "\n".join(lines) + "\n")

    # task status: one row per column for the main model
    st = []
    for col, owner, cat, defin in COLUMNS:
        x = L[(L.table3_column == col) & (L.model == MAIN_MODEL)]
        if len(x) and x.value.notna().any():
            xv = x[x.value.notna()]
            pref = xv[xv.input_setting.astype(str).str.contains("state")]  # same rule as the .tex: main setting first
            r = (pref if len(pref) else xv).iloc[0]
            st.append(dict(column=col, owner=owner, category=cat, status="done", model=MAIN_MODEL, input_setting=r.input_setting, value=round(r.value, 4),
                           eligible_n=r.eligible_n, scored_n=r.scored_n, failed_n=r.failed_n, reason=r.notes))
        elif len(x):
            r = x.iloc[0]
            st.append(dict(column=col, owner=owner, category=cat, status="N/A", model=MAIN_MODEL, value=None,
                           eligible_n=r.eligible_n, scored_n=r.scored_n, failed_n=r.failed_n,
                           reason=r.notes or r.excluded_reason or "not estimable"))
        else:
            st.append(dict(column=col, owner=owner, category=cat, status="pending", model=MAIN_MODEL, value=None,
                           eligible_n=None, scored_n=None, failed_n=None, reason="no submission yet"))
    S = pd.DataFrame(st)
    S.to_csv(os.path.join(res, "task_status.csv"), index=False)
    open(os.path.join(res, "merge_problems.txt"), "w").write("\n".join(problems) + ("\n" if problems else "no problems found\n"))
    print(S[["column", "owner", "status", "value", "scored_n"]].to_string(index=False))
    print(f"\n{len(problems)} problem(s); see results/merge_problems.txt" if problems else "\nno merge problems")


if __name__ == "__main__":
    main()
