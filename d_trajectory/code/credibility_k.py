"""Estimate the credibility constant K of the numbers-only baseline from the data (Buhlmann-Straub).

    python credibility_k.py --episodes path/to/B_D_C_phase1_v4_reviewed/source_D/case_episodes.csv --out metrics/D/credibility_k.json

Why. The numbers-only baseline (examiner_prior.py) blends the examiner's own number with the art-unit pool:
    estimate = Z * examiner + (1 - Z) * pool,   Z = n / (n + K),   n = the examiner's number of past episodes.
Buhlmann-Straub credibility theory gives the K that minimizes the expected squared error of this blend:
K = EPV / VHM, where
    EPV = expected process variance = how much single episodes of the SAME examiner scatter (noise inside an examiner)
    VHM = variance of hypothetical means = how much the TRUE examiner averages differ around their art-unit average
          (the signal we want to keep).
Lots of noise and little real difference between examiners -> big K -> lean on the pool. The reverse -> small K.

Data. Only the episodes the stats cards were built from (D phase 1 case_episodes.csv in the frozen v4 package): every
episode is cut at its case's A1 cutoff, so no test answer is used. One group = one test case = the case's own examiner
plus the examiners of its art-unit pool, all cut at that case's cutoff (exactly the comparison the blend makes).

Per-episode outcome x (only episodes whose outcome is known at the cutoff; same scope as the card statistic):
    next_log_days  log(days) from a reply to a non-final rejection to the next letter (letter seen before the cutoff)
    allowed_24     first reply -> allowed within 730 days (1/0); known if ended within 730 days or followed >= 730 days
    abandoned_24   same, abandoned
    rounds         first reply -> rejections until allowance/abandonment, capped at 4 (application ended before cutoff)
Estimators (Buhlmann-Straub, nonparametric, unbiased; examiner i in group g with n_i episodes, mean xbar_i):
    EPV_hat = sum_i sum_j (x_ij - xbar_i)^2 / sum_i (n_i - 1)
    VHM_hat = [ sum_g sum_(i in g) n_i (xbar_i - xbar_g)^2 - EPV_hat * sum_g (r_g - 1) ] / sum_g (n_g - sum_(i in g) n_i^2 / n_g)
              (xbar_g = episode-weighted group mean, r_g = examiners in the group, n_g = episodes in the group)
    K_hat   = EPV_hat / VHM_hat   (VHM_hat <= 0 -> no detectable examiner difference -> K = infinity, use the pool)
Uncertainty: 1,000 bootstrap draws of the 100 groups (cases), seed 20261010; 95% percentile interval for K.
Sensitivity: the same estimator with one group of all own examiners (difference around the overall mean, not the
art-unit mean).
"""
import argparse, json, math, os
import numpy as np
import pandas as pd

STATS = ["next_log_days", "allowed_24", "abandoned_24", "rounds"]


def truth(s):
    return s.astype(str).str.lower() == "true"


def observations(e):
    """One row per (group, examiner, statistic, episode) with a known outcome."""
    e = e[truth(e.next_signed_ok)].copy()
    e["next_days_cut"] = e.next_days_cut.astype(float)
    e["end_days_cut"] = e.end_days_cut.astype(float)
    e["rounds_cut"] = e.rounds_cut.astype(int)
    out = []
    nf = e[(e.prior_code == "MCTNF") & truth(e.next_observed)]
    out.append(nf.assign(stat="next_log_days", x=np.log(nf.next_days_cut.clip(lower=1))))
    fr = e[truth(e.is_first_reply)]
    ended = fr.end_event_cut.fillna("").astype(str).isin(["allowance", "abandonment"])
    known = (ended & (fr.end_days_cut <= 730)) | (fr.end_days_cut >= 730)
    k = fr[known]
    in24 = k.end_days_cut <= 730
    out.append(k.assign(stat="allowed_24", x=((k.end_event_cut == "allowance") & in24).astype(float)))
    out.append(k.assign(stat="abandoned_24", x=((k.end_event_cut == "abandonment") & in24).astype(float)))
    r = fr[~truth(fr.rounds_censored)]
    out.append(r.assign(stat="rounds", x=r.rounds_cut.clip(upper=4).astype(float)))
    o = pd.concat(out)
    return o[["sample_id", "variant", "examiner_id", "stat", "x"]]


def summarize(o):
    """Per (group, examiner): n, mean, within sum of squares."""
    g = o.groupby(["group", "examiner_id"]).x
    s = pd.DataFrame(dict(n=g.size(), m=g.mean(), ss=g.apply(lambda v: float(((v - v.mean()) ** 2).sum()))))
    return s.reset_index()


