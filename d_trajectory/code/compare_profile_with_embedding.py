"""profile_with_embedding scoring: the comparisons fixed in profile_with_embedding_protocol.md (no API).

    python compare_profile_with_embedding.py --root path/to/D_trajectory [--model gpt-5-mini]

Reads prediction files already in outputs/D ({M} = model). Every LLM run uses the same case record, A's state (A_v1)
and the frozen *_profile.txt prompts; only the examiner block differs.
  LLM, this week
    {M}_state_profile_with_embedding_card_{own,mismatched}     statistics card from the examiner's full history only
    {M}_state_profile_with_embedding_paths_{own,mismatched}    top-3 of B's BGE-M3 search, dated events only
    {M}_state_profile_with_embedding_fulldoc_{own,mismatched}  top-3 of B's BGE-M3 search, in full (documents + events)
  LLM, earlier (reused)
    {M}_state                       no examiner block (October)
    {M}_state_history_own           paths of the old TF-IDF top-3 (2026-11-05), for the old-vs-new search check
  no LLM
    emb_top3_math_{own,mismatched}  top-3 average: math on the 3 past applications of the new search (topk_math.py)
    prior_own                       full-history numbers: the statistics card's numbers blended with the art-unit pool
    history_math_own                the same math as the top-3 average, on the old TF-IDF top-3 (2026-11-05)
    km                              plain average
Paired differences: 1,000 paired bootstraps, seed 20261010, on the cases where both methods answered.
Copy check: how often the LLM's days equal a number it can read or work out from its block: the card's median days
(card runs) or the top-3 average's days (paths and fulldoc runs).
Writes metrics/D/profile_with_embedding_metrics.json, results/profile_with_embedding_table.csv,
results/profile_with_embedding_copy_check.csv.
"""
import argparse, json, os, re, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from traj_common import GRID_DAYS, HORIZON_DAYS, load_gold, load_predictions, surv_array  # noqa
from score_rounds_next import cindex  # noqa

SEED = 20261010
METRICS = ["disp_c_index", "disp_ibs", "rounds_mae", "rounds_acc", "next_c_index", "next_mae_days"]
PWE = "{m}_state_profile_with_embedding_{k}_{v}"


def names(m):
    """Every method in the table, in display order."""
    return (["km", "prior_own", "emb_top3_math_own", "emb_top3_math_mismatched", "history_math_own",
             f"{m}_state", f"{m}_state_history_own"]
            + [PWE.format(m=m, k=k, v=v) for k in ["card", "paths", "fulldoc"] for v in ["own", "mismatched"]])


def comparisons(m):
    """Fixed before the run (profile_with_embedding_protocol.md section 7)."""
    f = lambda k, v: PWE.format(m=m, k=k, v=v)  # noqa
    card = f("card", "own")
    return [
        # A. the standard RAG run: the 3 most similar past applications in full
        (f("fulldoc", "own"), f"{m}_state", "A1: does the full RAG help the LLM?"),
        (f("fulldoc", "own"), f("fulldoc", "mismatched"), "A2: is it about this examiner?"),
        (f("fulldoc", "own"), "emb_top3_math_own", "A3 (main): does the LLM beat the top-3 average of the same 3 applications?"),
        (f("fulldoc", "own"), f("paths", "own"), "A4: do the documents add anything beyond the dated events?"),
        (f("fulldoc", "own"), card, "A5: full RAG vs the statistics card"),
        # B. the 3 most similar past applications as dated events only
        (f("paths", "own"), f("paths", "mismatched"), "B1: paths, is it about this examiner?"),
        (f("paths", "own"), "emb_top3_math_own", "B2: paths, LLM vs the top-3 average of the same 3"),
        (f("paths", "own"), card, "B3: paths vs the statistics card"),
        (f("paths", "own"), f"{m}_state_history_own", "B4: paths, new search vs old TF-IDF search"),
        # C. the statistics card (the examiner's full history)
        (card, f"{m}_state", "C1: does the statistics card help the LLM?"),
        (card, f("card", "mismatched"), "C2: card, is it about this examiner?"),
        (card, "prior_own", "C3: card, does the LLM add anything beyond the card's numbers (no LLM)?"),
        # N. no LLM
        ("emb_top3_math_own", "prior_own", "N1: top-3 average vs the examiner's full-history numbers"),
        ("emb_top3_math_own", "emb_top3_math_mismatched", "N2: top-3 average, is it about this examiner?"),
        ("emb_top3_math_own", "history_math_own", "N3: top-3 average, new search vs old TF-IDF search"),
    ]


