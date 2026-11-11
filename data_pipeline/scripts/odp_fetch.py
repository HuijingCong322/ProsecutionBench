"""
ODP file-wrapper fetcher for ProsecutionBench (A's data pipeline).

Run on your Mac (needs USPTO_API_KEY in the environment, e.g. from ~/.zshrc):
    cd ~/examinerbench
    python3 scripts/odp_fetch.py 11968167 11968176 11968173 --all
    python3 scripts/odp_fetch.py --ids-file data_v0/sample_ids.csv     # Table-8 docs only

For each application it saves, under data_v0/apps/<app_id>/:
    raw/meta.json, raw/transactions.json, raw/documents.json   (untouched API responses)
    catalog.csv        every document in the file wrapper, sorted by date (+ whether it was downloaded)
    transactions.csv   full transaction history, sorted by date
    pdf/<date>_<code>_<docid>.pdf
    fetch_log.jsonl    one line per HTTP call: url, status, bytes, seconds
Re-running skips files already downloaded (resumable). The key is never written to disk.
"""
import argparse, csv, json, os, sys, time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Please run:  pip3 install requests")

BASE = "https://api.uspto.gov/api/v1/patent/applications"
ROOT = Path(__file__).resolve().parent.parent / "data_v0" / "apps"
MIN_GAP = 0.35          # seconds between calls (ODP: no parallel requests per key)

# Table 8 of the paper + codes B needs to check round alignment
TABLE8_PREFIXES = ("A.", "A...", "AF/D", "AFF", "DECL")
TABLE8_CODES = {
    "SPEC", "CLM", "ABST",
    "CTNF", "CTFR", "CTRS", "CTEQ", "CTAV", "NOA", "CTMS",
    "A...", "A.NE", "A.AF", "A.I.", "AMSB", "REM", "RCEX",
    "EXIN", "892", "NINA", "N417", "NRES",
}

_last = [0.0]


def call(session, url, log, stream=False):
    for attempt in range(6):
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        t0 = time.time()
        try:
            r = session.get(url, timeout=120, stream=stream)
        except requests.RequestException as e:
            log.write(json.dumps({"url": url, "error": str(e), "attempt": attempt}) + "\n")
            time.sleep(5 * (attempt + 1))
            continue
        finally:
            _last[0] = time.time()
        if r.status_code == 429 or r.status_code >= 500:
            log.write(json.dumps({"url": url, "status": r.status_code, "attempt": attempt}) + "\n")
            time.sleep(6 * (attempt + 1))
            continue
        content = r.content
        log.write(json.dumps({"url": url, "status": r.status_code, "bytes": len(content),
                              "seconds": round(time.time() - t0, 3)}) + "\n")
        return r.status_code, content
    return None, b""


def day(s):
    return (s or "")[:10]


def wanted(code, mode_all):
    if mode_all:
        return True
    return code in TABLE8_CODES or code.startswith(TABLE8_PREFIXES)


