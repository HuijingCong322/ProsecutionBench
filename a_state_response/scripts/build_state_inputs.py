"""Build State Tracking inputs (A, week-3 pilot) from data_v1_share.
Usage: python3 A/scripts/build_state_inputs.py [--share PATH]
Samples: dev (3 pilot apps) + gold_subset (10) at O1_cutoff and A1_cutoff; test_core (100) at A1_cutoff.
Visible documents: the example's inputs dated on or before the stage cutoff (O1 mail date / A1 filing
date). The application's description and abstract are omitted: state fields (claims, rejections) do not
come from them; they are listed in omitted_doc_ids. Claims as filed come from the PGPUB claims.
Output: A/inputs/state_inputs.jsonl, one row per (sample, stage) with the rendered input text,
doc ids, omitted/missing ids and input_hash."""
import argparse, csv, hashlib, json, re
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--share", default=str(A.parent / "data_v1_share"))
S = Path(ap.parse_args().share)

DEV = ["11968167", "11968173", "11968176"]
labels = list(csv.DictReader(open(S / "labels.csv")))
gold = [r["app_id"] for r in labels if r["gold_subset"] == "True"]
core = [r["app_id"] for r in labels if r["test_core"] == "True"]
TUNE = (A / "inputs" / "tune_apps.txt").read_text().split() if (A / "inputs" / "tune_apps.txt").exists() else []
plan = [(a, st, "dev") for a in DEV for st in ("O1_cutoff", "A1_cutoff")] + \
       [(a, st, "tune") for a in TUNE for st in ("O1_cutoff", "A1_cutoff")] + \
       [(a, st, "gold") for a in gold for st in ("O1_cutoff", "A1_cutoff")] + \
       [(a, "A1_cutoff", "test_core") for a in core if a not in gold]


def render(x):
    p = S / x["text_path"]
    if not x["text_path"] or not p.exists():
        return None
    if p.suffix == ".json":                                   # PGPUB claims
        return "\n".join(f"{c['number']}. " + re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", c["text"])
                         for c in json.loads(p.read_text()))
    return p.read_text()


out = open(A / "inputs" / "state_inputs.jsonl", "w")
n = 0
for app, stage, group in plan:
    e = json.loads((S / "examples" / f"{app}.json").read_text())
    cut = e["o1"]["mail_date"] if stage == "O1_cutoff" else e["cutoff"]
    parts, ids, omitted, missing = [], [], [], []
    for x in e["inputs"]:
        if x["date"] > cut:
            continue
        if x["doc_id"] in ("pgpub_description", "pgpub_abstract"):
            omitted.append(x["doc_id"]); continue
        t = render(x)
        if t is None:
            missing.append(x["doc_id"]); continue
        ids.append(x["doc_id"])
        role = x["role"]
        parts.append(f"=== DOC {x['doc_id']} | {x['doc_code']} | {x['date']} | role={role} | text_source={x['source']} ===\n{t.strip()}")
    text = "\n\n".join(parts)
    row = {"sample_id": f"{app}_t1", "app_id": app, "stage": stage, "group": group, "cutoff": cut,
           "o1_doc_id": e["o1"]["doc_id"], "o1_code": e["o1"]["code"],
           "a1_doc_ids": e["a1"]["doc_ids"] if stage == "A1_cutoff" else [],
           "doc_ids": ids, "omitted_doc_ids": omitted, "missing_doc_ids": missing,
           "input_hash": hashlib.sha1(text.encode()).hexdigest()[:16], "approx_tokens": len(text) // 4,
           "input_text": text}
    out.write(json.dumps(row) + "\n")
    n += 1
out.close()
from collections import Counter
rows = [json.loads(l) for l in open(A / "inputs" / "state_inputs.jsonl")]
print("rows:", n, Counter((r["group"], r["stage"]) for r in rows))
tok = sorted(r["approx_tokens"] for r in rows)
print("approx tokens p50/p90/max:", tok[len(tok) // 2], tok[int(len(tok) * .9)], tok[-1],
      "| rows with missing docs:", sum(bool(r["missing_doc_ids"]) for r in rows))
