"""Paired comparison of two trajectory prediction files on the SAME cases (both models answered validly).

Writes metrics/D/paired_<a>_vs_<b>.json with C-idx / IBS for each model on the shared cases and the
difference (a minus b) with a 95% bootstrap interval (same resampled cases for both models, seed 20261010).
For C-idx higher is better; for IBS lower is better.

Usage:
  python compare_trajectory_models.py --root .. \
      --a outputs/D/trajectory_predictions_qwen3.6-27b_state.jsonl \
      --b outputs/D/trajectory_predictions_gpt-5-mini_state.jsonl
"""
import argparse, json, os
import numpy as np
from traj_common import GRID_DAYS, HORIZON_DAYS, load_gold, load_predictions, surv_array


def metrics(y, S):
    from sksurv.metrics import concordance_index_ipcw, integrated_brier_score
    risk = 1.0 - S[:, -1]
    return (float(concordance_index_ipcw(y, y, risk, tau=HORIZON_DAYS)[0]),
            float(integrated_brier_score(y, y, S, GRID_DAYS)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    x = ap.parse_args()
    G = load_gold(x.root)
    G = G[G.eligible == True].set_index("sample_id")
    PA = {r["sample_id"]: r for r in load_predictions(os.path.join(x.root, x.a))}
    PB = {r["sample_id"]: r for r in load_predictions(os.path.join(x.root, x.b))}
    shared = [s for s in G.index if PA.get(s, {}).get("status") == "ok" and PB.get(s, {}).get("status") == "ok"]
    sub = G.loc[shared].reset_index()
    y = surv_array(sub)
    SA = np.array([PA[s]["S"] for s in shared], float)
    SB = np.array([PB[s]["S"] for s in shared], float)
    ca, ia = metrics(y, SA)
    cb, ib = metrics(y, SB)
    rng = np.random.default_rng(20261010)
    dc, di = [], []
    for _ in range(x.n_boot):
        idx = rng.integers(0, len(sub), len(sub))
        yb = y[idx]
        if yb["event"].sum() < 2 or yb["time"].min() >= GRID_DAYS[0] or yb["time"].max() <= GRID_DAYS[-1]:
            continue
        try:
            a_c, a_i = metrics(yb, SA[idx])
            b_c, b_i = metrics(yb, SB[idx])
        except Exception:  # noqa
            continue
        dc.append(a_c - b_c); di.append(a_i - b_i)
    name = lambda p, P: f"{next(iter(P.values())).get('model')} ({next(iter(P.values())).get('input_setting')})"
    out = dict(a=x.a, b=x.b, a_label=name(x.a, PA), b_label=name(x.b, PB), eligible_n=int(len(G)),
               shared_n=len(shared),
               a_only_failed=[s for s in G.index if PA.get(s, {}).get("status") != "ok"],
               b_only_failed=[s for s in G.index if PB.get(s, {}).get("status") != "ok"],
               c_index_a=ca, c_index_b=cb, ibs_a=ia, ibs_b=ib,
               delta_c_index=ca - cb, delta_c_index_ci95=[float(np.percentile(dc, 2.5)), float(np.percentile(dc, 97.5))],
               delta_ibs=ia - ib, delta_ibs_ci95=[float(np.percentile(di, 2.5)), float(np.percentile(di, 97.5))],
               n_boot_used=len(dc), note="delta = a minus b on shared valid cases; C-idx higher is better, IBS lower is better")
    os.makedirs(os.path.join(x.root, "metrics", "D"), exist_ok=True)
    stem = lambda p: os.path.basename(p).replace("trajectory_predictions_", "").replace(".jsonl", "")
    path = os.path.join(x.root, "metrics", "D", f"paired_{stem(x.a)}_vs_{stem(x.b)}.json")
    json.dump(out, open(path, "w"), indent=1)
    print(f"{out['a_label']} vs {out['b_label']} on {len(shared)}/{len(G)} shared cases")
    print(f"  C-idx {ca:.3f} vs {cb:.3f}   diff {ca - cb:+.3f}  95% CI [{out['delta_c_index_ci95'][0]:+.3f}, {out['delta_c_index_ci95'][1]:+.3f}]")
    print(f"  IBS   {ia:.3f} vs {ib:.3f}   diff {ia - ib:+.3f}  95% CI [{out['delta_ibs_ci95'][0]:+.3f}, {out['delta_ibs_ci95'][1]:+.3f}]")
    print("wrote", path)


if __name__ == "__main__":
    main()
