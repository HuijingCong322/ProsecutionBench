"""Per app/stage failure breakdown of a scored prediction file (reads outputs/state_scores_per_record.csv)."""
import csv, sys
from collections import defaultdict, Counter
rows = list(csv.DictReader(open(sys.argv[1] if len(sys.argv) > 1 else "A/outputs/state_scores_per_record.csv")))
agg = defaultdict(Counter)
for r in rows:
    k = (r["app_id"], r["stage"], r["list"])
    agg[k]["n"] += 1
    if r["found"] != "True": agg[k]["missing"] += 1; continue
    if r["version_ok"] != "True": agg[k]["version"] += 1
    if r["status_ok"] != "True": agg[k]["status"] += 1
    if r["text_ok"] != "True": agg[k]["text"] += 1
    if r["correct"] == "True": agg[k]["ok"] += 1
tot = Counter()
for k in sorted(agg):
    c = agg[k]; tot.update(c)
    if c["ok"] < c["n"]:
        print(*k, dict(c))
print("TOTAL", dict(tot))