def group_parts(s):
    """Per group (case), the additive pieces of the Buhlmann-Straub estimators:
    ss = within-examiner sum of squares, dfw = sum (n_i - 1), ssb = sum n_i (xbar_i - xbar_g)^2, r = r_g - 1,
    den = n_g - sum n_i^2 / n_g, n = episodes. Sums over any set of groups give the estimators for that set."""
    rows = []
    for g, gs in s.groupby("group"):
        ng = gs.n.sum()
        mg = (gs.n * gs.m).sum() / ng
        rows.append(dict(group=g, ss=gs.ss.sum(), dfw=(gs.n - 1).sum(), ssb=float((gs.n * (gs.m - mg) ** 2).sum()),
                         r=len(gs) - 1, den=ng - float((gs.n ** 2).sum()) / ng, n=ng, rows=len(gs)))
    return pd.DataFrame(rows).set_index("group")


def estimate(P):
    """P: summed group pieces (a Series or a 2-D array of sums with columns ss, dfw, ssb, r, den)."""
    epv = P["ss"] / P["dfw"]
    vhm = (P["ssb"] - epv * P["r"]) / P["den"]
    return epv, vhm


def buhlmann_straub(s):
    """s: rows (group, examiner_id, n, m, ss). Returns EPV, VHM, K."""
    P = group_parts(s)
    epv, vhm = estimate(P.sum())
    k = epv / vhm if vhm > 0 else math.inf
    return dict(epv=float(epv), vhm=float(vhm), k=float(k), n_groups=len(P), n_examiner_rows=int(P.rows.sum()),
                n_episodes=int(P.n.sum()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    e = pd.read_csv(a.episodes, dtype=str)
    o = observations(e)
    # main: group = case; members = the case's own examiner + its art-unit pool examiners, same cutoff
    main_o = o[o.variant.isin(["own", "artunit"])].assign(group=lambda d: d.sample_id)
    # sensitivity: one group of all own examiners (each case's own snapshot as its own examiner row)
    all_o = o[o.variant == "own"].assign(group="all", examiner_id=lambda d: d.sample_id + ":" + d.examiner_id)
    res = {}
    rng = np.random.default_rng(20261010)
    cases = sorted(main_o.sample_id.unique())
    draws = [rng.choice(len(cases), len(cases), replace=True) for _ in range(1000)]
    for st in STATS:
        s = summarize(main_o[main_o.stat == st])
        est = buhlmann_straub(s)
        P = group_parts(s).reindex(cases).fillna(0.0)[["ss", "dfw", "ssb", "r", "den"]].to_numpy()
        T = np.array([P[idx].sum(axis=0) for idx in draws])  # a case drawn twice counts twice
        epv_b = T[:, 0] / T[:, 1]
        vhm_b = (T[:, 2] - epv_b * T[:, 3]) / T[:, 4]
        ks = np.where(vhm_b > 0, epv_b / np.where(vhm_b > 0, vhm_b, 1), np.inf)
        ks = np.array(ks)
        fin = ks[np.isfinite(ks) & (ks > 0)]
        est["k_ci95"] = [float(np.percentile(np.where(np.isfinite(ks), ks, 1e9), q)) for q in (2.5, 97.5)]
        est["share_draws_vhm_le_0"] = float(np.mean(~np.isfinite(ks)))
        est["k_boot_median"] = float(np.median(fin)) if len(fin) else None
        est["sensitivity_vs_overall_mean"] = buhlmann_straub(summarize(all_o[all_o.stat == st]))
        res[st] = est
    out = dict(method="Buhlmann-Straub nonparametric credibility, K = EPV / VHM",
               data=os.path.basename(a.episodes), groups="one per test case: own examiner + art-unit pool examiners, all cut at the case's A1 cutoff",
               bootstrap="1000 draws of cases, seed 20261010", stats=res,
               k_used={st: (None if not math.isfinite(r["k"]) else round(r["k"], 1)) for st, r in res.items()},
               note="k_used None = no detectable examiner difference: Z = 0 (pool only)")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1, default=float)
    for st, r in res.items():
        sen = r["sensitivity_vs_overall_mean"]
        print(f"{st:14s} EPV {r['epv']:.4f}  VHM {r['vhm']:.4f}  K {r['k']:.1f}  95% [{r['k_ci95'][0]:.1f}, {r['k_ci95'][1]:.1f}]"
              f"  (VHM<=0 in {r['share_draws_vhm_le_0']:.0%} of draws)  episodes {r['n_episodes']}"
              f" | vs overall mean: K {sen['k']:.1f}")


if __name__ == "__main__":
    main()
