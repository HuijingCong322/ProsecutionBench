"""Score every trajectory prediction file and write metrics/D/trajectory_metrics.json (+ a per-method CSV).

Usage: python score_trajectory.py --root path/to/D_trajectory [--which core|test300]
Scores every outputs/D/trajectory_predictions_*.jsonl that matches the chosen test set.
"""
import argparse, glob, json, os
import pandas as pd
import sksurv
from traj_common import load_gold, load_predictions, load_train, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--which", default="core", choices=["core", "test300"])
    a = ap.parse_args()
    R = a.root
    G, TR = load_gold(R, a.which), load_train(R)
    files = sorted(glob.glob(os.path.join(R, "outputs", "D", "trajectory_predictions_*.jsonl")))
    files = [f for f in files if (f.endswith("_test300.jsonl")) == (a.which == "test300")]
    results = []
    for f in files:
        recs = load_predictions(f)
        if not recs:
            continue
        r = score(recs, G, TR)
        r["predictions_file"] = os.path.relpath(f, R)
        results.append(r)
        print(f"{r['method']:<28} scored {r['scored_n']}/{r['eligible_n']}  "
              f"C-idx {r.get('c_index')}  IBS {r.get('ibs')}")
    os.makedirs(os.path.join(R, "metrics", "D"), exist_ok=True)
    suffix = "" if a.which == "core" else "_test300"
    meta = dict(test_set="test_core (100)" if a.which == "core" else "test (300, optional extension)",
                endpoint="time from A1 filing (cutoff) to the first mailed Notice of Allowance or mailed abandonment notice",
                metric_notes=dict(
                    c_index="IPCW concordance (sksurv concordance_index_ipcw), tau = 730 days, risk = 1 - S(730)",
                    ibs="integrated Brier score over the frozen monthly grid (months 1..24)",
                    primary_censoring_weights="from the evaluation labels; test_core has no censored case, so all weights are 1",
                    sensitivity_suffix_trainG="censoring weights estimated from training labels censored at 2013-12-31"),
                scikit_survival_version=sksurv.__version__)
    with open(os.path.join(R, "metrics", "D", f"trajectory_metrics{suffix}.json"), "w") as f:
        json.dump(dict(meta, results=results), f, indent=1)
    flat = pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in results])
    flat.to_csv(os.path.join(R, "metrics", "D", f"trajectory_metrics{suffix}.csv"), index=False)


if __name__ == "__main__":
    main()
