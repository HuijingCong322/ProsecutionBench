"""Non-LLM reference results for Remaining Rounds and Time to Next Action.
Fitted only on training labels censored at 2013-12-31 (inputs/rounds_next_train_labels.csv).

  km  : marginal Kaplan-Meier (no covariates). Same prediction for every case, so its C-index is 0.5 by design.
  cox : Cox proportional hazards (ridge alpha = 1), the same 20 cutoff facts as the Disposition Cox model
        (technology center, O1 type, log days filing->O1, log days O1->A1, number of O1 grounds, 9 A1 strategy flags).

Remaining rounds as a survival problem (so censored training cases are used, not dropped):
  the "time" is N + 1 (1, 2, 3, ...). A case with N = 2 ends at time 3.
  A censored case where we saw k actions is censored at k + 0.5: we only know N >= k.
  P(N >= k) = S(k) and P(N = k) = S(k) - S(k + 1). The point prediction is the median of that distribution
  (the median gives the smallest expected absolute error).
Time to next action: time = days from the cutoff to the next examiner communication. Point prediction = median
  of the predicted curve; risk score for the C-index = Cox linear predictor (higher = sooner).

Usage: python baselines_rounds_next.py --root path/to/D_trajectory [--which core|test300]
Writes outputs/D/rounds_next_predictions_{km,cox}[ _test300].jsonl and outputs/D/rounds_next_cox_coefficients.json
"""
import argparse, json, os
import numpy as np
import pandas as pd
from baselines_trajectory import features

BINS = ["0", "1", "2", "3", "4+"]
MAX_DAYS = 3650


def km_curve(time, event):
    """Kaplan-Meier S(t) as (unique event times, S just after each)."""
    time, event = np.asarray(time, float), np.asarray(event, bool)
    ts = np.unique(time[event])
    S, out = 1.0, []
    for t in ts:
        n = (time >= t).sum()
        d = ((time == t) & event).sum()
        S *= 1 - d / n
        out.append(S)
    return ts, np.array(out)


def step(ts, Ss, t):
    """Right-continuous step function value at t (1 before the first event time)."""
    i = np.searchsorted(ts, t, side="right") - 1
    return 1.0 if i < 0 else float(Ss[i])


def rounds_dist(Sfun):
    """Sfun(k) = P(N + 1 > k) = P(N >= k). Returns P(N=0..3), P(N>=4) and the median."""
    S = [1.0] + [Sfun(k) for k in range(1, 5)]
    p = [max(S[k] - S[k + 1], 0.0) for k in range(4)] + [max(S[4], 0.0)]
    tot = sum(p)
    p = [x / tot for x in p]
    cum = np.cumsum(p)
    med = int(np.argmax(cum >= 0.5))  # 4 means "4 or more" -> predict 4
    return p, med


