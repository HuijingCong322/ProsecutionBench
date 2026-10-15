"""Summary figure for A (State Tracking + Applicant Response), week-3 pilot.

Reads only committed result files (no API calls):
  state_metrics.json, response_metrics.json, README prompt-selection numbers (hard-coded below, dev+tune 12 apps).
Writes results/A_results_plot.pdf and results/A_results_plot.png.
With --model qwen: reads outputs/qwen36_27b/ and writes results/A_results_plot_qwen36_27b.pdf/.png; panel (b) then shows
usable outputs per cutoff (Qwen used the frozen p3 prompt, there was no prompt selection) and panel (c) has no test_core bars.

  python3 a_state_response/scripts/plot_results.py [--model qwen]
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

A = Path(__file__).resolve().parent.parent
OUT = A / "results"; OUT.mkdir(exist_ok=True)
_ap = argparse.ArgumentParser(); _ap.add_argument("--model", choices=["gpt", "qwen"], default="gpt")
QWEN = _ap.parse_args().model == "qwen"
SRC = A / "outputs" / "qwen36_27b" if QWEN else A
st = json.loads((SRC / "state_metrics.json").read_text())
rs = json.loads((SRC / "response_metrics.json").read_text())

BLUE, ORANGE, GREEN, PURPLE, GREY = "#3b6fd4", "#e07040", "#3aa57a", "#6a4fd0", "#9a9a9a"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titlesize": 10, "axes.titleweight": "bold",
                     "axes.titlelocation": "left", "legend.frameon": False})
fig, ax = plt.subplots(2, 2, figsize=(11, 7.6))


def label_bars(a, bars, fmt="{:.2f}"):
    for b in bars:
        a.annotate(fmt.format(b.get_height()), (b.get_x() + b.get_width() / 2, b.get_height()),
                   xytext=(0, 2), textcoords="offset points", ha="center", va="bottom", fontsize=7.5)


# (a) State tracking vs human gold, O1 and A1 cutoffs
a = ax[0, 0]
keys = [("claim_version_accuracy", "Claim\n(headline)"), ("id_found", "ID found"), ("status_acc", "Status"),
        ("version_acc", "Version"), ("text_acc", "Text"), ("rejection_status_macro_f1", "Rej\nmacro-F1")]
w = 0.38
for i, (cut, col, name) in enumerate([("O1_cutoff", BLUE, "O1 cutoff"), ("A1_cutoff", ORANGE, "A1 cutoff")]):
    vals = [st[cut][k] for k, _ in keys]
    bars = a.bar([x + (i - 0.5) * w for x in range(len(keys))], vals, w, color=col,
                 label=f"{name} (n={st[cut]['n_records']} claim records)")
    label_bars(a, bars)
a.set_xticks(range(len(keys)), [l for _, l in keys]); a.set_ylim(0, 1.25); a.set_ylabel("Score")
a.set_title("(a) State tracking vs human gold (10 apps" + ("; cut snapshots = empty)" if QWEN else ")"))
a.legend(loc="upper left", fontsize=8, ncol=2)

# (b) Prompt selection on dev+tune (12 apps, automatic reference) — numbers from README, 2026-10-09
a = ax[0, 1]
if QWEN:   # Qwen: usable outputs per cutoff instead (no prompt selection was done for Qwen)
    preds = [json.loads(l) for l in open(SRC / "state_predictions.jsonl")]
    resp_ok = rs["n_predictions"] - len(rs["parse_failures"])
    rows = [(c, sum(p["parse_ok"] for p in preds if p["stage"] == c), sum(p["stage"] == c for p in preds))
            for c in ("O1_cutoff", "A1_cutoff")] + [("reply", resp_ok, rs["n_predictions"])]
    for y, (name, ok, n) in enumerate(rows):
        a.barh(y, ok, 0.55, color=[BLUE, ORANGE, GREEN][y])
        if n - ok:
            a.barh(y, n - ok, 0.55, left=ok, color="white", edgecolor=GREY, hatch="///")
        a.text(n + 0.2, y, f"{ok}/{n} parsed" + (f", {n - ok} cut at 16,384 tokens" if n - ok else ""), va="center", fontsize=8)
    a.set_yticks(range(3), ["State, O1 cutoff", "State, A1 cutoff", "Applicant reply"]); a.invert_yaxis()
    a.set_xlim(0, 17); a.set_xlabel("Gold apps")
    a.set_title("(b) Usable outputs per cutoff")
if not QWEN:
    var = ["p1 minimal", "p1 low", "p2 minimal", "p2 low", "p3 low\n(frozen)"]
    co1 = [0.640, 0.729, 0.523, 0.832, 0.888]; ca1 = [0.578, 0.636, 0.567, 0.607, 0.796]; rej = [0.885, 0.944, 0.900, 0.908, 0.945]
    for vals, col, name in [(co1, BLUE, "Claim, O1"), (ca1, ORANGE, "Claim, A1"), (rej, GREY, "Rej F1 (incl. objections)")]:
        a.plot(range(5), vals, "-o", color=col, label=name, ms=5)
    a.axvspan(3.6, 4.4, color=PURPLE, alpha=0.08)
    a.set_xticks(range(5), var); a.set_ylim(0.4, 1.02); a.set_ylabel("Score")
    a.set_title("(b) Prompt selection (dev+tune, 12 apps, auto reference)")
    a.legend(loc="lower right", fontsize=8)

# (c) Applicant response strategy: per-label F1
a = ax[1, 0]
labs = ["amendment", "argument", "cancellation", "other"]
g = [rs["strat"]["per_label"][l] for l in labs]
sup_tc = rs.get("strat_test_core_supplementary")
off = -w / 2 if sup_tc else 0
b1 = a.bar([x + off for x in range(4)], g, w, color=GREEN,
           label=f"gold 10 (human-checked), macro-F1 {rs['strat']['macro_f1']:.2f}")
label_bars(a, b1)
if sup_tc:
    s = [sup_tc["per_label"][l] for l in labs]
    b2 = a.bar([x + w / 2 for x in range(4)], s, w, color="white", edgecolor=GREEN, hatch="///",
               label=f"test_core 90 (auto labels, record only), macro-F1 {sup_tc['macro_f1']:.2f}")
    label_bars(a, b2)
a.set_xticks(range(4), labs); a.set_ylim(0, 1.3); a.set_ylabel("F1")
a.set_title("(c) Applicant response: strategy F1 by label")
a.legend(loc="upper right", fontsize=7.5, ncol=1)

# (d) Edit P/R/F1 and argument support breakdown
a = ax[1, 1]
e = rs["edit_gold"]
bars = a.bar([0, 1, 2], [e["precision"], e["recall"], e["f1"]], 0.6, color=PURPLE)
label_bars(a, bars)
sp = rs["supp"]; src = sp["by_source"]
sup = sp["supported"]; judged_no = src["llm judge"] - sup; nospan = src["rule: span not found"]; unk = sp["unknown"]
x0 = 3.4; bottom = 0
for v, col, name in [(sup, GREEN, "supported"), (judged_no, ORANGE, "judge: not supported"),
                     (nospan, "#f2b38f", "cited span not found"), (unk, GREY, "no citation (unknown)")]:
    a.bar(x0, v / sp["units"], 0.6, bottom=bottom, color=col, label=f"{name} ({v})")
    bottom += v / sp["units"]
a.annotate(f"Supp = {sup}/{sp['verifiable']} = {sp['supp']:.2f}", (x0, 1.0), xytext=(0, 3),
           textcoords="offset points", ha="center", fontsize=7.5)
a.set_xticks([0, 1, 2, x0], ["Edit P", "Edit R", "Edit F1", f"Supp\n({sp['units']} units)"])
a.set_ylim(0, 1.12); a.set_ylabel("Score / share of argument units")
a.set_title(f"(d) Edits ({e['ref_units']} ref / {e['pred_units']} pred units) and argument support")
a.legend(loc="upper left", fontsize=7.5, bbox_to_anchor=(0.0, 0.95))

fig.suptitle("A — State Tracking + Applicant Response (" + ("qwen3.6-27b, provider-default thinking" if QWEN else
             "gpt-5-mini, reasoning_effort=low") + "; week-3 pilot)",
             x=0.01, ha="left", fontsize=11, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.96))
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"A_results_plot{'_qwen36_27b' if QWEN else ''}.{ext}", dpi=200)
print("wrote", OUT / f"A_results_plot{'_qwen36_27b' if QWEN else ''}.png (and .pdf)")
