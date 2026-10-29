"""Examiner-prior baselines (no LLM) for the 3 trajectory tasks, from D's stats cards.

    python examiner_prior.py --root path/to/D_trajectory --cards profile_phase1/stats_cards.jsonl

For each test_core case and each profile version (own, mismatched, artunit):
  Disposition   the training KM/Aalen-Johansen curves (the KM baseline every case gets), stretched so that month 24
                hits the examiner's numbers: F_allow(t) * a24 / F_allow_train(24), F_aband(t) * b24 / F_aband_train(24),
                then the frozen repair rules (validate_curves). a24 / b24 = allowed / abandoned within 24 months after
                the first reply, shrunk toward the art-unit pool (k = 5); the art-unit version uses the pool itself.
  Rounds        P(N = 0..3, 4+) after the first reply, each share shrunk toward the pool, renormalized;
                the point guess is the median (as for KM and Cox).
  Next action   the examiner's median days from a reply (to a non-final rejection) to the next letter, shrunk on the
                log scale; risk = minus the days.
Writes outputs/D/{trajectory,rounds_next}_predictions_prior_{own,mismatched,artunit}.jsonl and
metrics/D/examiner_prior_metrics.json (scores + paired differences against KM, same cases, seed 20261010).
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from traj_common import GRID_DAYS, HORIZON_DAYS, load_gold, load_predictions, load_train, score, surv_array, validate_curves  # noqa
from score_rounds_next import score_file, cindex  # noqa

K = 5
BINS = ["0", "1", "2", "3", "4+"]


def shrink(x, n, p):
    if x is None:
        return p
    if p is None:
        return x
    return (n * x + K * p) / (n + K)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--cards", required=True)
    a = ap.parse_args()
    R = a.root
    cards = [json.loads(l) for l in open(a.cards)]
    by = {(c["sample_id"], c["variant"]): c for c in cards}
    km = {r["sample_id"]: r for r in load_predictions(os.path.join(R, "outputs", "D", "trajectory_predictions_km.jsonl"))}
    km_rn = {r["sample_id"]: r for r in load_predictions(os.path.join(R, "outputs", "D", "rounds_next_predictions_km.jsonl"))}
    k0 = next(iter(km.values()))
    FA0, FB0 = np.array(k0["F_allowance"]), np.array(k0["F_abandonment"])
    out_dir = os.path.join(R, "outputs", "D")
    written = {}
    for v in ["own", "mismatched", "artunit"]:
        traj, rn = [], []
        for sid in km:
            c = by[(sid, v)]
            pool = by[(sid, "artunit")]["stats"]
            s = c["stats"]
            fr, pf = s["first_reply"], pool["first_reply"]
            nl, pn = s["next_letter"], pool["next_letter"]
            if v == "artunit":
                a24, b24 = fr["allowed_by_24m"], fr["abandoned_by_24m"]
                dist = fr["rounds_dist_km"]
                days = nl["median_days_km"]
            else:
                sh = c["shrunk"]
                a24, b24, days = sh["allowed_by_24m"], sh["abandoned_by_24m"], sh["median_days_next_letter"]
                n = fr["n_episodes"]
                dist = {b: shrink(fr["rounds_dist_km"][b] if fr["rounds_dist_km"] else None, n,
                                  pf["rounds_dist_km"][b] if pf["rounds_dist_km"] else None) for b in BINS}
            # disposition
            FA = FA0 * (a24 / FA0[-1]) if a24 is not None else FA0
            FB = FB0 * (b24 / FB0[-1]) if b24 is not None else FB0
            FA, FB, S, rep = validate_curves(FA.tolist(), FB.tolist())
            traj.append(dict(sample_id=sid, method=f"examiner_prior_{v}", model="none (examiner numbers)",
                             input_setting=f"{v} profile numbers", status="ok", repairs=rep,
                             F_allowance=list(map(float, FA)), F_abandonment=list(map(float, FB)), S=list(map(float, S)),
                             card_sha1=c["card_sha1"], a24=a24, b24=b24))
            # rounds + next action
            p = np.array([max(0.0, dist[b]) for b in BINS], float) if dist else np.array(km_rn[sid]["p_rounds"])
            p = p / p.sum()
            med = int(np.argmax(np.cumsum(p) >= 0.5))
            d = float(round(days)) if days else km_rn[sid]["next_days_pred"]
            rn.append(dict(sample_id=sid, method=f"examiner_prior_{v}", model="none (examiner numbers)",
                           input_setting=f"{v} profile numbers", status="ok", p_rounds=p.round(6).tolist(),
                           rounds_pred=med, rounds_pred_dist_median=med, next_days_pred=d, next_risk=-d,
                           card_sha1=c["card_sha1"]))
        for name, recs in [("trajectory", traj), ("rounds_next", rn)]:
            f = os.path.join(out_dir, f"{name}_predictions_prior_{v}.jsonl")
            with open(f, "w") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
        written[v] = (traj, rn)

    # ---------------- score + paired vs KM (and vs the frozen LLM runs that exist)
    G, TR = load_gold(R), load_train(R)
    GR = pd.read_csv(os.path.join(R, "gold", "rounds_next_gold.csv"), dtype={"sample_id": str})
    Ge = G[G.eligible == True].set_index("sample_id")
    ids = [s for s in Ge.index]
    y = surv_array(Ge.loc[ids].reset_index())
    from sksurv.metrics import concordance_index_ipcw, integrated_brier_score

    def dmetrics(yy, S):
        return (float(concordance_index_ipcw(yy, yy, 1 - S[:, -1], tau=HORIZON_DAYS)[0]),
                float(integrated_brier_score(yy, yy, S, GRID_DAYS)))

    gr = GR.set_index("sample_id").loc[ids]
    yr, yt = gr.rounds.astype(int).values, gr.next_days.astype(float).values
    ev = np.ones(len(yt), bool)

    def arrays(traj_recs, rn_recs):
        P = {r["sample_id"]: r for r in traj_recs}
        Q = {r["sample_id"]: r for r in rn_recs}
        S = np.array([P[s]["S"] for s in ids], float)
        rp = np.array([int(Q[s]["rounds_pred"]) for s in ids])
        nd = np.array([float(Q[s]["next_days_pred"]) for s in ids])
        nr = np.array([float(Q[s].get("next_risk", -Q[s]["next_days_pred"])) for s in ids])
        return S, rp, nd, nr

    comps = {"km": (list(km.values()), list(km_rn.values()))}
    for v, (t, r) in written.items():
        comps["prior_" + v] = (t, r)
    for name in ["cox", "gpt-5-mini", "qwen3.6-27b_state"]:
        ft = os.path.join(out_dir, f"trajectory_predictions_{name}.jsonl")
        fr_ = os.path.join(out_dir, f"rounds_next_predictions_{name}.jsonl")
        if os.path.exists(ft) and os.path.exists(fr_):
            comps[name] = (load_predictions(ft), load_predictions(fr_))
    A = {k: arrays(*v) for k, v in comps.items()}
    res = {}
    for k, (S, rp, nd, nr) in A.items():
        c, i = dmetrics(y, S)
        res[k] = dict(disp_c_index=c, disp_ibs=i, rounds_mae=float(np.abs(rp - yr).mean()),
                      rounds_acc=float((rp == yr).mean()), next_c_index=cindex(yt, ev, nr),
                      next_mae_days=float(np.abs(nd - yt).mean()),
                      rounds_pred_counts={int(a): int(b) for a, b in zip(*np.unique(rp, return_counts=True))},
                      next_median_pred=float(np.median(nd)))
    rng = np.random.default_rng(20261010)
    draws = [rng.integers(0, len(ids), len(ids)) for _ in range(1000)]
    paired = {}
    for k in [x for x in A if x.startswith("prior_")]:
        for base in ["km"] + [x for x in A if not x.startswith("prior_") and x != "km"]:
            Sa, ra, na, nra = A[k]
            Sb, rb, nb, nrb = A[base]
            dd = {m: [] for m in ["disp_c_index", "disp_ibs", "rounds_mae", "rounds_acc", "next_c_index", "next_mae_days"]}
            for idx in draws:
                yb = y[idx]
                ok = not (yb["event"].sum() < 2 or yb["time"].min() >= GRID_DAYS[0] or yb["time"].max() <= GRID_DAYS[-1])
                if ok:
                    try:
                        ca, ia = dmetrics(yb, Sa[idx]); cb, ib = dmetrics(yb, Sb[idx])
                        dd["disp_c_index"].append(ca - cb); dd["disp_ibs"].append(ia - ib)
                    except Exception:  # noqa
                        pass
                ea, eb = np.abs(ra[idx] - yr[idx]), np.abs(rb[idx] - yr[idx])
                dd["rounds_mae"].append(ea.mean() - eb.mean())
                dd["rounds_acc"].append((ea == 0).mean() - (eb == 0).mean())
                dd["next_mae_days"].append(np.abs(na[idx] - yt[idx]).mean() - np.abs(nb[idx] - yt[idx]).mean())
                if np.ptp(nra[idx]) > 0:
                    cb_ = cindex(yt[idx], ev[idx], nrb[idx]) if np.ptp(nrb[idx]) > 0 else 0.5
                    dd["next_c_index"].append(cindex(yt[idx], ev[idx], nra[idx]) - cb_)
            paired[f"{k}_vs_{base}"] = {m: dict(delta=float(res[k][m] - res[base][m]),
                                                ci95=[float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None,
                                                n_boot=len(v)) for m, v in dd.items()}
    os.makedirs(os.path.join(R, "metrics", "D"), exist_ok=True)
    out = dict(note="examiner-prior baselines (no LLM), test_core 100; deltas = prior minus comparison on the same cases; "
                    "C-index and accuracy higher is better, IBS / MAE lower is better; 1000 paired bootstraps, seed 20261010",
               cards_file=os.path.basename(a.cards), k_shrink=K, scores=res, paired=paired)
    json.dump(out, open(os.path.join(R, "metrics", "D", "examiner_prior_metrics.json"), "w"), indent=1)
    rows = [dict(method=k, **{m: v for m, v in r.items() if not isinstance(v, dict)}) for k, r in res.items()]
    pd.DataFrame(rows).to_csv(os.path.join(R, "metrics", "D", "examiner_prior_metrics.csv"), index=False)
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    for k, v in paired.items():
        if k.endswith("_vs_km") or "qwen" in k:
            print(k, {m: (round(x["delta"], 3), [round(c, 3) for c in x["ci95"]] if x["ci95"] else None) for m, x in v.items()})


if __name__ == "__main__":
    main()