def median_time(Sfun, grid):
    for t in grid:
        if Sfun(t) <= 0.5:
            return float(t)
    return float(grid[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--which", default="core", choices=["core", "test300"])
    a = ap.parse_args()
    R = a.root
    suffix = "" if a.which == "core" else "_test300"
    G = pd.read_csv(os.path.join(R, "gold", f"rounds_next_gold{suffix}.csv"), dtype={"sample_id": str})
    TRL = pd.read_csv(os.path.join(R, "inputs", "rounds_next_train_labels.csv"), dtype={"sample_id": str})
    TRF = pd.read_csv(os.path.join(R, "inputs", "trajectory_train_labels.csv"), dtype={"sample_id": str})
    TR = TRL.merge(TRF[["sample_id", "o1_code", "days_filing_to_o1", "days_o1_to_a1", "n_grounds_o1", "strategy"]],
                   on="sample_id", how="left", validate="one_to_one")
    assert TR.o1_code.notna().all(), "training features missing"
    TF = pd.read_csv(os.path.join(R, "inputs", "trajectory_test_features.csv"), dtype={"sample_id": str}).set_index("sample_id")
    ids = G.sample_id.tolist()
    os.makedirs(os.path.join(R, "outputs", "D"), exist_ok=True)

    # survival encodings
    r_time = np.where(TR.rounds_censored, TR.rounds + 0.5, TR.rounds + 1).astype(float)
    r_event = (~TR.rounds_censored).values
    n_time = np.maximum(TR.next_days.astype(float).values, 0.5)
    n_event = (~TR.next_censored).values
    day_grid = np.arange(1, MAX_DAYS + 1)

    # ---- KM (marginal)
    ts_r, S_r = km_curve(r_time, r_event)
    p_km, med_km = rounds_dist(lambda k: step(ts_r, S_r, k))
    ts_n, S_n = km_curve(n_time, n_event)
    md_km = median_time(lambda t: step(ts_n, S_n, t), day_grid)
    with open(os.path.join(R, "outputs", "D", f"rounds_next_predictions_km{suffix}.jsonl"), "w") as f:
        for s in ids:
            f.write(json.dumps(dict(sample_id=s, method="km_marginal", model="none (train KM)", input_setting="no covariates",
                                    status="ok", p_rounds=p_km, rounds_pred=med_km, rounds_pred_dist_median=med_km,
                                    next_days_pred=md_km, next_risk=0.0)) + "\n")

    # ---- Cox PH
    from sksurv.linear_model import CoxPHSurvivalAnalysis
    from sksurv.util import Surv
    from sklearn.preprocessing import StandardScaler
    Xtr = features(TR)
    sc = StandardScaler().fit(Xtr)
    Xte = sc.transform(features(TF.loc[ids].reset_index()))
    cox_r = CoxPHSurvivalAnalysis(alpha=1.0).fit(sc.transform(Xtr), Surv.from_arrays(event=r_event, time=r_time))
    cox_n = CoxPHSurvivalAnalysis(alpha=1.0).fit(sc.transform(Xtr), Surv.from_arrays(event=n_event, time=n_time))
    fr = cox_r.predict_survival_function(Xte)
    fn = cox_n.predict_survival_function(Xte)
    risk_n = cox_n.predict(Xte)
    clip = lambda fun, t: float(fun(min(max(t, fun.x[0]), fun.x[-1]))) if t >= fun.x[0] else 1.0
    with open(os.path.join(R, "outputs", "D", f"rounds_next_predictions_cox{suffix}.jsonl"), "w") as f:
        for s, a_r, a_n, rk in zip(ids, fr, fn, risk_n):
            p, med = rounds_dist(lambda k: clip(a_r, k))
            md = median_time(lambda t: clip(a_n, t), np.arange(1, int(a_n.x[-1]) + 1))
            f.write(json.dumps(dict(sample_id=s, method="cox_ph_cutoff_features", model="none (Cox PH, ridge alpha=1)",
                                    input_setting="cutoff features", status="ok", p_rounds=p, rounds_pred=med,
                                    rounds_pred_dist_median=med, next_days_pred=md, next_risk=float(rk))) + "\n")
    with open(os.path.join(R, "outputs", "D", f"rounds_next_cox_coefficients{suffix}.json"), "w") as f:
        json.dump(dict(features=list(Xtr.columns),
                       rounds_coef_standardized=dict(zip(Xtr.columns, cox_r.coef_.round(4).tolist())),
                       next_action_coef_standardized=dict(zip(Xtr.columns, cox_n.coef_.round(4).tolist())),
                       n_train=len(TR), rounds_events=int(r_event.sum()), next_events=int(n_event.sum()),
                       note="positive weight = ends sooner (rounds: fewer further actions; next action: sooner letter)"), f, indent=1)
    print(f"[{a.which}] KM rounds P(0..3,4+) = {[round(x, 3) for x in p_km]}  median {med_km} | KM next-action median {md_km:.0f} days")
    print(f"[{a.which}] wrote KM and Cox predictions for {len(ids)} cases")


if __name__ == "__main__":
    main()
