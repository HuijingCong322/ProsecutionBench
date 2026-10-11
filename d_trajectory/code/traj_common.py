"""Shared, frozen rules for D / Trajectory Forecasting (ProsecutionBench Table 3 pilot, week of 2026-10-08).

Everything that decides a score lives here, so the LLM runner, the baselines and the scorer use the same rules.
"""
import json, os
import numpy as np
import pandas as pd

GRID_MONTHS = list(range(1, 25))
DAYS_PER_MONTH = 30.4375
GRID_DAYS = np.array([round(m * DAYS_PER_MONTH) for m in GRID_MONTHS], dtype=float)
HORIZON_DAYS = float(GRID_DAYS[-1])  # 730 days = 24 months
I12, I24 = GRID_MONTHS.index(12), GRID_MONTHS.index(24)


# ---------------------------------------------------------------- loading
def load_gold(root, which="core"):
    f = "trajectory_gold.csv" if which == "core" else "trajectory_gold_test300.csv"
    G = pd.read_csv(os.path.join(root, "gold", f), dtype={"sample_id": str})
    E = pd.read_csv(os.path.join(root, "trajectory_eligible_ids.csv" if which == "core"
                                 else "trajectory_eligible_ids_test300.csv"), dtype={"sample_id": str})
    G = G.merge(E[["sample_id", "eligible", "exclusion_reason"]], on="sample_id")
    return G


def load_train(root):
    return pd.read_csv(os.path.join(root, "inputs", "trajectory_train_labels.csv"), dtype={"sample_id": str})


def load_predictions(path):
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def surv_array(df):
    """sksurv structured array: event = any disposition (NOA or abandonment) observed."""
    from sksurv.util import Surv
    return Surv.from_arrays(event=df.label_status.astype(int).values > 0,
                            time=df.time_days.astype(float).values)


# ---------------------------------------------------------------- frozen output rules
def validate_curves(F_allow, F_aband):
    """Frozen repair rules for model output. Returns (F_allow, F_aband, S, repairs) or raises ValueError
    for a structural failure (which is retried once, then listed as failed, never filled with defaults).

    1. Both curves must be lists of 24 numbers (months 1..24).            -> else structural failure
    2. Values are clipped to [0, 1].                                        -> repair 'clipped'
    3. Each curve is made non-decreasing with a running maximum.            -> repair 'monotone'
    4. Where F_allow + F_aband > 1, both are divided by their sum.          -> repair 'renormalized'
       Steps 3-4 repeat until both hold (max 20 passes).
    5. S(t) = 1 - F_allow(t) - F_aband(t).
    """
    out = []
    for name, c in (("F_allowance", F_allow), ("F_abandonment", F_aband)):
        if not isinstance(c, (list, tuple)) or len(c) != len(GRID_MONTHS):
            raise ValueError(f"{name} must be a list of {len(GRID_MONTHS)} numbers")
        try:
            out.append(np.array([float(v) for v in c], dtype=float))
        except (TypeError, ValueError):
            raise ValueError(f"{name} has non-numeric values")
        if not np.all(np.isfinite(out[-1])):
            raise ValueError(f"{name} has non-finite values")
    a, b = out
    repairs = []
    if (a < 0).any() or (a > 1).any() or (b < 0).any() or (b > 1).any():
        repairs.append("clipped")
    a, b = np.clip(a, 0, 1), np.clip(b, 0, 1)
    for _ in range(20):
        changed = False
        ma, mb = np.maximum.accumulate(a), np.maximum.accumulate(b)
        if not (np.allclose(ma, a) and np.allclose(mb, b)):
            repairs.append("monotone"); changed = True
        a, b = ma, mb
        tot = a + b
        if (tot > 1 + 1e-9).any():
            repairs.append("renormalized"); changed = True
            scale = np.where(tot > 1, 1.0 / tot, 1.0)
            a, b = a * scale, b * scale
        if not changed:
            break
    S = np.clip(1.0 - a - b, 0.0, 1.0)
    return a, b, S, sorted(set(repairs))


