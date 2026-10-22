"""Disposition: the extra analyses promised last week (no API calls; uses the saved predictions).

1. Cause-specific scores ("how does it end?"): for allowance and for abandonment separately, at 12 and 24 months
   - predicted share vs real share
   - Brier score of F_cause(t) against "ended this way by t" (0/1)
   - AUROC: does the model give a higher chance to the cases that really ended this way by t? (0.5 = no better than chance)
2. Calibration + log loss for "ended (either way) by 12 / 24 months": 5 equal-size bins of predicted chance,
   predicted vs real rate per bin; log loss; expected calibration error (ECE, 5 bins).
3. Ranking check (pre-stated sensitivity, not the frozen metric): C-index when the risk score is the chance of
   ending by month 6 or month 12 instead of month 24.
95% intervals: 1000 case bootstraps, seed 20261010.

Usage: python analyze_disposition_extra.py --root path/to/D_trajectory
Writes metrics/D/disposition_extra.json, results/disposition_cause_specific.csv, results/disposition_calibration.csv,
results/disposition_rank_check.csv, results/disposition_calibration_plot.png/.pdf
"""
import argparse, glob, json, os
import numpy as np
import pandas as pd
from traj_common import GRID_DAYS, GRID_MONTHS, load_gold, load_predictions

M = {6: GRID_MONTHS.index(6), 12: GRID_MONTHS.index(12), 24: GRID_MONTHS.index(24)}
ORDER = [("km", "KM / Aalen–Johansen"), ("cox", "Cox"), ("gpt-5-mini.jsonl", "GPT-5-mini, history only"),
         ("gpt-5-mini_state", "GPT-5-mini, state + history"), ("qwen3.6-27b.jsonl", "Qwen3.6-27B, history only"),
         ("qwen3.6-27b_state", "Qwen3.6-27B, state + history")]


def auroc(score, y):
    y = np.asarray(y, bool); s = np.asarray(score, float)
    pos, neg = s[y], s[~y]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    gt = (pos[:, None] > neg[None, :]).sum(); eq = (pos[:, None] == neg[None, :]).sum()
    return float((gt + 0.5 * eq) / (len(pos) * len(neg)))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def bins5(p, y):
    if np.ptp(p) == 0:  # same chance for every case (KM): one point
        return [(float(p[0]), float(np.mean(y)), len(p))]
    order = np.argsort(p, kind="stable"); parts = np.array_split(order, 5)
    return [(float(np.mean(p[i])), float(np.mean(y[i])), len(i)) for i in parts]


def ece(p, y):
    return float(sum(n * abs(a - b) for a, b, n in bins5(p, y)) / len(p))


def harrell(t, ev, risk, tau=730.0):
    tt = np.minimum(t, tau); e = ev & (t <= tau)
    num = den = 0.0
    for i in range(len(t)):
        if not e[i]:
            continue
        later = tt > tt[i]
        den += later.sum(); num += (risk[i] > risk[later]).sum() + 0.5 * (risk[i] == risk[later]).sum()
    return num / den


