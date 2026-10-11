"""Non-LLM reference results for Trajectory Forecasting, fitted only on training labels censored at 2013-12-31.

  km    : marginal Kaplan-Meier S(t) + Aalen-Johansen F_allowance(t), F_abandonment(t). Same curve for every case,
          so its C-index is 0.5 by construction; it is the reference for IBS.  (Required by the plan.)
  cox   : supplementary Cox proportional hazards on features available at the A1 cutoff (fixed before scoring):
          technology center, O1 type, log days filing->O1, log days O1->A1, number of O1 grounds,
          A1 strategy flags. Gives only S(t) (no cause split).

Usage: python baselines_trajectory.py --root path/to/D_trajectory [--which core|test300]
"""
import argparse, json, os
import numpy as np
import pandas as pd
from traj_common import GRID_DAYS, aalen_johansen, load_gold, load_train

STRATS = ["amend_claims", "add_claims", "cancel_claims", "argue", "amend_specification", "amend_drawings",
          "interview", "terminal_disclaimer", "declaration_affidavit"]
TCS = ["1600", "1700", "2100", "2400", "2600", "2800", "3600", "3700"]


def features(df):
    X = pd.DataFrame(index=df.index)
    for tc in TCS[1:]:
        X[f"tc_{tc}"] = (df.tc.astype(str) == tc).astype(float)
    X["o1_final"] = (df.o1_code == "CTFR").astype(float)
    X["log_days_filing_to_o1"] = np.log1p(df.days_filing_to_o1.clip(lower=0))
    X["log_days_o1_to_a1"] = np.log1p(df.days_o1_to_a1.clip(lower=0))
    X["n_grounds_o1"] = df.n_grounds_o1.fillna(0).astype(float)
    st = df.strategy.fillna("")
    for s in STRATS:
        X[f"strat_{s}"] = st.str.split(";").apply(lambda xs: s in xs).astype(float)
    return X


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--which", default="core", choices=["core", "test300"])
    a = ap.parse_args()
    R = a.root
    G = load_gold(R, a.which)
    TR = load_train(R)
    ids = G[G.eligible == True].sample_id.tolist()
    os.makedirs(os.path.join(R, "outputs", "D"), exist_ok=True)
    suffix = "" if a.which == "core" else "_test300"

    # ---- KM / Aalen-Johansen
    S, F1, F2 = aalen_johansen(TR.time_days, TR.label_status, GRID_DAYS)
    with open(os.path.join(R, "outputs", "D", f"trajectory_predictions_km{suffix}.jsonl"), "w") as f:
        for s in ids:
            f.write(json.dumps(dict(sample_id=s, method="km_aalen_johansen", model="none (train KM/AJ)",
                                    input_setting="no covariates", status="ok", repairs=[],
                                    F_allowance=F1.tolist(), F_abandonment=F2.tolist(), S=S.tolist())) + "\n")

    # ---- Cox PH (supplementary)
    from sksurv.linear_model import CoxPHSurvivalAnalysis
    from sksurv.util import Surv
    from sklearn.preprocessing import StandardScaler
    Xtr = features(TR)
    sc = StandardScaler().fit(Xtr)
    y = Surv.from_arrays(event=TR.label_status.values > 0, time=TR.time_days.astype(float).values)
    cox = CoxPHSurvivalAnalysis(alpha=1.0).fit(sc.transform(Xtr), y)  # alpha fixed a priori (ridge)
    TF = pd.read_csv(os.path.join(R, "inputs", "trajectory_test_features.csv"), dtype={"sample_id": str}).set_index("sample_id")
    Xte = features(TF.loc[ids].reset_index())
    fns = cox.predict_survival_function(sc.transform(Xte))
    with open(os.path.join(R, "outputs", "D", f"trajectory_predictions_cox{suffix}.jsonl"), "w") as f:
        for s, fn in zip(ids, fns):
            Sv = np.clip(fn(np.minimum(GRID_DAYS, fn.x[-1])), 0, 1)
            f.write(json.dumps(dict(sample_id=s, method="cox_ph_cutoff_features", model="none (Cox PH, ridge alpha=1)",
                                    input_setting="cutoff features", status="ok", repairs=[],
                                    F_allowance=None, F_abandonment=None, S=Sv.tolist())) + "\n")
    coefs = dict(zip(Xtr.columns, cox.coef_.round(4).tolist()))
    with open(os.path.join(R, "outputs", "D", f"cox_coefficients{suffix}.json"), "w") as f:
        json.dump(dict(features=list(Xtr.columns), coef_standardized=coefs, n_train=len(TR),
                       events_train=int((TR.label_status > 0).sum())), f, indent=1)
    print(f"[{a.which}] KM S(12m)={S[11]:.3f} S(24m)={S[23]:.3f}  F_allow(24m)={F1[23]:.3f}  F_aband(24m)={F2[23]:.3f}")
    print(f"[{a.which}] wrote KM and Cox predictions for {len(ids)} cases")


if __name__ == "__main__":
    main()
