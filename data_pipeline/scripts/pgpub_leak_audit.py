"""Audit: PGPUB used as 'application as filed' input, but published after the O1/A1 cutoff,
possibly carrying amended claims. Read-only; writes data_v1/pgpub_leak_audit.csv."""
import json, re, csv, sys
from pathlib import Path
sys.path.insert(0, "scripts")
rows = []
for f in sorted(Path("data_v1/examples").glob("*.json")):
    e = json.load(open(f)); app = e["app_id"]; d = Path("data_v1/apps") / app
    if not any(i["doc_id"] == "pgpub_claims" for i in e["inputs"]): continue
    x = (d / "pub" / "pgpub.xml").read_text(errors="replace") if (d / "pub" / "pgpub.xml").exists() else ""
    m = re.search(r"<publication-reference>.*?<date>(\d{8})</date>", x, re.S)
    pd = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ""
    pc = json.load(open(d / "text" / "pgpub_claims.json")) if (d / "text" / "pgpub_claims.json").exists() else []
    # as-filed claim count from the filed CLM text (numbered lines) if present
    filed = [i for i in sorted((d / "text").glob("*_CLM_*.txt")) if i.name[:10] <= e["filing_date"][:10] or i.name[:10] == sorted((d / "text").glob("*_CLM_*.txt"))[0].name[:10]]
    nf = None
    if filed:
        t = filed[0].read_text()
        nums = [int(n) for n in re.findall(r"(?m)^\s*(\d{1,3})\s*\.", t)]
        nf = max(nums) if nums else None
    pm = re.search(r"Pub\.? No|amend", "")
    rows.append(dict(app_id=app, split=e["split"], test_core=e["test_core"], gold=e["gold_subset"], filing=e["filing_date"],
                     o1=e["o1"]["mail_date"], cutoff=e["cutoff"], pgpub_date=pd,
                     after_o1=bool(pd and e["o1"].get("mail_date") and pd > e["o1"]["mail_date"]), after_cutoff=bool(pd and pd > e["cutoff"]),
                     n_pgpub_claims=len(pc), n_filed_claims=nf, claims_differ=(nf is not None and nf != len(pc))))
w = csv.DictWriter(open("data_v1/pgpub_leak_audit.csv", "w"), fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
from collections import Counter
print("examples with pgpub input", len(rows))
print("pgpub after O1:", sum(r["after_o1"] for r in rows), "| after A1 cutoff:", sum(r["after_cutoff"] for r in rows))
print("after O1 & claim count != filed:", sum(r["after_o1"] and r["claims_differ"] for r in rows))
print("before O1 & claim count != filed:", sum((not r["after_o1"]) and r["claims_differ"] for r in rows))
print("by split (after_o1):", Counter(r["split"] for r in rows if r["after_o1"]))
print("test_core after_o1:", sum(r["after_o1"] and str(r["test_core"])=="True" for r in rows), "gold:", [r["app_id"] for r in rows if r["after_o1"] and str(r["gold"])=="True"])