def boot(fn, n, seed=20261010, B=1000):
    rng = np.random.default_rng(seed); out = []
    for _ in range(B):
        i = rng.integers(0, n, n)
        v = fn(i)
        if v == v:
            out.append(v)
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))] if out else [None, None]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); R = ap.parse_args().root
    G = load_gold(R); G = G[G.eligible == True].set_index("sample_id")
    t = G.time_days.astype(float).values; st = G.label_status.astype(int).values; ids = G.index.tolist()
    files = sorted(glob.glob(os.path.join(R, "outputs", "D", "trajectory_predictions_*.jsonl")))
    files = [f for f in files if not f.endswith("_test300.jsonl") and "_mock" not in f]
    runs = []
    for key, label in ORDER:
        f = [x for x in files if os.path.basename(x).replace("trajectory_predictions_", "").startswith(key)
             or os.path.basename(x).endswith(key)]
        f = [x for x in f if (key != "gpt-5-mini.jsonl" or x.endswith("gpt-5-mini.jsonl"))
             and (key != "qwen3.6-27b.jsonl" or x.endswith("qwen3.6-27b.jsonl"))]
        if not f:
            continue
        P = {r["sample_id"]: r for r in load_predictions(f[0])}
        S = np.array([P[s]["S"] for s in ids], float)
        Fa = np.array([P[s]["F_allowance"] for s in ids], float) if P[ids[0]].get("F_allowance") is not None else None
        Fb = np.array([P[s]["F_abandonment"] for s in ids], float) if P[ids[0]].get("F_abandonment") is not None else None
        runs.append((label, S, Fa, Fb))

    cause_rows, cal_rows, rank_rows, cal_bins = [], [], [], {}
    for label, S, Fa, Fb in runs:
        n = len(ids)
        # ---- 1. cause-specific
        for cause, code, F in (("allowance", 1, Fa), ("abandonment", 2, Fb)):
            for mo in (12, 24):
                y = ((st == code) & (t <= GRID_DAYS[M[mo]])).astype(float)
                row = dict(method=label, cause=cause, month=mo, real_share=float(y.mean()))
                if F is None:
                    row.update(pred_share=None, brier=None, auroc=None, auroc_lo=None, auroc_hi=None)
                else:
                    p = F[:, M[mo]]
                    a = auroc(p, y)
                    lo, hi = boot(lambda i: auroc(p[i], y[i]), n) if np.ptp(p) > 0 else (None, None)
                    row.update(pred_share=float(p.mean()), brier=float(np.mean((p - y) ** 2)), auroc=a, auroc_lo=lo, auroc_hi=hi)
                cause_rows.append(row)
        # ---- 2. calibration + log loss (ended either way by t)
        for mo in (12, 24):
            y = ((st > 0) & (t <= GRID_DAYS[M[mo]])).astype(float)
            p = 1 - S[:, M[mo]]
            ll = logloss(p, y); lo, hi = boot(lambda i: logloss(p[i], y[i]), n)
            cal_rows.append(dict(method=label, month=mo, pred_share=float(p.mean()), real_share=float(y.mean()),
                                 log_loss=ll, log_loss_lo=lo, log_loss_hi=hi, ece_5bins=ece(p, y),
                                 brier=float(np.mean((p - y) ** 2))))
            cal_bins[(label, mo)] = bins5(p, y)
        # ---- 3. ranking check at month 6 / 12 / 24
        ev = st > 0
        for mo in (6, 12, 24):
            r = 1 - S[:, M[mo]]
            c = harrell(t, ev, r)
            lo, hi = boot(lambda i: harrell(t[i], ev[i], r[i]), n, B=500) if np.ptp(r) > 0 else (None, None)
            rank_rows.append(dict(method=label, risk_month=mo, c_index=c, lo=lo, hi=hi))

    os.makedirs(os.path.join(R, "results"), exist_ok=True)
    pd.DataFrame(cause_rows).to_csv(os.path.join(R, "results", "disposition_cause_specific.csv"), index=False)
    pd.DataFrame(cal_rows).to_csv(os.path.join(R, "results", "disposition_calibration.csv"), index=False)
    pd.DataFrame(rank_rows).to_csv(os.path.join(R, "results", "disposition_rank_check.csv"), index=False)
    json.dump(dict(cause_specific=cause_rows, calibration=cal_rows, rank_check=rank_rows,
                   calibration_bins={f"{k[0]} | {k[1]}m": v for k, v in cal_bins.items()},
                   notes="harrell C here truncated at 730 days, risk = 1 - S(month); month 24 equals the Table 3 C-idx up to tie handling"),
              open(os.path.join(R, "metrics", "D", "disposition_extra.json"), "w"), indent=1)

    # ---- calibration plot: 2 panels (12 and 24 months)
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    cols = {"KM / Aalen–Johansen": "#8a8986", "Cox": "#52514e", "GPT-5-mini, history only": "#9cc3f0",
            "GPT-5-mini, state + history": "#2a78d6", "Qwen3.6-27B, history only": "#f5b08f",
            "Qwen3.6-27B, state + history": "#eb6834"}
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(1, 2, figsize=(10, 4.4))
    for k, mo in enumerate((12, 24)):
        a = ax[k]; a.plot([0, 1], [0, 1], color="#0b0b0b", lw=1, ls="--", label="perfect")
        for label, *_ in runs:
            b = cal_bins[(label, mo)]
            a.plot([x[0] for x in b], [x[1] for x in b], marker="o", ms=4, lw=1.6, color=cols[label], label=label)
        a.set_xlim(0, 1.02); a.set_ylim(0, 1.02); a.set_xlabel(f"predicted chance the case has ended by month {mo}")
        a.set_ylabel("real share that ended"); a.set_title(f"Disposition calibration, month {mo} (5 bins of 20 cases)")
    ax[1].legend(fontsize=7.5, loc="lower right", frameon=False)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(R, "results", f"disposition_calibration_plot.{ext}"), dpi=200)
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(pd.DataFrame(cause_rows).round(3).to_string(index=False)); print()
        print(pd.DataFrame(cal_rows).round(3).to_string(index=False)); print()
        print(pd.DataFrame(rank_rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
