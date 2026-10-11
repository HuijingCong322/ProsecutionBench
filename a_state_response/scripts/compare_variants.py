"""Compare prompt variants on the dev + tune cases (A). Reference = automatic state references
(gold/state_dev_auto_draft.jsonl; not human-reviewed, used only to choose a prompt).
Usage: python3 A/scripts/compare_variants.py"""
import json, subprocess, sys
from collections import defaultdict
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ref = A / "gold" / "state_dev_auto_draft.jsonl"
usage = defaultdict(lambda: [0, 0.0, 0])
for l in open(A / "logs" / "usage_log.jsonl"):
    u = json.loads(l)
    v = u.get("variant", "main")
    usage[v][0] += 1; usage[v][1] += u.get("est_cost_usd", 0); usage[v][2] += u.get("completion_tokens", 0)
rows = []
for d in sorted((A / "outputs" / "variants").glob("*/state_predictions.jsonl")):
    v = d.parent.name
    r = subprocess.run([sys.executable, str(A / "scripts" / "score_state.py"), "--gold", str(ref), "--pred", str(d)],
                       capture_output=True, text=True)
    m = json.loads((A / "state_metrics.json").read_text())
    preds = [json.loads(l) for l in open(d)]
    rows.append((v, len(preds), sum(not p["parse_ok"] for p in preds),
                 m["O1_cutoff"]["claim_version_accuracy"], m["A1_cutoff"]["claim_version_accuracy"],
                 m["A1_cutoff"]["id_found"], m["A1_cutoff"]["status_acc"], m["A1_cutoff"]["version_acc"],
                 m["all"]["claim_ground_micro_f1"], m["all"]["rejection_status_macro_f1"],
                 usage[v][1], usage[v][2] // max(1, usage[v][0])))
hdr = ("variant", "n", "fail", "Claim O1", "Claim A1", "A1 found", "A1 status", "A1 version", "grounds F1", "Rej F1",
       "cost $", "out tok/call")
print(" | ".join(hdr))
for x in rows:
    print(" | ".join(f"{y:.3f}" if isinstance(y, float) else str(y) for y in x))
