"""Landscape overview of the Table 3 pilot (all members' current results), laid out like Table 3 in the paper draft.

Reads only d_trajectory/results/table3_pilot.csv (D's merged table, rebuilt by d_trajectory/code/build_table3.py).
Writes a_state_response/results/table3_pilot_overview.png and .pdf. No API calls.

  python3 a_state_response/scripts/plot_table3_overview.py
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "d_trajectory" / "results" / "table3_pilot.csv"
OUT = ROOT / "a_state_response" / "results"; OUT.mkdir(exist_ok=True)

GROUPS = [  # (category, colour of the rule under the header, columns) -- same order as the paper's Table 3
    ("Examiner\nPrediction", "#2a78d6", ["Occ.", "Type", "Grnd."]),
    ("Examiner\nGeneration", "#008300", ["R-L", "MET.", "Judge"]),
    ("Applicant\nResponse", "#e34948", ["Strat.", "Edit", "Supp."]),
    ("Trajectory\nForecasting", "#6250d6", ["C-idx", "IBS"]),
    ("State\nTracking", "#eb6834", ["Claim", "Rej."]),
    ("Personalized\nModeling", "#1baf7a", ["dOcc.", "dR-L"]),
]
SHOW = {"IBS": "IBS↓", "dOcc.": "ΔOcc.", "dR-L": "ΔR-L"}
COLS = [c for _, _, cs in GROUPS for c in cs]
# rows: (section, label, model in csv, input settings accepted for B/C/D cells)
MAIN = {"state_with_history", "state_with_history+profile", "record", "record + predicted O1 state",
        "record + predicted O1 state (GPT-derived)"}
ROWS = [("Proprietary", "gpt-5-mini", "gpt-5-mini", MAIN),
        ("Open-weight", "Qwen3.6-27B", "qwen3.6-27b", MAIN),
        ("Input ablation", "gpt-5-mini, history only", "gpt-5-mini", {"history_only"}),
        ("Input ablation", "Qwen3.6-27B, history only", "qwen3.6-27b", {"history_only"}),
        ("Reference (no language model)", "Cox PH, cutoff features", "reference: cox_ph_cutoff_features", None),
        ("Reference (no language model)", "Kaplan-Meier / Aalen-Johansen", "reference: km_aalen_johansen", None)]
FLAG = {("qwen3.6-27b", "Claim"): "*", ("qwen3.6-27b", "Rej."): "*"}

cells = {}
for r in csv.DictReader(open(SRC)):
    cells.setdefault((r["model"], r["table3_column"]), []).append(r)


def cell(model, col, settings):
    rs = [r for r in cells.get((model, col), []) if settings is None or r["input_setting"] in settings]
    if not rs:
        return None
    assert len(rs) == 1, (model, col, rs)
    r = rs[0]
    return float(r["value"]), r["scored_n"], r["eligible_n"]


INK, MUTED, RULE = "#0b0b0b", "#6b6a66", "#bdbcb7"
plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10})
fig = plt.figure(figsize=(17, 7.0))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 100); ax.set_ylim(0, 100)

x0, label_w = 1.5, 17.0
col_w = (100 - x0 - label_w - 1.5) / len(COLS)
xs = {c: x0 + label_w + (i + 0.5) * col_w for i, c in enumerate(COLS)}
top = 93
ax.plot([x0, 98.5], [top, top], color=INK, lw=1.2)
# group headers with a coloured rule underneath (text stays in ink)
for name, colour, cs in GROUPS:
    left, right = xs[cs[0]] - col_w / 2 + 0.3, xs[cs[-1]] + col_w / 2 - 0.3
    ax.text((left + right) / 2, top - 4.2, name, ha="center", va="center", fontsize=10, fontweight="bold", color=INK)
    ax.plot([left, right], [top - 8.2, top - 8.2], color=colour, lw=2.4, solid_capstyle="butt")
ax.text(x0, top - 11, "Model", ha="left", va="center", fontweight="bold")
for c in COLS:
    ax.text(xs[c], top - 11, SHOW.get(c, c), ha="center", va="center")
y = top - 14
ax.plot([x0, 98.5], [y, y], color=INK, lw=0.7)

section = None
for sec, label, model, settings in ROWS:
    if sec != section:
        y -= 4.2
        ax.text(x0, y, sec, ha="left", va="center", style="italic", color=MUTED, fontsize=9.5)
        section = sec
    y -= 6.2
    ax.text(x0 + 0.8, y + 0.6, label, ha="left", va="center")
    for c in COLS:
        v = cell(model, c, settings)
        if v is None:
            ax.text(xs[c], y + 0.6, "–", ha="center", va="center", color=MUTED)
            continue
        val, scored, elig = v
        txt = f"{val:+.2f}" if c in ("dOcc.", "dR-L") else f"{val:.2f}"
        ax.text(xs[c], y + 1.4, txt + FLAG.get((model, c), ""), ha="center", va="center", color=INK)
        ax.text(xs[c], y - 1.6, f"n={scored}" + ("" if scored == elig else f"/{elig}"), ha="center", va="center",
                fontsize=7, color=MUTED)
y -= 4.5
ax.plot([x0, 98.5], [y, y], color=INK, lw=1.2)

notes = ("Pilot results on small fixed subsets (data_v1_share v1.2), not benchmark findings. n = scored cases (scored/eligible when some failed). "
         "Prediction, generation, trajectory and profile cells use the\nstructured state (A's GPT-5-mini A1 state) + history; State Tracking uses the record. "
         "Claim and Rej. are at the A1 cutoff on 10 human-reviewed gold apps; Strat., Edit, Supp. on the same 10 apps (Supp. n = verifiable argument units).\n"
         "* 5 of 10 Qwen A1 snapshots were cut at 16,384 tokens and scored as empty; on the 14 snapshots both models parsed, Claim is 0.90 (Qwen) vs 0.80 (gpt-5-mini). "
         "Judge = fixed GPT-5-mini judge, 1-5.\nExaminer Prediction and Personalized cells use automatic, not yet reviewed gold (B). "
         "Δ = with profile minus without on a small paired subset. Qwen uses provider-default thinking, gpt-5-mini reasoning_effort=low. – = not run.")
ax.text(x0, y - 2.2, notes, ha="left", va="top", fontsize=8, color=MUTED, linespacing=1.5)
ax.text(x0, 98, "Table 3 pilot: all members' current results (week of 2026-10-08, A/B/C/D)", ha="left", va="center",
        fontsize=12, fontweight="bold")
for ext in ("png", "pdf"):
    fig.savefig(OUT / f"table3_pilot_overview.{ext}", dpi=200, bbox_inches="tight", pad_inches=0.15)
print("wrote", OUT / "table3_pilot_overview.png")
