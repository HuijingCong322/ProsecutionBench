"""Score Remaining Rounds and Time to Next Action for every outputs/D/rounds_next_predictions_*.jsonl.

Remaining Rounds (paper metrics: MAE, accuracy)
  MAE      = mean |predicted N - true N|                         (lower is better)
  Acc      = share of cases with predicted N exactly right
  Acc+-1   = share within one action (extra diagnostic)
  RPS      = ranked probability score of P(N = 0, 1, 2, 3, 4+)   (lower is better; only if a distribution is given)
Time to Next Action (paper metrics: C-index, MAE in days)
  C-index  = IPCW concordance, tau = 730 days (test_core has no censored case, so this equals Harrell's C);
             risk = higher means the letter comes sooner. A constant prediction gets 0.5.
  MAE days = mean |predicted days - true days|
95% intervals: 1000 case bootstraps, seed 20261010 (one case per family in test_core).
Failed or missing cases are listed and not scored as zero.

Usage: python score_rounds_next.py --root path/to/D_trajectory [--which core|test300]
Writes metrics/D/rounds_next_metrics[ _test300].json and .csv
"""
import argparse, glob, json, os
import numpy as np
import pandas as pd

BINS = 5
TAU = 730.0


def rps(P, y):
    """Ranked probability score for ordered bins 0,1,2,3,4+ (mean over cases)."""
    Y = np.zeros_like(P)
    Y[np.arange(len(y)), np.minimum(y, BINS - 1)] = 1
    return float(np.mean(np.sum((np.cumsum(P, 1) - np.cumsum(Y, 1)) ** 2, 1) / (BINS - 1)))


def cindex(t, ev, risk):
    from sksurv.metrics import concordance_index_ipcw
    from sksurv.util import Surv
    y = Surv.from_arrays(event=ev, time=t)
    return float(concordance_index_ipcw(y, y, risk, tau=TAU)[0])