class Scorer:
    def __init__(self, root, n_boot):
        self.R, self.n_boot = root, n_boot
        G = load_gold(root)
        self.Ge = G[G.eligible == True].set_index("sample_id")  # noqa
        self.GR = pd.read_csv(os.path.join(root, "gold", "rounds_next_gold.csv"), dtype={"sample_id": str}).set_index("sample_id")
        self.ids = list(self.Ge.index)
        from sksurv.metrics import concordance_index_ipcw, integrated_brier_score
        self.cidx, self.ibs = concordance_index_ipcw, integrated_brier_score

    def load(self, name):
        O = os.path.join(self.R, "outputs", "D")
        ft, fr = os.path.join(O, f"trajectory_predictions_{name}.jsonl"), os.path.join(O, f"rounds_next_predictions_{name}.jsonl")
        if not (os.path.exists(ft) and os.path.exists(fr)):
            return None
        return ({r["sample_id"]: r for r in load_predictions(ft) if r.get("status") == "ok"},
                {r["sample_id"]: r for r in load_predictions(fr) if r.get("status") == "ok"})

    def dm(self, y, S):
        return (float(self.cidx(y, y, 1 - S[:, -1], tau=HORIZON_DAYS)[0]), float(self.ibs(y, y, S, GRID_DAYS)))

    def metrics(self, run, ids=None):
        T, Q = run
        ids = ids or self.ids
        it, iq = [s for s in ids if s in T], [s for s in ids if s in Q]
        res = dict(n_disp=len(it), n_rn=len(iq))
        if len(it) >= 5:
            y = surv_array(self.Ge.loc[it].reset_index())
            res["disp_c_index"], res["disp_ibs"] = self.dm(y, np.array([T[s]["S"] for s in it], float))
        if len(iq) >= 5:
            yr = self.GR.loc[iq, "rounds"].astype(int).values
            yt = self.GR.loc[iq, "next_days"].astype(float).values
            rp = np.array([int(Q[s]["rounds_pred"]) for s in iq])
            nd = np.array([float(Q[s]["next_days_pred"]) for s in iq])
            nr = np.array([float(Q[s].get("next_risk", -Q[s]["next_days_pred"])) for s in iq])
            res.update(rounds_mae=float(np.abs(rp - yr).mean()), rounds_acc=float((rp == yr).mean()),
                       next_mae_days=float(np.abs(nd - yt).mean()),
                       next_c_index=cindex(yt, np.ones(len(yt), bool), nr) if np.ptp(nr) > 0 else 0.5)
        return res

    def paired(self, ra, rb):
        (Ta, Qa), (Tb, Qb) = ra, rb
        it = [s for s in self.ids if s in Ta and s in Tb]
        iq = [s for s in self.ids if s in Qa and s in Qb]
        y = surv_array(self.Ge.loc[it].reset_index())
        Sa = np.array([Ta[s]["S"] for s in it], float); Sb = np.array([Tb[s]["S"] for s in it], float)
        yr = self.GR.loc[iq, "rounds"].astype(int).values; yt = self.GR.loc[iq, "next_days"].astype(float).values
        ev = np.ones(len(yt), bool)
        rpa = np.array([int(Qa[s]["rounds_pred"]) for s in iq]); rpb = np.array([int(Qb[s]["rounds_pred"]) for s in iq])
        nda = np.array([float(Qa[s]["next_days_pred"]) for s in iq]); ndb = np.array([float(Qb[s]["next_days_pred"]) for s in iq])
        nra = np.array([float(Qa[s].get("next_risk", -Qa[s]["next_days_pred"])) for s in iq])
        nrb = np.array([float(Qb[s].get("next_risk", -Qb[s]["next_days_pred"])) for s in iq])
        ca, ia = self.dm(y, Sa); cb, ib = self.dm(y, Sb)
        point = dict(disp_c_index=ca - cb, disp_ibs=ia - ib,
                     rounds_mae=np.abs(rpa - yr).mean() - np.abs(rpb - yr).mean(),
                     rounds_acc=(rpa == yr).mean() - (rpb == yr).mean(),
                     next_c_index=cindex(yt, ev, nra) - cindex(yt, ev, nrb),
                     next_mae_days=np.abs(nda - yt).mean() - np.abs(ndb - yt).mean())
        rng = np.random.default_rng(SEED)
        dd = {m: [] for m in METRICS}
        for _ in range(self.n_boot):
            i1 = rng.integers(0, len(it), len(it))
            yb = y[i1]
            if yb["event"].sum() >= 2 and yb["time"].min() < GRID_DAYS[0] and yb["time"].max() > GRID_DAYS[-1]:
                try:
                    c1, b1 = self.dm(yb, Sa[i1]); c2, b2 = self.dm(yb, Sb[i1])
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
            out[m] = dict(delta=float(point[m]), ci95=ci, n_boot=len(v), clear=bool(ci and (ci[0] > 0 or ci[1] < 0)))
        out["n_disp"], out["n_rn"] = len(it), len(iq)
        return out