def fetch_app(session, app, mode_all):
    d = ROOT / app
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "pdf").mkdir(exist_ok=True)
    log = open(d / "fetch_log.jsonl", "a")
    t_start = time.time()

    def get_json(name, url):
        p = d / "raw" / f"{name}.json"
        if p.exists():
            return json.loads(p.read_text())
        st, body = call(session, url, log)
        if st != 200:
            print(f"  ! {name}: HTTP {st} {body[:200]!r}")
            return None
        p.write_bytes(body)
        return json.loads(body)

    meta = get_json("meta", f"{BASE}/{app}/meta-data")
    tx = get_json("transactions", f"{BASE}/{app}/transactions")
    cont = get_json("continuity", f"{BASE}/{app}/continuity")
    docs = get_json("documents", f"{BASE}/{app}/documents")
    if docs is None:
        log.close()
        return {"app_id": app, "status": "documents_failed"}

    # transactions.csv
    events = []
    if tx:
        for w in tx.get("patentFileWrapperDataBag", []) or [tx]:
            events += w.get("eventDataBag", []) or []
    events.sort(key=lambda e: e.get("eventDate", ""))
    with open(d / "transactions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_date", "event_code", "event_description"])
        for e in events:
            w.writerow([e.get("eventDate"), e.get("eventCode"), e.get("eventDescriptionText")])

    # documents
    bag = docs.get("documentBag", []) or []
    bag.sort(key=lambda x: (x.get("officialDate", ""), x.get("documentIdentifier", "")))
    rows, n_want, n_ok, n_bytes = [], 0, 0, 0
    for x in bag:
        code = x.get("documentCode", "") or ""
        did = x.get("documentIdentifier", "")
        pdf_opt = next((o for o in x.get("downloadOptionBag", []) or []
                        if (o.get("mimeTypeIdentifier") or "").upper() == "PDF"), None)
        pages = pdf_opt.get("pageTotalQuantity") if pdf_opt else None
        want = wanted(code, mode_all)
        path, status = "", "not_requested"
        if want:
            n_want += 1
            safe = code.replace("/", "-").replace(".", "_")
            p = d / "pdf" / f"{day(x.get('officialDate'))}_{safe}_{did}.pdf"
            path = str(p.relative_to(ROOT.parent))
            if p.exists() and p.stat().st_size > 0:
                status = "ok"
            elif not pdf_opt:
                status = "no_pdf_option"
            else:
                st, body = call(session, pdf_opt["downloadUrl"], log)
                if st == 200 and body[:4] == b"%PDF":
                    p.write_bytes(body)
                    status = "ok"
                else:
                    status = f"failed_http_{st}"
            if status == "ok":
                n_ok += 1
                n_bytes += p.stat().st_size
        rows.append([day(x.get("officialDate")), code, x.get("documentCodeDescriptionText"),
                     x.get("directionCategory"), did, pages, want, status, path])
    with open(d / "catalog.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["official_date", "doc_code", "description", "direction", "doc_id",
                    "pages", "requested", "download_status", "pdf_path"])
        w.writerows(rows)
    log.close()
    md = ((meta or {}).get("patentFileWrapperDataBag") or [{}])[0].get("applicationMetaData", {}) or {}
    parents = []
    for b in ((cont or {}).get("patentFileWrapperDataBag") or [{}]):
        parents += [p.get("parentApplicationNumberText") for p in (b.get("parentContinuityBag") or [])
                    if p.get("parentApplicationNumberText")]
    res = {"app_id": app, "status": "ok", "filing_date": md.get("filingDate"),
           "app_type": md.get("applicationTypeCode"), "art_unit": md.get("groupArtUnitNumber"),
           "examiner": md.get("examinerNameText"), "app_status": md.get("applicationStatusDescriptionText"),
           "parents": parents, "family_id": min(parents + [app]), "n_catalog": len(bag), "n_requested": n_want,
           "n_downloaded": n_ok, "bytes": n_bytes, "n_transactions": len(events),
           "seconds": round(time.time() - t_start, 1), "mode": "all" if mode_all else "table8"}
    (d / "status.json").write_text(json.dumps(res, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--ids-file", help="CSV with an app_id column")
    ap.add_argument("--all", action="store_true", help="download every document, not just Table 8")
    a = ap.parse_args()
    key = os.environ.get("USPTO_API_KEY")
    if not key:
        sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
    ids = list(a.ids)
    if a.ids_file:
        with open(a.ids_file) as f:
            ids += [r["app_id"] for r in csv.DictReader(f)]
    s = requests.Session()
    s.headers["X-API-KEY"] = key
    summary = []
    for i, app in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}] {app} ...", flush=True)
        r = fetch_app(s, app.strip(), a.all)
        print("   ", r, flush=True)
        summary.append(r)
    out = ROOT.parent / "fetch_summary.jsonl"
    with open(out, "a") as f:
        for r in summary:
            f.write(json.dumps(r) + "\n")
    print("done ->", out)


if __name__ == "__main__":
    main()
