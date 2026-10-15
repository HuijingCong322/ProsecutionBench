"""GPT-5-mini vs Qwen3.6-27B comparison figure for A (week-3 pilot, gold 10).

Reads only committed result files (no API calls):
  state_metrics.json, response_metrics.json                                (GPT-5-mini)
  outputs/qwen36_27b/state_metrics.json, response_metrics.json,
  outputs/qwen36_27b/state_matched_subset_diagnostic.json, state_predictions.jsonl   (Qwen3.6-27B)
Writes results/A_model_comparison.pdf and results/A_model_comparison.png.

  python3 a_state_response/scripts/plot_model_comparison.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

A = Path(__file__).resolve().parent.parent
Q = A / "outputs" / "qwen36_27b"
OUT = A / "results"; OUT.mkdir(exist_ok=True)
load = lambda p: json.loads(p.read_text())
gs, gr = load(A / "state_metrics.json"), load(A / "response_metrics.json")
qs, qr = load(Q / "state_metrics.json"), load(Q / "response_metrics.json")
diag = load(Q / "state_matched_subset_diagnostic.json")["results"]
qpred = [json.loads(l) for l in open(Q / "state_predictions.jsonl")]
gpred = [json.loads(l) for l in open(A / "outputs" / "state_predictions.jsonl")]
gpred = [p for p in gpred if p["group"] == "gold"]

GPT, QWEN = "#2a78d6", "#eb6834"          # categorical slots 1-2 (validated: CVD dE 24.7, contrast >= 3:1)
INK, MUTED, GRID, TRUNC = "#0b0b0b", "#52514e", "#e6e5e1", "#c9c8c3"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10,
                     "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False})
fig, ax = plt.subplots(2, 2, figsize=(11.5, 7.8))
W = 0.36


def pair(a, labels, gv, qv, ylim=1.18, fmt="{:.2f}"):
    """Grouped bars, GPT left / Qwen right, value labels in text ink."""
    for i, (vals, col, name) in enumerate([(gv, GPT, "gpt-5-mini"), (qv, QWEN, "qwen3.6-27b")]):
        xs = [x + (i - 0.5) * (W + 0.02) for x in range(len(labels))]
        bars = a.bar(xs, vals, W, color=col, label=name, zorder=2)
        for b, v in zip(bars, vals):
            a.annotate(fmt.format(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 2),
                       textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK)
    a.set_xticks(range(len(labels)), labels)
    a.set_ylim(0, ylim)
    a.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)


# (a) Table 3 values (A1 cutoff for Claim/Rej), truncated snapshots scored as empty
a = ax[0, 0]
lab = ["Claim\n(A1)*", "Rej\n(A1)*", "Strat", "Edit F1", "Supp"]
gv = [gs["A1_cutoff"]["claim_version_accuracy"], gs["A1_cutoff"]["rejection_status_macro_f1"],
      gr["strat"]["macro_f1"], gr["edit_gold"]["f1"], gr["supp"]["supp"]]
qv = [qs["A1_cutoff"]["claim_version_accuracy"], qs["A1_cutoff"]["rejection_status_macro_f1"],
      qr["strat"]["macro_f1"], qr["edit_gold"]["f1"], qr["supp"]["supp"]]
pair(a, lab, gv, qv, ylim=1.25)
n_a1_trunc = sum(1 for p in qpred if p["stage"] == "A1_cutoff" and not p["parse_ok"])
a.text(0.01, 0.99, f"* qwen: {n_a1_trunc} of 10 A1 snapshots cut at 16,384 tokens,\n   scored as empty (same rule as gpt)",
       transform=a.transAxes, va="top", fontsize=7.5, color=MUTED)
a.set_ylabel("Score")
a.set_title("(a) Table 3 values (10 gold apps)")

# (b) Claim / Rej on the snapshots both models parsed (diagnostic, not a Table 3 value)
a = ax[0, 1]
lab = [f"Claim, O1\n(n={diag['gpt']['O1_cutoff'][0]} snaps)", f"Claim, A1\n(n={diag['gpt']['A1_cutoff'][0]} snaps)",
       "Claim, all\n(14 snaps)", "Rej, all\n(14 snaps)"]
gv = [diag["gpt"]["O1_cutoff"][2], diag["gpt"]["A1_cutoff"][2], diag["gpt"]["all"][2], diag["gpt"]["all"][3]]
qv = [diag["qwen"]["O1_cutoff"][2], diag["qwen"]["A1_cutoff"][2], diag["qwen"]["all"][2], diag["qwen"]["all"][3]]
pair(a, lab, gv, qv)
a.set_ylabel("Score")
a.set_title("(b) Same 14 snapshots both models parsed")
a.text(0.01, 0.99, "Diagnostic only (removes truncation); not a Table 3 value",
       transform=a.transAxes, va="top", fontsize=7.5, color=MUTED)

# (c) Output completeness: parsed vs truncated snapshots / replies
a = ax[1, 0]
rows = [("gpt-5-mini  state (20)", sum(p["parse_ok"] for p in gpred), len(gpred), GPT),
        ("qwen3.6-27b state (20)", sum(p["parse_ok"] for p in qpred), len(qpred), QWEN),
        ("gpt-5-mini  reply (10)", gr["n_predictions"] - len(gr["parse_failures"]), gr["n_predictions"], GPT),
        ("qwen3.6-27b reply (10)", qr["n_predictions"] - len(qr["parse_failures"]), qr["n_predictions"], QWEN)]
for y, (name, ok, n, col) in enumerate(reversed(rows)):
    a.barh(y, ok, 0.6, color=col, zorder=2)
    if n - ok:
        a.barh(y, n - ok, 0.6, left=ok + 0.08, color=TRUNC, hatch="///", edgecolor="white", lw=0, zorder=2)
    a.text(n + 0.3, y, f"{ok}/{n} parsed" + (f", {n - ok} cut at 16,384 tokens" if n - ok else ""),
           va="center", fontsize=7.5, color=INK)
a.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)])
a.set_xlim(0, 33); a.set_xlabel("Outputs")
a.xaxis.grid(True, color=GRID, lw=0.8, zorder=0)
a.set_title("(c) Usable outputs (same frozen inputs and prompts)")

# (d) Edit precision / recall / F1 and number of proposed units
a = ax[1, 1]
ge, qe = gr["edit_gold"], qr["edit_gold"]
pair(a, ["Edit P", "Edit R", "Edit F1"], [ge["precision"], ge["recall"], ge["f1"]],
     [qe["precision"], qe["recall"], qe["f1"]], ylim=0.7)
a.set_ylabel("Score")
a.set_title(f"(d) Edits vs actual amendment ({ge['ref_units']} reference units)")
a.text(0.01, 0.99, f"proposed units: gpt-5-mini {ge['pred_units']}, qwen3.6-27b {qe['pred_units']}",
       transform=a.transAxes, va="top", fontsize=7.5, color=MUTED)

fig.suptitle("A: gpt-5-mini (reasoning_effort=low) vs qwen3.6-27b (provider-default thinking), "
             "10 gold apps, week-3 pilot", x=0.01, ha="left", fontsize=11, fontweight="bold")
h, l = ax[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper right", ncol=2, fontsize=9, bbox_to_anchor=(0.99, 0.955))
fig.tight_layout(rect=(0, 0, 1, 0.93))
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"A_model_comparison.{ext}", dpi=200)
print("wrote", OUT / "A_model_comparison.pdf", OUT / "A_model_comparison.png")
