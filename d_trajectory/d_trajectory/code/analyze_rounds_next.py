"""Remaining Rounds + Time to Next Action: every table and graph for the report (no API calls).

Reads gold/rounds_next_gold.csv and outputs/D/rounds_next_predictions_{km,cox,gpt-5-mini[_state],qwen3.6-27b[_state]}.jsonl
Writes
  results/rounds_next_paired.csv        paired bootstrap differences (same 100 cases, 1000 draws, seed 20261010)
  results/rounds_confusion.csv          predicted vs real number of further rejections, per method
  results/rounds_by_group.csv           rounds error split by how the case ended and by RCE
  results/next_action_by_type.csv       next-letter error split by what the next letter was
  results/rounds_next_examples.csv      the worked-example cases, every method's guess
  results/rounds_p0_auroc.csv           does P(no more rejections) pick out the cases that really had 0? (AUROC)
  results/rounds_distribution.png/.pdf  real vs predicted counts, and average predicted probabilities
  results/rounds_confusion.png/.pdf     6 heat maps
  results/next_action_scatter.png/.pdf  predicted vs real days, 6 panels
Usage: python analyze_rounds_next.py --root path/to/D_trajectory
"""
import argparse, json, os
import numpy as np
import pandas as pd

RUNS = [("km", "KM"), ("cox", "Cox"), ("gpt-5-mini", "GPT-5-mini, history"), ("gpt-5-mini_state", "GPT-5-mini, state+history"),
        ("qwen3.6-27b", "Qwen3.6-27B, history"), ("qwen3.6-27b_state", "Qwen3.6-27B, state+history")]
COL = {"KM": "#8a8986", "Cox": "#52514e", "GPT-5-mini, history": "#9cc3f0", "GPT-5-mini, state+history": "#2a78d6",
       "Qwen3.6-27B, history": "#f5b08f", "Qwen3.6-27B, state+history": "#eb6834"}
BINS = ["0", "1", "2", "3", "4+"]
EXAMPLES = ["13826133", "14622198", "13752885", "13816667"]


def cidx(t, risk):
    num = den = 0.0
    tt = np.minimum(t, 730)
    for i in range(len(t)):
        if t[i] > 730:
            continue
        later = tt > tt[i]
        den += later.sum(); num += (risk[i] > risk[later]).sum() + 0.5 * (risk[i] == risk[later]).sum()
    return num / den


