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
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
    a0, a1 = ax
    a0.step(m, S_tr, where="post", color=MUTED, lw=2, ls="--", label="Train KM (censored at 2013-12-31)")
    a0.step(m, S_te, where="post", color=INK, lw=2, label=f"Test core, observed (n={len(G)})")
    a0.set_title("Still pending: S(t) = P(no NOA and no abandonment yet)", fontsize=9, loc="left")
    a1.step(m, A_tr, where="post", color=BLUE, lw=2, ls="--", label="Allowance, train AJ")
    a1.step(m, A_te, where="post", color=BLUE, lw=2, label="Allowance, test observed")
    a1.step(m, B_tr, where="post", color=ORANGE, lw=2, ls="--", label="Abandonment, train AJ")
    a1.step(m, B_te, where="post", color=ORANGE, lw=2, label="Abandonment, test observed")
    a1.set_title("Cumulative incidence by outcome", fontsize=9, loc="left")
    gm = GRID_DAYS / DAYS_PER_MONTH
    colors = [AQUA, "#6250d6", "#e87ba4"]
    for k, (name, recs) in enumerate(llm):
        AQUA_k = colors[k % len(colors)]
        Sm = np.mean([r["S"] for r in recs], axis=0)
        a0.plot(gm, Sm, color=AQUA_k, lw=2, marker="o", ms=4, label=f"{name}: mean predicted")
        if k == len(llm) - 1 and all(r.get("F_allowance") is not None for r in recs):  # right panel: last run only
            a1.plot(gm, np.mean([r["F_allowance"] for r in recs], axis=0), color=BLUE, lw=1.5, ls=":", marker="o", ms=4,
                    label=f"Allowance, {name}")
            a1.plot(gm, np.mean([r["F_abandonment"] for r in recs], axis=0), color=ORANGE, lw=1.5, ls=":", marker="o",
                    ms=4, label=f"Abandonment, {name}")
    for a in ax:
        a.set_xlim(0, 24); a.set_ylim(0, 1); a.set_xticks([0, 6, 12, 18, 24])
        a.set_xlabel("Months after A1 filing"); a.grid(axis="y", color="#e6e5e1", lw=0.8)
        a.legend(frameon=False, fontsize=7, loc="upper right" if a is a0 else "upper left")
    a0.set_ylabel("Probability")
    fig.tight_layout()
    os.makedirs(os.path.join(R, "results"), exist_ok=True)
    fig.savefig(os.path.join(R, "results", "trajectory_survival_plot.pdf"))
    fig.savefig(os.path.join(R, "results", "trajectory_survival_plot.png"), dpi=160)
    print("plot written", "with LLM curves: " + ", ".join(n for n, _ in llm) if llm else "(no LLM predictions yet)")


if __name__ == "__main__":
    main()