# ---------------------------------------------------------------- scoring
def score(pred_records, gold, train, method_name=None, n_boot=1000):
    """Score one method. Primary: censoring weights from the evaluation labels (test_core has no censored
    case, so every weight is 1). Sensitivity: censoring weights from the training labels (plan wording)."""
    from sksurv.metrics import concordance_index_ipcw, integrated_brier_score, brier_score, concordance_index_censored

    elig = gold[gold.eligible == True].copy()
    P = {r["sample_id"]: r for r in pred_records}
    ok = [s for s in elig.sample_id if s in P and P[s].get("status") == "ok"]
    failed = [s for s in elig.sample_id if s in P and P[s].get("status") != "ok"]
    missing = [s for s in elig.sample_id if s not in P]
    sub = elig.set_index("sample_id").loc[ok].reset_index()
    S = np.array([P[s]["S"] for s in ok], dtype=float)
    res = dict(method=method_name or (pred_records[0].get("method") if pred_records else None),
               model=pred_records[0].get("model") if pred_records else None,
               input_setting=pred_records[0].get("input_setting") if pred_records else None,
               eligible_n=int(len(elig)), scored_n=len(ok), failed_n=len(failed), missing_n=len(missing),
               excluded_n=int((gold.eligible != True).sum()),
               excluded_reason=";".join(sorted(set(gold.loc[gold.eligible != True, "exclusion_reason"].astype(str)))) or "",
               events_scored={k: int(v) for k, v in sub.event.value_counts().items()},
               horizon_days=HORIZON_DAYS, grid_days=GRID_DAYS.tolist(),
               repairs={}, failed_ids=failed, missing_ids=missing)
    for s in ok:
        for rp in P[s].get("repairs", []):
            res["repairs"][rp] = res["repairs"].get(rp, 0) + 1
    if len(ok) < 10 or sub.label_status.astype(int).gt(0).sum() < 2:
        res["note"] = "fewer than 10 scored cases or fewer than 2 events: metrics N/A"
        return res
    y_test = surv_array(sub)
    risk = 1.0 - S[:, -1]  # risk score = probability of any disposition within the horizon
    for tag, y_cens in (("", y_test), ("_trainG", surv_array(train))):
        try:
            res["c_index" + tag] = float(concordance_index_ipcw(y_cens, y_test, risk, tau=HORIZON_DAYS)[0])
        except Exception as e:  # noqa
            res["c_index" + tag] = None; res["c_index" + tag + "_error"] = str(e)
        try:
            res["ibs" + tag] = float(integrated_brier_score(y_cens, y_test, S, GRID_DAYS))
            _, bs = brier_score(y_cens, y_test, S[:, [I12, I24]], GRID_DAYS[[I12, I24]])
            res["brier_12m" + tag], res["brier_24m" + tag] = float(bs[0]), float(bs[1])
        except Exception as e:  # noqa
            res["ibs" + tag] = None; res["ibs" + tag + "_error"] = str(e)
    # 95% bootstrap intervals (test_core has one case per family, so case resampling = family resampling)
    rng = np.random.default_rng(20261010)
    cs, ibs = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, len(sub), len(sub))
        yb = y_test[idx]
        if yb["event"].sum() < 2 or yb["time"].min() >= GRID_DAYS[0] or yb["time"].max() <= GRID_DAYS[-1]:
            continue
        try:
            cs.append(concordance_index_ipcw(yb, yb, risk[idx], tau=HORIZON_DAYS)[0])
            ibs.append(integrated_brier_score(yb, yb, S[idx], GRID_DAYS))
        except Exception:  # noqa
            pass
    if cs:
        res["c_index_ci95"] = [float(np.percentile(cs, 2.5)), float(np.percentile(cs, 97.5))]
        res["ibs_ci95"] = [float(np.percentile(ibs, 2.5)), float(np.percentile(ibs, 97.5))]
        res["n_boot_used"] = len(cs)
    # Harrell's C truncated at the horizon (sanity check; equals IPCW C when nothing is censored)
    t = sub.time_days.astype(float).values
    ev = (sub.label_status.astype(int).values > 0) & (t <= HORIZON_DAYS)
    res["harrell_c_trunc"] = float(concordance_index_censored(ev, np.minimum(t, HORIZON_DAYS), risk)[0])
    # Calibration-in-the-large and cause-specific diagnostics (both outcomes kept separately)
    by = lambda days, cause: ((sub.label_status.astype(int).values == cause) & (t <= days)).astype(float)
    obs_any12 = ((sub.label_status.astype(int).values > 0) & (t <= GRID_DAYS[I12])).mean()
    obs_any24 = ((sub.label_status.astype(int).values > 0) & (t <= HORIZON_DAYS)).mean()
    res["calibration"] = dict(pred_any_12m=float((1 - S[:, I12]).mean()), obs_any_12m=float(obs_any12),
                              pred_any_24m=float((1 - S[:, I24]).mean()), obs_any_24m=float(obs_any24))
    if all(P[s].get("F_allowance") is not None for s in ok):
        Fa = np.array([P[s]["F_allowance"] for s in ok], dtype=float)
        Fb = np.array([P[s]["F_abandonment"] for s in ok], dtype=float)
        ya, yb = by(HORIZON_DAYS, 1), by(HORIZON_DAYS, 2)
        res["cause_specific_24m"] = dict(
            brier_allowance=float(np.mean((Fa[:, I24] - ya) ** 2)),
            brier_abandonment=float(np.mean((Fb[:, I24] - yb) ** 2)),
            pred_allowance=float(Fa[:, I24].mean()), obs_allowance=float(ya.mean()),
            pred_abandonment=float(Fb[:, I24].mean()), obs_abandonment=float(yb.mean()))
    return res


# ---------------------------------------------------------------- nonparametric curves (train)
def aalen_johansen(time, status, grid):
    """Kaplan-Meier S(t) for any event and Aalen-Johansen cumulative incidence for cause 1 and cause 2.
    status: 0 censored, 1 allowance, 2 abandonment. Returns arrays evaluated at `grid` (right-continuous)."""
    time, status = np.asarray(time, float), np.asarray(status, int)
    ts = np.unique(time[status > 0])
    S, F1, F2 = 1.0, 0.0, 0.0
    steps = []
    for t in ts:
        n = (time >= t).sum()
        d1 = ((time == t) & (status == 1)).sum()
        d2 = ((time == t) & (status == 2)).sum()
        F1 += S * d1 / n
        F2 += S * d2 / n
        S *= 1 - (d1 + d2) / n
        steps.append((t, S, F1, F2))
    out = np.zeros((len(grid), 3))
    for i, g in enumerate(grid):
        cur = (1.0, 0.0, 0.0)
        for t, s, f1, f2 in steps:
            if t <= g:
                cur = (s, f1, f2)
            else:
                break
        out[i] = cur
    return out[:, 0], out[:, 1], out[:, 2]
