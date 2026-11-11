"""Fetch the as-filed SPEC/CLM/ABST of applications whose PGPUB was published after the O1 mail date
(the PGPUB is then not visible at that cutoff and may print amended claims). USPTO XML when the document
has it; otherwise the PDF, which v1_text.py --ocr turns into text (mentor rule: OCR only without raw text).
List: data_v1/filed_docs_to_fetch.json  [[app_id, affects_A1, [doc_id, ...]], ...]
Rows are appended to apps/<app>/doc_sources.csv with role 'input_filed'.
Run on the Mac:  source ~/.zshrc; python3 scripts/v1_fetch_filed.py && python3 scripts/v1_text.py --ocr --jobs=4 $(python3 -c "import json;print(' '.join(a for a,_,_ in json.load(open('data_v1/filed_docs_to_fetch.json'))))")"""
import csv, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v1_fetch as V   # noqa: E402

D = V.OUT
key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
s = V.F.requests.Session()
s.headers["X-API-KEY"] = key
todo = json.load(open(D / "filed_docs_to_fetch.json"))
log = open(D / "fetch_filed.log", "a")
tot = {}
for app, _, ids in todo:
    d = D / "apps" / app
    docs = {x.get("documentIdentifier"): x for x in
            json.loads((d / "raw" / "documents.json").read_text()).get("documentBag", []) or []}
    sp = d / "doc_sources.csv"
    rows = list(csv.DictReader(open(sp))) if sp.exists() else []
    byid = {r["doc_id"]: r for r in rows}
    for did in ids:
        x = docs.get(did)
        if not x:
            print(app, did, "not in documents.json"); continue
        opts = {(o.get("mimeTypeIdentifier") or "").upper(): o for o in x.get("downloadOptionBag") or []}
        row = byid.get(did) or {"doc_id": did, "doc_code": x.get("documentCode"), "date": (x.get("officialDate") or "")[:10],
                                "role": "input_filed", "original_filing": True, "xml": "", "pdf": "", "source": "none"}
        if row.get("role") not in ("input_filed",):
            row["role"] = "input_filed"
        if "XML" in opts:
            row["xml"] = V.download(s, opts["XML"]["downloadUrl"], d / "xml" / f"{V.stem(x)}.xml.bin", log)
        if row["xml"] in ("ok", "cached"):
            row["source"] = "xml"
        elif "PDF" in opts:
            row["pdf"] = V.download(s, opts["PDF"]["downloadUrl"], d / "pdf" / f"{V.stem(x)}.pdf", log)
            row["source"] = "pdf_ocr" if row["pdf"] in ("ok", "cached") else "none"
        if did not in byid:
            rows.append(row); byid[did] = row
        tot[row["source"]] = tot.get(row["source"], 0) + 1
        print(app, did, row["doc_code"], row["source"], flush=True)
    fields = list(rows[0].keys())
    with open(sp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
print("done", tot)
