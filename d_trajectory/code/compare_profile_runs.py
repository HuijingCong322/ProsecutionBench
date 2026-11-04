"""Phase 2 scoring: LLM + examiner profile vs. the frozen comparisons in personalization_protocol.md.

    python compare_profile_runs.py --root path/to/D_trajectory [--models gpt-5-mini,qwen3.6-27b]

Reads the prediction files already in outputs/D (nothing is re-run, no API):
    {M}_state                    LLM, state + history, no profile (the frozen baseline from Oct 2026)
    {M}_state_profile_own        LLM + the case's own examiner profile
    {M}_state_profile_mismatched LLM + another examiner's profile (same art unit)
    prior_own / prior_mismatched examiner numbers only, no LLM (examiner_prior.py)
    km                           plain average
For each model it scores all 3 tasks on the same 100 test_core cases and the frozen paired differences
(1,000 paired bootstraps, seed 20261010, cases where both methods have an answer), then the planned splits:
retrieved_k (3 vs < 3), RCE in the true path (0 vs 1+), and the 6 all-censored cards.
Addendum A (protocol section 9) adds the examples-only runs ({M}_state_profile_{own,mismatched}_exonly) and the
examples lookup baseline (exlookup_{own,mismatched}, from examples_lookup.py).
Writes metrics/D/profile_phase2_metrics.json and results/profile_phase2_table.csv.
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from traj_common import GRID_DAYS, HORIZON_DAYS, load_gold, load_predictions, surv_array  # noqa
from score_rounds_next import cindex  # noqa

METRICS = ["disp_c_index", "disp_ibs", "rounds_mae", "rounds_acc", "next_c_index", "next_mae_days"]
# cards whose first-reply cases were all still pending at the cutoff (CENSORING_INTERPRETATION.csv in the v4 package)
ALL_CENSORED = {("13627444", "mismatched"), ("13086389", "own"), ("13484627", "own"), ("13773735", "own"),
                ("13816667", "own"), ("14031839", "own")}


def comparisons(m):
    """Frozen before any profile run (personalization_protocol.md section 4)."""
    return [(f"{m}_state_profile_own", f"{m}_state", "primary: does the own profile help the LLM?"),
            (f"{m}_state_profile_own", f"{m}_state_profile_mismatched", "is it this examiner (vs another examiner)?"),
            (f"{m}_state_profile_own", "prior_own", "new bar: does the LLM beat the examiner numbers alone?"),
            (f"{m}_state_profile_mismatched", f"{m}_state", "control: does any profile help?"),
            # Addendum A (protocol section 9): examples only, no examiner statistics to copy
            (f"{m}_state_profile_own_exonly", f"{m}_state", "A1: do the examiner's past cases help without the numbers?"),
            (f"{m}_state_profile_own_exonly", f"{m}_state_profile_mismatched_exonly", "A2: is it this examiner's cases?"),
            (f"{m}_state_profile_own_exonly", "exlookup_own", "A3: does the LLM beat copying the example days?"),
            (f"{m}_state_profile_own_exonly", f"{m}_state_profile_own", "A4 (descriptive): cost of removing the numbers")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--models", default="gpt-5-mini,qwen3.6-27b")
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args()
    R = a.root
    out_dir = os.path.join(R, "outputs", "D")
    G = load_gold(R)
    Ge = G[G.eligible == True].set_index("sample_id")
    GR = pd.read_csv(os.path.join(R, "gold", "rounds_next_gold.csv"), dtype={"sample_id": str}).set_index("sample_id")
    ids_all = list(Ge.index)
    rces = GR.loc[ids_all, "rces"].fillna(0).astype(int)

    def load(name):
        ft = os.path.join(out_dir, f"trajectory_predictions_{name}.jsonl")
        fr = os.path.join(out_dir, f"rounds_next_predictions_{name}.jsonl")
        if not (os.path.exists(ft) and os.path.exists(fr)):
            return None
        T = {r["sample_id"]: r for r in load_predictions(ft) if r.get("status") == "ok"}
        Q = {r["sample_id"]: r for r in load_predictions(fr) if r.get("status") == "ok"}
        return T, Q

    from sksurv.metrics import concordance_index_ipcw, integrated_brier_score

    def metrics_on(run, ids):
        T, Q = run
        it = [s for s in ids if s in T]
        iq = [s for s in ids if s in Q]
        res = dict(n_disp=len(it), n_rn=len(iq))
        if len(it) >= 5:
            y = surv_array(Ge.loc[it].reset_index())
            S = np.array([T[s]["S"] for s in it], float)
            try:
                res["disp_c_index"] = float(concordance_index_ipcw(y, y, 1 - S[:, -1], tau=HORIZON_DAYS)[0])
                res["disp_ibs"] = float(integrated_brier_score(y, y, S, GRID_DAYS))
            except Exception:  # noqa  tiny subgroup
                pass
        if len(iq) >= 5:
            yr = GR.loc[iq, "rounds"].astype(int).values
            yt = GR.loc[iq, "next_days"].astype(float).values
            rp = np.array([int(Q[s]["rounds_pred"]) for s in iq])
            nd = np.array([float(Q[s]["next_days_pred"]) for s in iq])
            nr = np.array([float(Q[s].get("next_risk", -Q[s]["next_days_pred"])) for s in iq])
            res.update(rounds_mae=float(np.abs(rp - yr).mean()), rounds_acc=float((rp == yr).mean()),
                       next_mae_days=float(np.abs(nd - yt).mean()))
            # a constant risk (KM) ranks nothing: 0.5, as in the frozen tables
            res["next_c_index"] = cindex(yt, np.ones(len(yt), bool), nr) if np.ptp(nr) > 0 else 0.5
        return res

    def paired(ra, rb):
        Ta, Qa = ra
        Tb, Qb = rb
        it = [s for s in ids_all if s in Ta and s in Tb]
        iq = [s for s in ids_all if s in Qa and s in Qb]
        y = surv_array(Ge.loc[it].reset_index())
        Sa = np.array([Ta[s]["S"] for s in it], float); Sb = np.array([Tb[s]["S"] for s in it], float)
        yr = GR.loc[iq, "rounds"].astype(int).values; yt = GR.loc[iq, "next_days"].astype(float).values
        ev = np.ones(len(yt), bool)
        rpa = np.array([int(Qa[s]["rounds_pred"]) for s in iq]); rpb = np.array([int(Qb[s]["rounds_pred"]) for s in iq])
        nda = np.array([float(Qa[s]["next_days_pred"]) for s in iq]); ndb = np.array([float(Qb[s]["next_days_pred"]) for s in iq])
        nra = -nda if not all("next_risk" in Qa[s] for s in iq) else np.array([float(Qa[s]["next_risk"]) for s in iq])
        nrb = -ndb if not all("next_risk" in Qb[s] for s in iq) else np.array([float(Qb[s]["next_risk"]) for s in iq])

        def dm(yy, S):
            return (float(concordance_index_ipcw(yy, yy, 1 - S[:, -1], tau=HORIZON_DAYS)[0]),
                    float(integrated_brier_score(yy, yy, S, GRID_DAYS)))
        ca, ia = dm(y, Sa); cb, ib = dm(y, Sb)
        point = dict(disp_c_index=ca - cb, disp_ibs=ia - ib,
                     rounds_mae=np.abs(rpa - yr).mean() - np.abs(rpb - yr).mean(),
                     rounds_acc=(rpa == yr).mean() - (rpb == yr).mean(),
                     next_c_index=cindex(yt, ev, nra) - cindex(yt, ev, nrb),
                     next_mae_days=np.abs(nda - yt).mean() - np.abs(ndb - yt).mean())
        rng = np.random.default_rng(20261010)
        dd = {m: [] for m in METRICS}
        for _ in range(a.n_boot):
            i1 = rng.integers(0, len(it), len(it))
            yb = y[i1]
            if yb["event"].sum() >= 2 and yb["time"].min() < GRID_DAYS[0] and yb["time"].max() > GRID_DAYS[-1]:
                try:
                    c1, b1 = dm(yb, Sa[i1]); c2, b2 = dm(yb, Sb[i1])
                    dd["disp_c_index"].append(c1 - c2); dd["disp_ibs"].append(b1 - b2)
                except Exception:  # noqa
                    pass
            i2 = rng.integers(0, len(iq), len(iq))
            ea, eb = np.abs(rpa[i2] - yr[i2]), np.abs(rpb[i2] - yr[i2])
            dd["rounds_mae"].append(ea.mean() - eb.mean()); dd["rounds_acc"].append((ea == 0).mean() - (eb == 0).mean())
            dd["next_mae_days"].append(np.abs(nda[i2] - yt[i2]).mean() - np.abs(ndb[i2] - yt[i2]).mean())
            if np.ptp(nra[i2]) > 0 and np.ptp(nrb[i2]) > 0:
                dd["next_c_index"].append(cindex(yt[i2], ev[i2], nra[i2]) - cindex(yt[i2], ev[i2], nrb[i2]))
        out = {}
        for m in METRICS:
            v = dd[m]
            ci = [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None
            out[m] = dict(delta=float(point[m]), ci95=ci, n_boot=len(v),
                          clear=bool(ci and (ci[0] > 0 or ci[1] < 0)))
        out["n_disp"], out["n_rn"] = len(it), len(iq)
        return out

    names = {"km", "prior_own", "prior_mismatched", "exlookup_own", "exlookup_mismatched"}
    for m in a.models.split(","):
        names |= {f"{m}_state", f"{m}_state_profile_own", f"{m}_state_profile_mismatched",
                  f"{m}_state_profile_own_exonly", f"{m}_state_profile_mismatched_exonly"}
    runs = {n: r for n in sorted(names) if (r := load(n)) is not None}
    missing = sorted(names - set(runs))
    print("found:", ", ".join(sorted(runs)))
    if missing:
        print("not found yet (skipped):", ", ".join(missing))

    # profile meta for splits
    kmap = {}
    for n, (T, Q) in runs.items():
        if "_profile_" in n:
            for s, r in Q.items():
                kmap[(s, r.get("profile_setting"))] = r.get("retrieved_k")

    scores = {n: metrics_on(r, ids_all) for n, r in runs.items()}
    pair = {}
    for m in a.models.split(","):
        for x, b, why in comparisons(m):
            if x in runs and b in runs:
                pair[f"{x}_vs_{b}"] = dict(question=why, **paired(runs[x], runs[b]))

    splits = {}
    for n in runs:
        v = "own" if ("_own" in n or n.endswith("own")) else "mismatched" if "mismatched" in n else None
        groups = {"rce_0": [s for s in ids_all if rces[s] == 0], "rce_1plus": [s for s in ids_all if rces[s] > 0]}
        if v:
            groups["retrieved_k_3"] = [s for s in ids_all if kmap.get((s, v), 3) == 3]
            groups["retrieved_k_lt3"] = [s for s in ids_all if kmap.get((s, v), 3) < 3]
            groups["all_censored_card"] = [s for s in ids_all if (s, v) in ALL_CENSORED]
            groups["without_all_censored_cards"] = [s for s in ids_all if (s, v) not in ALL_CENSORED]
        splits[n] = {g: dict(n_cases=len(ii), **metrics_on(runs[n], ii)) for g, ii in groups.items()}

    os.makedirs(os.path.join(R, "metrics", "D"), exist_ok=True); os.makedirs(os.path.join(R, "results"), exist_ok=True)
    json.dump(dict(note="phase 2 examiner personalization, test_core 100; delta = first minus second on the same cases; "
                        "C-index / accuracy higher is better, IBS / MAE lower is better; clear = 95% CI excludes 0",
                   seed=20261010, n_boot=a.n_boot, scores=scores, paired=pair, splits=splits),
              open(os.path.join(R, "metrics", "D", "profile_phase2_metrics.json"), "w"), indent=1)
    tab = pd.DataFrame([dict(method=n, **{k: v for k, v in s.items()}) for n, s in scores.items()])
    tab.to_csv(os.path.join(R, "results", "profile_phase2_table.csv"), index=False)
    pd.set_option("display.width", 220)
    print(tab.round(3).to_string(index=False))
    for k, v in pair.items():
        print(f"\n{k}  ({v['question']})  n={v['n_disp']}/{v['n_rn']}")
        for mt in METRICS:
            x = v[mt]
            ci = f"[{x['ci95'][0]:+.3f}, {x['ci95'][1]:+.3f}]" if x["ci95"] else "n/a"
            print(f"   {mt:<14} {x['delta']:+.3f} {ci}{'  clear' if x['clear'] else ''}")


if __name__ == "__main__":
    main()
