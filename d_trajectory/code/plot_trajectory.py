"""results/trajectory_survival_plot.pdf (+ .png): training KM / Aalen-Johansen vs observed test_core outcomes,
plus the average predicted curve of any LLM prediction file found in outputs/D/.

Usage: python plot_trajectory.py --root path/to/D_trajectory
"""
import argparse, glob, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from traj_common import GRID_DAYS, DAYS_PER_MONTH, aalen_johansen, load_gold, load_predictions, load_train

BLUE, ORANGE, AQUA, INK, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    R = ap.parse_args().root
    G, TR = load_gold(R), load_train(R)
    G = G[G.eligible == True]
    fine = np.arange(0, 731, 1.0)
    m = fine / DAYS_PER_MONTH
    S_tr, A_tr, B_tr = aalen_johansen(TR.time_days, TR.label_status, fine)
    S_te, A_te, B_te = aalen_johansen(G.time_days, G.label_status, fine)

    llm = []
    for f in sorted(glob.glob(os.path.join(R, "outputs", "D", "trajectory_predictions_*.jsonl"))):
        if f.endswith("_test300.jsonl") or "_km" in f or "_cox" in f or "_mock" in f:
            continue
        recs = [r for r in load_predictions(f) if r.get("status") == "ok"]
        if recs:
            llm.append((f"{recs[0].get('model')} ({recs[0].get('input_setting')})", recs))

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False})
    # three panels, same legend logic in each: black = test core observed (the truth), grey dashed = training
    # curve (the KM / Aalen-Johansen baseline every case receives), coloured = mean predicted curve of each AI run.
    fig, ax = plt.subplots(1, 3, figsize=(13.5, 4.2))
    a0, a1, a2 = ax
    panels = [(a0, S_tr, S_te, "S", "Still pending: P(no allowance and no abandonment yet)"),
              (a1, A_tr, A_te, "F_allowance", "Allowed by month t: P(first event = allowance)"),
              (a2, B_tr, B_te, "F_abandonment", "Abandoned by month t: P(first event = abandonment)")]
    gm = GRID_DAYS / DAYS_PER_MONTH
    colors = [AQUA, "#6250d6", "#e87ba4", "#c98a00"]
    for a, tr, te, key, title in panels:
        a.step(m, tr, where="post", color=MUTED, lw=2, ls="--", label="Training curve (KM / AJ baseline, 478 cases)")
        a.step(m, te, where="post", color=INK, lw=2.2, label=f"Test core, what really happened (n={len(G)})")
        for k, (name, recs) in enumerate(llm):
            if all(r.get(key) is not None for r in recs):
                a.plot(gm, np.mean([r[key] for r in recs], axis=0), color=colors[k % len(colors)], lw=1.8, marker="o",
                       ms=3.5, label=f"{name}: mean predicted")
        a.set_title(title, fontsize=9, loc="left")
    for a in ax:
        a.set_xlim(0, 24); a.set_ylim(0, 1); a.set_xticks([0, 6, 12, 18, 24])
        a.set_xlabel("Months after A1 filing"); a.grid(axis="y", color="#e6e5e1", lw=0.8)
    a0.set_ylabel("Share of cases")
    h, l = a0.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    os.makedirs(os.path.join(R, "results"), exist_ok=True)
    fig.savefig(os.path.join(R, "results", "trajectory_survival_plot.pdf"))
    fig.savefig(os.path.join(R, "results", "trajectory_survival_plot.png"), dpi=160)
    print("plot written", "with LLM curves: " + ", ".join(n for n, _ in llm) if llm else "(no LLM predictions yet)")

    # ---- single graph: cumulative incidence by outcome, main setting (state_with_history) ----
    # colour = outcome (blue allowance, orange abandonment); line style = source
    # (dashed training AJ, solid test observed, dash-dot squares GPT, dotted circles Qwen).
    main = [(n, r) for n, r in llm if r[0].get("input_setting") == "state_with_history"]
    style = {"gpt": dict(ls="-.", marker="s", mfc="white", ms=4.5, lw=1.6),
             "qwen": dict(ls=":", marker="o", ms=4.5, lw=1.8)}
    fig, a = plt.subplots(figsize=(7.2, 5.6))
    h_al, h_ab = [], []
    h_al += a.step(m, A_tr, where="post", color=BLUE, lw=2, ls="--", label="Allowance, train AJ")
    h_ab += a.step(m, B_tr, where="post", color=ORANGE, lw=2, ls="--", label="Abandonment, train AJ")
    h_al += a.step(m, A_te, where="post", color=BLUE, lw=2.4, label="Allowance, test observed")
    h_ab += a.step(m, B_te, where="post", color=ORANGE, lw=2.4, label="Abandonment, test observed")
    for name, recs in main:
        st = style["qwen" if "qwen" in name.lower() else "gpt"]
        short = name.replace(" (state_with_history)", "")
        h_al += a.plot(gm, np.mean([r["F_allowance"] for r in recs], axis=0), color=BLUE, **st,
                       label=f"Allowance, {short}")
        h_ab += a.plot(gm, np.mean([r["F_abandonment"] for r in recs], axis=0), color=ORANGE, **st,
                       label=f"Abandonment, {short}")
    a.set_xlim(0, 24); a.set_ylim(0, 1); a.set_xticks([0, 6, 12, 18, 24])
    a.set_xlabel("Months after A1 filing"); a.set_ylabel("Share of cases")
    a.grid(axis="y", color="#e6e5e1", lw=0.8)
    a.set_title(f"Cumulative incidence by outcome (test core n={len(G)}; AI = state + history, mean predicted)",
                fontsize=9, loc="left")
    fig.legend(h_al + h_ab, [x.get_label() for x in h_al + h_ab], loc="lower center", ncol=2, frameon=False,
               fontsize=8)
    fig.tight_layout(rect=(0, 0.17, 1, 1))
    fig.savefig(os.path.join(R, "results", "trajectory_cumulative_incidence.pdf"))
    fig.savefig(os.path.join(R, "results", "trajectory_cumulative_incidence.png"), dpi=160)
    print("cumulative incidence plot written with:", ", ".join(n for n, _ in main))


if __name__ == "__main__":
    main()
