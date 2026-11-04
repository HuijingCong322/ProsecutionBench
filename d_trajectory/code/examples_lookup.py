"""Addendum A baseline (no LLM): copy the numbers that are visible in the examples-only profile.

    python examples_lookup.py --root path/to/D_trajectory --pkg path/to/B_D_C_phase1_v4_reviewed

The examples-only profile still shows, for each retrieved past case, "N days after reply". A model could copy those.
This baseline does exactly that, so an LLM given examples only has to beat it to show it does more than copy:
    Next action   median of the retrieved examples' days (k = 2: mean of the two, rounded); no example -> KM's days
    Disposition   KM curves (the examples show no 12/24-month outcome to copy)
    Rounds        KM (the examples show no round counts to copy)
Writes outputs/D/{trajectory,rounds_next}_predictions_exlookup_{own,mismatched}.jsonl
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import profile_inject as pi  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--pkg", required=True)
    a = ap.parse_args()
    O = os.path.join(a.root, "outputs", "D")
    km_t = [json.loads(x) for x in open(os.path.join(O, "trajectory_predictions_km.jsonl"))]
    km_r = {r["sample_id"]: r for r in map(json.loads, open(os.path.join(O, "rounds_next_predictions_km.jsonl")))}
    for v in ["own", "mismatched"]:
        P, info = pi.load_profiles(a.pkg, v, "examples_only")
        name = f"exlookup_{v}"
        with open(os.path.join(O, f"trajectory_predictions_{name}.jsonl"), "w") as f:
            for r in km_t:
                r2 = dict(r, method=f"examples_lookup_{v}", model="none (copy example days)",
                          input_setting=f"{v} examples-only profile, KM curves")
                f.write(json.dumps(r2) + "\n")
        n_used = 0
        with open(os.path.join(O, f"rounds_next_predictions_{name}.jsonl"), "w") as f:
            for sid, r in km_r.items():
                days = P[sid]["example_days"] if sid in P else []
                d = float(round(np.median(days))) if days else float(r["next_days_pred"])
                n_used += bool(days)
                r2 = dict(r, method=f"examples_lookup_{v}", model="none (copy example days)",
                          input_setting=f"{v} examples-only profile", next_days_pred=d, next_risk=-d,
                          example_days=days, retrieved_k=len(days))
                f.write(json.dumps(r2) + "\n")
        print(f"{name}: next action from example days in {n_used}/{len(km_r)} cases, KM otherwise")


if __name__ == "__main__":
    main()
