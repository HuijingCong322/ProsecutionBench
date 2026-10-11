"""Download the PDFs of the claim listings used in the gold text review (A/gold/pdf/<app>_<date>_<doc>.pdf)."""
import json, os, sys, csv
from pathlib import Path
R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "scripts"))
import v1_fetch as V  # noqa: E402
key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
s = V.F.requests.Session(); s.headers["X-API-KEY"] = key
out = R / "A" / "gold" / "pdf"; out.mkdir(parents=True, exist_ok=True)
log = open(out / "fetch.log", "a")
want = {(r["app_id"], r["doc_id"]) for r in csv.DictReader(open(R / "A" / "gold" / "state_gold_review_v2.csv"))
        if " text (sim" in r["what"] and r["doc_id"]}
nf = R / "A" / "gold" / "pdf_needed.txt"           # documents linked from gold_review_v3.xlsx
if nf.exists():
    want |= {tuple(l.split("\t")) for l in nf.read_text().splitlines() if l.strip()}
for app, did in sorted(want):
    docs = json.loads((R / "data_v1" / "apps" / app / "raw" / "documents.json").read_text()).get("documentBag", [])
    x = next((d for d in docs if d.get("documentIdentifier") == did), None)
    o = next((o for o in (x or {}).get("downloadOptionBag", []) if (o.get("mimeTypeIdentifier") or "").upper() == "PDF"), None)
    if not o:
        print(app, did, "no PDF option"); continue
    p = out / f"{app}_{(x.get('officialDate') or '')[:10]}_{did}.pdf"
    print(app, did, V.download(s, o["downloadUrl"], p, log), p.name, flush=True)
print("done")
