"""App-level (cluster) bootstrap 95% intervals for A's Claim and Edit scores on the 10 gold apps.

Resamples the 10 applications with replacement (10,000 draws, seed 20261011) and recomputes
  Claim = claim-version accuracy over claim records (outputs/state_scores_per_record.csv), per cutoff;
  Edit  = micro P/R/F1 over limitation units (response_metrics.json -> edit_gold.per_app).
Percentile intervals. Writes results/A_bootstrap_ci.json. No API calls.

  python3 a_state_response/scripts/bootstrap_ci.py
"""
import csv
import json
import random
from pathlib import Path

A = Path(__file__).resolve().parent.parent
B, SEED = 10000, 20261011
rows = list(csv.DictReader(open(A / "outputs" / "state_scores_per_record.csv")))
apps = sorted({r["app_id"] for r in rows})
edit = json.loads((A / "response_metrics.json").read_text())["edit_gold"]["per_app"]


def interval(stat):
    rng = random.Random(SEED)
    v = sorted(stat([rng.choice(apps) for _ in apps]) for _ in range(B))
    return [round(v[int(0.025 * B)], 3), round(v[int(0.975 * B) - 1], 3)]


out = {"method": f"app-level bootstrap, {B} draws, seed {SEED}, percentile 95% interval", "n_apps": len(apps)}
for st in ("O1_cutoff", "A1_cutoff"):
    by = {a: [r["correct"] == "True" for r in rows if r["app_id"] == a and r["stage"] == st] for a in apps}
    f = lambda s, by=by: sum(sum(by[a]) for a in s) / sum(len(by[a]) for a in s)
    out[f"claim_{st}"] = {"value": round(f(apps), 4), "ci95": interval(f)}


def prf(s):
    tp = sum(edit[a]["tp"] for a in s); p = sum(edit[a]["pred_units"] for a in s); g = sum(edit[a]["ref_units"] for a in s)
    P = tp / p if p else 0.0; R = tp / g if g else 0.0
    return P, R, (2 * P * R / (P + R) if P + R else 0.0)


for i, k in enumerate(("precision", "recall", "f1")):
    out[f"edit_{k}"] = {"value": round(prf(apps)[i], 4), "ci95": interval(lambda s, i=i: prf(s)[i])}

(A / "results").mkdir(exist_ok=True)
(A / "results" / "A_bootstrap_ci.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out, indent=1))