def card_medians(blocks_file):
    """The median days printed on each statistics card: {(sample_id, own|mismatched): days}."""
    out = {}
    for x in open(blocks_file, encoding="utf-8"):
        b = json.loads(x)
        mm = re.search(r"Days from a reply to the next letter: median (\d+)", b["card_text"])
        if mm:
            out[(b["sample_id"], b["variant"])] = float(mm.group(1))
    return out


def copy_check(sc, runs, m, card_med):
    """Does the LLM write down a number it can read or work out from its block?"""
    rows = []
    for v in ["own", "mismatched"]:
        math = runs.get(f"emb_top3_math_{v}")
        for kind in ["card", "paths", "fulldoc"]:
            name = PWE.format(m=m, k=kind, v=v)
            if name not in runs:
                continue
            Q = runs[name][1]
            if kind == "card":
                ref, shown = {s: card_med[(s, v)] for s in Q if (s, v) in card_med}, "card median days"
            else:
                ref = {s: math[1][s]["next_days_pred"] for s in Q if math and s in math[1]}
                shown = f"emb_top3_math_{v} days"
            ids = list(ref)
            d = pd.DataFrame(dict(llm=[Q[s]["next_days_pred"] for s in ids], ref=[ref[s] for s in ids],
                                  true=[sc.GR.loc[s, "next_days"] for s in ids]))
            rows.append(dict(method=name, compared_with=shown, n=len(d),
                             days_exactly_equal=round(float((d.llm == d.ref).mean()), 3),
                             days_within_3=round(float(((d.llm - d.ref).abs() <= 3).mean()), 3),
                             days_rank_corr_with_ref=round(float(d.llm.corr(d.ref, method="spearman")), 3),
                             days_rank_corr_with_truth=round(float(d.llm.corr(d.true, method="spearman")), 3)))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--model", default="gpt-5-mini")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--blocks", default=None, help="default: <root>/inputs/examiner_blocks_emb_v1.jsonl")
    a = ap.parse_args()
    R, m = a.root, a.model
    sc = Scorer(R, a.n_boot)
    want = names(m)
    runs = {n: r for n in want if (r := sc.load(n)) is not None}
    print("found:", ", ".join(runs))
    miss = [n for n in want if n not in runs]
    if miss:
        print("not found yet (skipped):", ", ".join(miss))
    scores = {n: sc.metrics(r) for n, r in runs.items()}
    pair = {}
    for x, b, why in comparisons(m):
        if x in runs and b in runs:
            pair[f"{x}_vs_{b}"] = dict(question=why, **sc.paired(runs[x], runs[b]))
    cc = copy_check(sc, runs, m, card_medians(a.blocks or os.path.join(R, "inputs", "examiner_blocks_emb_v1.jsonl")))
    os.makedirs(os.path.join(R, "metrics", "D"), exist_ok=True); os.makedirs(os.path.join(R, "results"), exist_ok=True)
    json.dump(dict(note="profile_with_embedding, test_core 100; delta = first minus second on the same cases; C-index / "
                        "accuracy higher is better, IBS / MAE lower is better; clear = 95% CI excludes 0",
                   seed=SEED, n_boot=a.n_boot, scores=scores, paired=pair, copy_check=cc.to_dict(orient="records")),
              open(os.path.join(R, "metrics", "D", "profile_with_embedding_metrics.json"), "w"), indent=1)
    tab = pd.DataFrame([dict(method=n, **scores[n]) for n in want if n in scores])
    tab.to_csv(os.path.join(R, "results", "profile_with_embedding_table.csv"), index=False)
    cc.to_csv(os.path.join(R, "results", "profile_with_embedding_copy_check.csv"), index=False)
    pd.set_option("display.width", 240)
    print(tab.round(3).to_string(index=False))
    for k, v in pair.items():
        print(f"\n{v['question']}\n  {k}  n={v['n_disp']}/{v['n_rn']}")
        for mt in METRICS:
            x = v[mt]
            ci = f"[{x['ci95'][0]:+.3f}, {x['ci95'][1]:+.3f}]" if x["ci95"] else "n/a"
            print(f"   {mt:<14} {x['delta']:+.3f} {ci}{'  clear' if x['clear'] else ''}")
    if len(cc):
        print("\nCopy check (Time to Next Action days)")
        print(cc.to_string(index=False))


if __name__ == "__main__":
    main()