def metrics(y, yhat, t, d, risk):
    e = np.abs(yhat - y)
    return dict(rounds_mae=e.mean(), rounds_acc=(e == 0).mean(), next_c=cidx(t, risk), next_mae=np.abs(d - t).mean())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); R = ap.parse_args().root
    G = pd.read_csv(os.path.join(R, "gold", "rounds_next_gold.csv"), dtype={"sample_id": str}).set_index("sample_id")
    ids = G.index.tolist()
    y = G.rounds.astype(int).values; t = G.next_days.astype(float).values
    P = {}
    for key, label in RUNS:
        f = os.path.join(R, "outputs", "D", f"rounds_next_predictions_{key}.jsonl")
        if not os.path.exists(f):
            print("missing", f); continue
        rec = {r["sample_id"]: r for r in map(json.loads, open(f)) if r.get("status") == "ok"}
        if not all(s in rec for s in ids):
            print("not all cases ok in", f, len(rec)); continue
        P[label] = dict(yhat=np.array([int(rec[s]["rounds_pred"]) for s in ids]),
                        p=np.array([rec[s].get("p_rounds") for s in ids], float),
                        d=np.array([float(rec[s]["next_days_pred"]) for s in ids]),
                        risk=np.array([float(rec[s].get("next_risk", -rec[s]["next_days_pred"])) for s in ids]),
                        why={s: rec[s].get("rationale", "") for s in ids})
    os.makedirs(os.path.join(R, "results"), exist_ok=True)

    # ---------------- paired bootstrap
    pairs = [("Qwen3.6-27B, state+history", "GPT-5-mini, state+history"), ("Qwen3.6-27B, history", "GPT-5-mini, history"),
             ("GPT-5-mini, state+history", "GPT-5-mini, history"), ("Qwen3.6-27B, state+history", "Qwen3.6-27B, history"),
             ("GPT-5-mini, history", "KM"), ("GPT-5-mini, state+history", "KM"), ("Qwen3.6-27B, history", "KM"),
             ("Qwen3.6-27B, state+history", "KM"), ("Cox", "KM")]
    rng = np.random.default_rng(20261010); draws = [rng.integers(0, len(ids), len(ids)) for _ in range(1000)]
    rows = []
    for a, b in pairs:
        if a not in P or b not in P:
            continue
        A, B = P[a], P[b]
        base = {k: metrics(y, A["yhat"], t, A["d"], A["risk"])[k] - metrics(y, B["yhat"], t, B["d"], B["risk"])[k]
                for k in ("rounds_mae", "rounds_acc", "next_c", "next_mae")}
        bs = {k: [] for k in base}
        for i in draws:
            ma = metrics(y[i], A["yhat"][i], t[i], A["d"][i], A["risk"][i]); mb = metrics(y[i], B["yhat"][i], t[i], B["d"][i], B["risk"][i])
            for k in bs:
                bs[k].append(ma[k] - mb[k])
        row = dict(a=a, b=b)
        for k in base:
            lo, hi = np.percentile(bs[k], [2.5, 97.5])
            row.update({f"{k}_diff": base[k], f"{k}_lo": lo, f"{k}_hi": hi, f"{k}_clear": bool(lo > 0 or hi < 0)})
        rows.append(row)
    PD = pd.DataFrame(rows); PD.to_csv(os.path.join(R, "results", "rounds_next_paired.csv"), index=False)

    # ---------------- confusion, groups, types, examples
    cap = lambda v: np.minimum(v, 4)
    conf = []
    for label, X in P.items():
        for tr in range(5):
            for pr in range(5):
                conf.append(dict(method=label, real=BINS[tr], predicted=BINS[pr], n=int(((cap(y) == tr) & (cap(X["yhat"]) == pr)).sum())))
    pd.DataFrame(conf).to_csv(os.path.join(R, "results", "rounds_confusion.csv"), index=False)

    groups = {"allowed": (G.disposition == "allowance").values, "abandoned": (G.disposition == "abandonment").values,
              "no RCE": (G.rces == 0).values, "1+ RCE": (G.rces > 0).values, "all": np.ones(len(ids), bool)}
    gr = []
    for gname, m in groups.items():
        row = dict(group=gname, n=int(m.sum()), real_mean=float(y[m].mean()))
        for label, X in P.items():
            row[f"{label} | mean guess"] = float(X["yhat"][m].mean()); row[f"{label} | MAE"] = float(np.abs(X["yhat"][m] - y[m]).mean())
        gr.append(row)
    pd.DataFrame(gr).to_csv(os.path.join(R, "results", "rounds_by_group.csv"), index=False)

    ty = []
    for nt in ["final_rejection", "allowance", "other"]:
        m = (G.next_type == nt).values if nt != "other" else ~G.next_type.isin(["final_rejection", "allowance"]).values
        row = dict(next_letter=nt, n=int(m.sum()), real_median_days=float(np.median(t[m])))
        for label, X in P.items():
            row[f"{label} | median guess"] = float(np.median(X["d"][m])); row[f"{label} | MAE"] = float(np.abs(X["d"][m] - t[m]).mean())
        ty.append(row)
    pd.DataFrame(ty).to_csv(os.path.join(R, "results", "next_action_by_type.csv"), index=False)

    ex = []
    for s in EXAMPLES:
        if s not in G.index:
            continue
        i = ids.index(s)
        row = dict(sample_id=s, real_rounds=int(y[i]), real_next_days=float(t[i]), real_next=G.loc[s, "next_type"],
                   ended=G.loc[s, "disposition"])
        for label, X in P.items():
            row[f"{label} | rounds"] = int(X["yhat"][i]); row[f"{label} | days"] = float(X["d"][i])
            if label.startswith(("GPT", "Qwen")):
                row[f"{label} | p(0..4+)"] = "/".join(f"{v:.2f}" for v in X["p"][i]); row[f"{label} | why"] = X["why"][s]
        ex.append(row)
    pd.DataFrame(ex).to_csv(os.path.join(R, "results", "rounds_next_examples.csv"), index=False)

    # does P(no more rejections) pick out the cases that really had 0? (AUROC, 1000 case bootstraps)
    def au(v, yy):
        pos, neg = v[yy], v[~yy]
        return ((pos[:, None] > neg).sum() + 0.5 * (pos[:, None] == neg).sum()) / (len(pos) * len(neg))
    yy = y == 0; a0 = []
    for label, X in P.items():
        v = X["p"][:, 0]; bs = []
        for i in draws:
            if yy[i].all() or (~yy[i]).all():
                continue
            bs.append(au(v[i], yy[i]))
        lo, hi = np.percentile(bs, [2.5, 97.5])
        a0.append(dict(method=label, auroc_p0=au(v, yy), lo=lo, hi=hi, mean_p0_real0=v[yy].mean(),
                       mean_p0_real1=v[y == 1].mean(), mean_p0_real2plus=v[y >= 2].mean()))
    pd.DataFrame(a0).to_csv(os.path.join(R, "results", "rounds_p0_auroc.csv"), index=False)

    # ---------------- figures
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    labels = list(P)
    # 1. distribution
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2)); w = 0.8 / (len(labels) + 1); x = np.arange(5)
    real = [np.mean(cap(y) == k) for k in range(5)]
    for k, a in enumerate(ax):
        a.bar(x - 0.4 + w / 2, real, w, color="#0b0b0b", label="real")
        for j, lab in enumerate(labels):
            v = [np.mean(cap(P[lab]["yhat"]) == q) for q in range(5)] if k == 0 else P[lab]["p"].mean(0)
            a.bar(x - 0.4 + w * (j + 1.5), v, w, color=COL[lab], label=lab)
        a.set_xticks(x); a.set_xticklabels(BINS); a.set_xlabel("further rejections before the case ends")
        a.set_ylabel("share of the 100 cases" if k == 0 else "average predicted probability")
        a.set_title("Point guesses vs real" if k == 0 else "Average predicted probability vs real share")
    ax[1].legend(fontsize=7.5, frameon=False); fig.tight_layout()
    for e in ("png", "pdf"):
        fig.savefig(os.path.join(R, "results", f"rounds_distribution.{e}"), dpi=200)
    # 2. confusion
    fig, ax = plt.subplots(1, len(labels), figsize=(2.6 * len(labels), 2.9))
    for a, lab in zip(np.atleast_1d(ax), labels):
        M = np.zeros((5, 5), int)
        for tr, pr in zip(cap(y), cap(P[lab]["yhat"])):
            M[tr, pr] += 1
        a.imshow(M, cmap="Blues", vmin=0, vmax=max(40, M.max()))
        for i in range(5):
            for j in range(5):
                if M[i, j]:
                    a.text(j, i, M[i, j], ha="center", va="center", fontsize=8, color="white" if M[i, j] > 25 else "#0b0b0b")
        a.set_xticks(range(5)); a.set_xticklabels(BINS); a.set_yticks(range(5)); a.set_yticklabels(BINS)
        a.set_xlabel("guessed"); a.set_title(lab, fontsize=8)
    np.atleast_1d(ax)[0].set_ylabel("real")
    fig.tight_layout()
    for e in ("png", "pdf"):
        fig.savefig(os.path.join(R, "results", f"rounds_confusion.{e}"), dpi=200)
    # 3. next-action scatter
    fig, ax = plt.subplots(2, 3, figsize=(11, 7), sharex=True, sharey=True)
    for a, lab in zip(ax.ravel(), labels):
        a.plot([0, 450], [0, 450], color="#0b0b0b", lw=1, ls="--")
        a.scatter(t, P[lab]["d"], s=14, color=COL[lab], alpha=0.8, edgecolor="none")
        a.set_title(f"{lab}  (MAE {np.abs(P[lab]['d'] - t).mean():.0f} days)", fontsize=8.5)
        a.set_xlim(0, 450); a.set_ylim(0, 450)
    for a in ax[1]:
        a.set_xlabel("real days to the next examiner letter")
    for a in ax[:, 0]:
        a.set_ylabel("guessed days")
    fig.tight_layout()
    for e in ("png", "pdf"):
        fig.savefig(os.path.join(R, "results", f"next_action_scatter.{e}"), dpi=200)
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(PD.round(3).to_string(index=False)); print(pd.DataFrame(gr).round(2).T.to_string()); print(pd.DataFrame(ty).round(1).T.to_string())


if __name__ == "__main__":
    main()