def score_file(recs, G):
    P = {r["sample_id"]: r for r in recs}
    r0 = recs[0]
    res = dict(method=r0.get("method"), model=r0.get("model"), input_setting=r0.get("input_setting"))
    rng = np.random.default_rng(20261010)
    boot = [rng.integers(0, 10 ** 9) for _ in range(1000)]

    # ---------------- remaining rounds
    E = G[G.eligible_rounds == True]
    ok = [s for s in E.sample_id if s in P and P[s].get("status") == "ok" and P[s].get("rounds_pred") is not None]
    sub = E.set_index("sample_id").loc[ok]
    y = sub.rounds.astype(int).values
    yhat = np.array([int(P[s]["rounds_pred"]) for s in ok])
    err = np.abs(yhat - y)
    rr = dict(eligible_n=len(E), scored_n=len(ok), failed_ids=[s for s in E.sample_id if s not in ok],
              mae=float(err.mean()), acc=float((err == 0).mean()), acc_within1=float((err <= 1).mean()),
              mean_pred=float(yhat.mean()), mean_true=float(y.mean()),
              pred_counts={int(k): int(v) for k, v in zip(*np.unique(yhat, return_counts=True))},
              true_counts={int(k): int(v) for k, v in zip(*np.unique(y, return_counts=True))})
    has_p = all(P[s].get("p_rounds") is not None for s in ok)
    if has_p:
        Pm = np.array([P[s]["p_rounds"] for s in ok], float)
        rr["rps"] = rps(Pm, y)
        rr["mean_p_by_bin"] = Pm.mean(0).round(4).tolist()
        rr["obs_share_by_bin"] = [float(np.mean(np.minimum(y, 4) == k)) for k in range(BINS)]
    if all(P[s].get("rounds_pred_dist_median") is not None for s in ok):
        ym = np.array([int(P[s]["rounds_pred_dist_median"]) for s in ok])
        rr["mae_dist_median"] = float(np.abs(ym - y).mean()); rr["acc_dist_median"] = float((ym == y).mean())
    bm, ba = [], []
    for sd in boot:
        i = np.random.default_rng(sd).integers(0, len(y), len(y))
        bm.append(err[i].mean()); ba.append((err[i] == 0).mean())
    rr["mae_ci95"] = [float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))]
    rr["acc_ci95"] = [float(np.percentile(ba, 2.5)), float(np.percentile(ba, 97.5))]
    res["remaining_rounds"] = rr

    # ---------------- time to next action
    E = G[G.eligible_next == True]
    ok = [s for s in E.sample_id if s in P and P[s].get("status") == "ok" and P[s].get("next_days_pred") is not None]
    sub = E.set_index("sample_id").loc[ok]
    t = sub.next_days.astype(float).values
    ev = np.ones(len(t), bool)
    d = np.array([float(P[s]["next_days_pred"]) for s in ok])
    risk = np.array([float(P[s].get("next_risk", -P[s]["next_days_pred"])) for s in ok])
    ae = np.abs(d - t)
    nr = dict(eligible_n=len(E), scored_n=len(ok), failed_ids=[s for s in E.sample_id if s not in ok],
              c_index=cindex(t, ev, risk), mae_days=float(ae.mean()), median_ae_days=float(np.median(ae)),
              mean_pred_days=float(d.mean()), mean_true_days=float(t.mean()),
              median_pred_days=float(np.median(d)), median_true_days=float(np.median(t)))
    bc, bm = [], []
    for sd in boot:
        i = np.random.default_rng(sd).integers(0, len(t), len(t))
        bm.append(ae[i].mean())
        if np.ptp(risk[i]) > 0:
            bc.append(cindex(t[i], ev[i], risk[i]))
    nr["mae_days_ci95"] = [float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))]
    if bc:
        nr["c_index_ci95"] = [float(np.percentile(bc, 2.5)), float(np.percentile(bc, 97.5))]
    res["time_to_next_action"] = nr
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--which", default="core", choices=["core", "test300"])
    a = ap.parse_args()
    R = a.root
    suffix = "" if a.which == "core" else "_test300"
    G = pd.read_csv(os.path.join(R, "gold", f"rounds_next_gold{suffix}.csv"), dtype={"sample_id": str})
    files = sorted(glob.glob(os.path.join(R, "outputs", "D", "rounds_next_predictions_*.jsonl")))
    files = [f for f in files if f.endswith("_test300.jsonl") == (a.which == "test300")]
    out, flat = [], []
    for f in files:
        recs = [json.loads(x) for x in open(f) if x.strip()]
        if not recs:
            continue
        r = score_file(recs, G)
        r["predictions_file"] = os.path.relpath(f, R)
        out.append(r)
        rr, nr = r["remaining_rounds"], r["time_to_next_action"]
        flat.append(dict(method=r["method"], model=r["model"], input_setting=r["input_setting"],
                         rounds_scored=rr["scored_n"], rounds_mae=rr["mae"], rounds_mae_lo=rr["mae_ci95"][0],
                         rounds_mae_hi=rr["mae_ci95"][1], rounds_acc=rr["acc"], rounds_acc_lo=rr["acc_ci95"][0],
                         rounds_acc_hi=rr["acc_ci95"][1], rounds_acc_within1=rr["acc_within1"], rounds_rps=rr.get("rps"),
                         next_scored=nr["scored_n"], next_c_index=nr["c_index"],
                         next_c_lo=(nr.get("c_index_ci95") or [None])[0], next_c_hi=(nr.get("c_index_ci95") or [None, None])[1],
                         next_mae_days=nr["mae_days"], next_mae_lo=nr["mae_days_ci95"][0], next_mae_hi=nr["mae_days_ci95"][1],
                         predictions_file=r["predictions_file"]))
        print(f"{r['method']:<34} rounds MAE {rr['mae']:.3f} Acc {rr['acc']:.3f} | next C {nr['c_index']:.3f} "
              f"MAE {nr['mae_days']:.1f} d  (scored {rr['scored_n']}/{nr['scored_n']})")
    os.makedirs(os.path.join(R, "metrics", "D"), exist_ok=True)
    meta = dict(test_set="test_core (100)" if a.which == "core" else "test (300)",
                cutoff="A1 filing date (same as Disposition)",
                remaining_rounds="mailed CTNF + CTFR after the cutoff, up to the first NOA or abandonment notice",
                time_to_next_action="days to the first mailed CTNF/CTFR/CTAV/CTRS/CTEQ/NOA/abandonment notice after the cutoff",
                train="A train + excluded_time_boundary (478), nothing after 2013-12-31 used")
    json.dump(dict(meta, results=out), open(os.path.join(R, "metrics", "D", f"rounds_next_metrics{suffix}.json"), "w"), indent=1)
    pd.DataFrame(flat).to_csv(os.path.join(R, "metrics", "D", f"rounds_next_metrics{suffix}.csv"), index=False)


if __name__ == "__main__":
    main()
