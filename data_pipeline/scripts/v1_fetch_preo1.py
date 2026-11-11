"""v1.2: download the documents added to rounds.json input_doc_ids (filed/mailed between the filing day
and O1) that have no text yet. USPTO XML when available, else PDF for OCR (mentor rule).
Rows are added to apps/<app>/doc_sources.csv (role 'input'); existing rows are kept unchanged.
Run on the Mac:  source ~/.zshrc; python3 scripts/v1_fetch_preo1.py"""
import csv, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v1_fetch as V   # noqa: E402

D = V.OUT
key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
s = V.F.requests.Session(); s.headers["X-API-KEY"] = key
log = open(D / "fetch_preo1.log", "a")
apps = json.load(open(D / "preo1_apps.json"))
tot = {}
for k, app in enumerate(apps, 1):
    d = D / "apps" / app
    rd = json.loads((d / "rounds.json").read_text())
    docs = {x.get("documentIdentifier"): x for x in json.loads((d / "raw" / "documents.json").read_text()).get("documentBag", []) or []}
    sp = d / "doc_sources.csv"
    rows = list(csv.DictReader(open(sp)))
    have = {r["doc_id"]: r for r in rows}
    for did in rd["input_doc_ids"]:
        r0 = have.get(did)
        if r0 and r0.get("source") in ("xml", "pdf_ocr", "not_needed", "pgpub"):
            continue
        x = docs.get(did)
        if not x:
            continue
        code = x.get("documentCode") or ""
        row = r0 or {"doc_id": did, "doc_code": code, "date": (x.get("officialDate") or "")[:10], "role": "input",
                     "original_filing": False, "xml": "", "pdf": "", "source": "none"}
        if code in V.TEXT_CODES or code.startswith("A."):
            opts = {(o.get("mimeTypeIdentifier") or "").upper(): o for o in x.get("downloadOptionBag") or []}
            if "XML" in opts:
                row["xml"] = V.download(s, opts["XML"]["downloadUrl"], d / "xml" / f"{V.stem(x)}.xml.bin", log)
            if row["xml"] in ("ok", "cached"):
                row["source"] = "xml"
            elif "PDF" in opts:
                row["pdf"] = V.download(s, opts["PDF"]["downloadUrl"], d / "pdf" / f"{V.stem(x)}.pdf", log)
                row["source"] = "pdf_ocr" if row["pdf"] in ("ok", "cached") else "none"
        else:
            row["source"] = "not_needed"
        if not r0:
            rows.append(row); have[did] = row
        tot[row["source"]] = tot.get(row["source"], 0) + 1
    with open(sp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"[{k}/{len(apps)}] {app} {tot}", flush=True)
print("done", tot)
