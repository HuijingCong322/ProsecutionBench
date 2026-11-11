"""Build the shareable package data_v1_share/ (upload this folder to Drive).
Contains: README.md, labels.csv, splits.json, sample_manifest.csv, examples/, and per application
apps/<app>/{text/, rounds.json, catalog.csv, transactions.csv, doc_sources.csv}. Raw API JSON, XML,
PDFs and publications stay in data_v1/ (not needed for experiments).
sample_manifest.csv: one row per example with the A1-cutoff input document ids, the ids whose text is
missing, and input_hash (sha1 over the input texts) so everyone can check they use identical inputs."""
import csv, hashlib, json, shutil
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data_v1"
OUT = D.parent / "data_v1_share"
(OUT / "examples").mkdir(parents=True, exist_ok=True)   # files are overwritten in place
rows = []
for f in sorted((D / "examples").glob("*.json")):
    e = json.loads(f.read_text())
    app = e["app_id"]
    shutil.copy(f, OUT / "examples" / f.name)
    dst = OUT / "apps" / app
    dst.mkdir(parents=True, exist_ok=True)
    if (D / "apps" / app / "text").exists():
        shutil.copytree(D / "apps" / app / "text", dst / "text", dirs_exist_ok=True)
    for n in ("rounds.json", "catalog.csv", "transactions.csv", "doc_sources.csv"):
        if (D / "apps" / app / n).exists():
            shutil.copy(D / "apps" / app / n, dst / n)
    h = hashlib.sha1()
    missing = []
    for x in e["inputs"]:
        p = D / x["text_path"] if x["text_path"] else None
        if p and p.exists():
            h.update(x["doc_id"].encode()); h.update(p.read_bytes())
        else:
            missing.append(x["doc_id"])
    rows.append({"sample_id": f"{app}_t1", "app_id": app, "family_id": e["family_id"], "split": e["split"],
                 "test_core": e.get("test_core"), "gen_core": e.get("gen_core"), "gen_subset": e["gen_subset"], "gold_subset": e.get("gold_subset"), "stage": "t1_A1_cutoff", "cutoff": e["cutoff"],
                 "o1_mail_date": e["o1"]["mail_date"], "tc": e["tc"], "examiner_id": e["examiner_id"],
                 "input_doc_ids": ";".join(x["doc_id"] for x in e["inputs"]),
                 "missing_doc_ids": ";".join(missing), "input_hash": h.hexdigest()[:16],
                 "n_inputs_ocr": sum(x["source"] == "ocr" for x in e["inputs"]),
                 "target_doc_id": (e["target"] or {}).get("doc_id", ""),
                 "target_has_text": bool((e["target"] or {}).get("text_path"))})
with open(OUT / "sample_manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
for n in ("README.md", "labels.csv", "splits.json", "gold_subset.csv"):
    shutil.copy(D / n, OUT / n)
from collections import Counter
print("examples:", len(rows), dict(Counter(r["split"] for r in rows)))
print("test with missing input text:", sum(1 for r in rows if r["split"] == "test" and r["missing_doc_ids"]),
      "| test target without text:", sum(1 for r in rows if r["split"] == "test" and not r["target_has_text"]))
