"""data_v1 fetcher: build the t=1 dataset from USPTO-provided text (XML), not from our own OCR.

Run on the Mac (needs USPTO_API_KEY; sequential calls only, resumable):
  cd ~/examinerbench && source ~/.zshrc
  python3 scripts/v1_fetch.py --target 5                       # smoke test
  caffeinate -i nohup python3 scripts/v1_fetch.py --target 1000 > v1_fetch.log 2>&1 &
  tail -f v1_fetch.log                                         # Ctrl-C only stops tail
  pkill -f v1_fetch.py                                         # safe stop; rerun to continue

Application order: the 62 data_v0 applications first (3 pilot apps = dev, 59 = v0 evaluation sample),
then data_full/frame_order.csv (OARD frame, fixed random order stratified by technology center, so any
prefix is a proportional random sample). Stops when --target eligible applications are reached
(the 62 v0 apps are counted in the target).

Per application, under data_v1/apps/<app>/:
  raw/meta.json, transactions.json, continuity.json, documents.json, associated.json (untouched API JSON)
  catalog.csv, transactions.csv, status.json, rounds.json (t=1 round, same rules as data_v0)
  pub/pgpub.*, pub/grant.*      USPTO full-text XML of the published application / granted patent
  xml/<date>_<code>_<docid>.xml.bin   USPTO XML version of each round document (O1 .. A1, next action,
                                and the A2 claim listing as a label-only document)
  pdf/<date>_<code>_<docid>.pdf       ONLY for round documents that have no XML (OCR fallback)
  doc_sources.csv               per round document: which source is available (xml / pgpub / pdf / none)
Index of all screened applications: data_v1/index.jsonl."""
import argparse, csv, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odp_fetch as F      # noqa: E402
import build_rounds as B   # noqa: E402
from full_fetch import screen  # noqa: E402

R = Path(__file__).resolve().parent.parent
OUT = R / "data_v1"
BASE = F.BASE
MAX_PUB_BYTES = 60_000_000          # guard: never pull a bulk weekly archive by mistake
# Round documents whose text a model or label needs. Others (drawings, fee sheets, forms) are skipped.
TEXT_CODES = {"SPEC", "CLM", "ABST", "CTNF", "CTFR", "CTRS", "CTAV", "CTEQ", "CTMS", "NOA",
              "A...", "A.NE", "A.I.", "A.AF", "AMSB", "REM", "892", "EXIN"}
ORIGINAL = {"SPEC", "CLM", "ABST"}
V0_DEV = ["11968167", "11968173", "11968176"]


def stem(d):
    code = (d.get("documentCode") or "").replace("/", "-").replace(".", "_")
    return f"{(d.get('officialDate') or '')[:10]}_{code}_{d.get('documentIdentifier')}"


def download(session, url, path, log, max_bytes=None):
    """Sequential GET with retry; writes path. Returns 'ok', 'cached', 'too_large' or 'http_<n>'."""
    if path.exists() and path.stat().st_size > 0:
        return "cached"
    for attempt in range(6):
        wait = F.MIN_GAP - (time.time() - F._last[0])
        if wait > 0:
            time.sleep(wait)
        t0 = time.time()
        try:
            r = session.get(url, timeout=180, stream=True)
            if r.status_code == 200:
                n = int(r.headers.get("Content-Length") or 0)
                if max_bytes and n > max_bytes:
                    r.close()
                    log.write(json.dumps({"url": url, "status": "too_large", "bytes": n}) + "\n")
                    return "too_large"
                body = r.content
                if max_bytes and len(body) > max_bytes:
                    return "too_large"
        except F.requests.RequestException as e:
            log.write(json.dumps({"url": url, "error": str(e), "attempt": attempt}) + "\n")
            time.sleep(5 * (attempt + 1))
            continue
        finally:
            F._last[0] = time.time()
        if r.status_code == 429 or r.status_code >= 500:
            log.write(json.dumps({"url": url, "status": r.status_code, "attempt": attempt}) + "\n")
            time.sleep(6 * (attempt + 1))
            continue
        log.write(json.dumps({"url": url, "status": r.status_code, "bytes": len(r.content),
                              "seconds": round(time.time() - t0, 3)}) + "\n")
        if r.status_code != 200:
            return f"http_{r.status_code}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return "ok"
    return "failed"


def find_meta(obj, key):
    """Return the first dict stored under `key` anywhere in a JSON object."""
    if isinstance(obj, dict):
        if isinstance(obj.get(key), dict):
            return obj[key]
        for v in obj.values():
            f = find_meta(v, key)
            if f:
                return f
    elif isinstance(obj, list):
        for v in obj:
            f = find_meta(v, key)
            if f:
                return f
    return None


def fetch_pubs(session, app, d, log):
    p = d / "raw" / "associated.json"
    if not p.exists():
        st, body = F.call(session, f"{BASE}/{app}/associated-documents", log)
        if st != 200:
            return {"pgpub": f"assoc_http_{st}", "grant": f"assoc_http_{st}"}
        p.write_bytes(body)
    assoc = json.loads(p.read_text())
    res = {}
    for name, key in (("pgpub", "pgpubDocumentMetaData"), ("grant", "grantDocumentMetaData")):
        m = find_meta(assoc, key)
        url = (m or {}).get("fileLocationURI")
        if not url:
            res[name] = "none"
            continue
        if (d / "pub").exists() and any((d / "pub").glob(f"{name}.*")):
            res[name] = "cached"
            continue
        tmp = d / "pub" / f"{name}.download"
        res[name] = download(session, url, tmp, log, MAX_PUB_BYTES)
        if tmp.exists():
            head = tmp.read_bytes()[:600]
            ext = "zip" if head[:2] == b"PK" else "tar" if head[257:262] == b"ustar" else "xml" \
                if head.lstrip()[:1] == b"<" else "bin"
            tmp.rename(d / "pub" / f"{name}.{ext}")
            res[name + "_file"] = (m or {}).get("xmlFileName") or url.rsplit("/", 1)[-1]
    return res


def fetch_round_docs(session, app, d, rd, has_pgpub, log):
    docs = {x.get("documentIdentifier"): x for x in
            json.loads((d / "raw" / "documents.json").read_text()).get("documentBag", []) or []}
    ids = list(rd.get("input_doc_ids", []))
    nxt = (rd.get("next_event") or {}).get("doc_id")
    if nxt and nxt not in ids:
        ids.append(nxt)
    # label-only: the applicant's next claim listing after the next action (A2 claims). Claims amended in
    # A1 reappear there as clean 'previously presented' text, which gives a clean post-A1 claim version.
    a2 = None
    nd = (rd.get("next_event") or {}).get("mail_date")
    if nd:
        a2 = next((x.get("documentIdentifier") for x in sorted(docs.values(), key=lambda x: x.get("officialDate") or "")
                   if (x.get("officialDate") or "")[:10] > nd and x.get("documentCode") == "CLM"
                   and x.get("directionCategory") == "INCOMING"), None)
        if a2 and a2 not in ids:
            ids.append(a2)
    first_day = min((x.get("officialDate") or "")[:10] for x in docs.values())
    rows = []
    for did in ids:
        x = docs.get(did)
        if not x:
            continue
        code = x.get("documentCode") or ""
        opts = {(o.get("mimeTypeIdentifier") or "").upper(): o for o in x.get("downloadOptionBag") or []}
        original = code in ORIGINAL and (x.get("officialDate") or "")[:10] == first_day
        role = "target" if did == nxt else "label_only_A2_claims" if did == a2 else "input"
        row = {"doc_id": did, "doc_code": code, "date": (x.get("officialDate") or "")[:10], "role": role,
               "original_filing": original, "xml": "", "pdf": "", "source": "none"}
        if code in TEXT_CODES or code.startswith("A."):
            if "XML" in opts:
                row["xml"] = download(session, opts["XML"]["downloadUrl"], d / "xml" / f"{stem(x)}.xml.bin", log)
            xml_ok = row["xml"] in ("ok", "cached")
            if xml_ok:
                row["source"] = "xml"
            elif original and has_pgpub:
                row["source"] = "pgpub"             # original spec/claims/abstract come from the PGPUB XML
            elif "PDF" in opts:                     # exception: no USPTO text -> keep PDF for OCR
                row["pdf"] = download(session, opts["PDF"]["downloadUrl"], d / "pdf" / f"{stem(x)}.pdf", log)
                row["source"] = "pdf_ocr" if row["pdf"] in ("ok", "cached") else "none"
        else:
            row["source"] = "not_needed"
        rows.append(row)
    with open(d / "doc_sources.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["doc_id"])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    return dict(Counter(r["source"] for r in rows))


def app_order():
    v0 = V0_DEV + [r["app_id"] for r in csv.DictReader(open(R / "data_v0" / "labels.csv"))]
    frame = [r["app_id"] for r in csv.DictReader(open(R / "data_full" / "frame_order.csv"))]
    seen = set(v0)
    return [(a, "v0_dev" if a in V0_DEV else "v0_eval") for a in v0] + \
           [(a, "frame") for a in frame if a not in seen]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1000, help="stop after this many eligible apps")
    ap.add_argument("--min-free-gb", type=float, default=5.0)
    a = ap.parse_args()
    key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
    (OUT / "apps").mkdir(parents=True, exist_ok=True)
    F.ROOT = OUT / "apps"
    B.D = OUT
    F.wanted = lambda code, mode_all: False      # never bulk-download PDFs
    idx_path = OUT / "index.jsonl"
    done = {}
    if idx_path.exists():
        for line in open(idx_path):
            try:
                r = json.loads(line); done[r["app_id"]] = r
            except Exception:
                pass
    s = F.requests.Session()
    s.headers["X-API-KEY"] = key
    n_elig = sum(1 for r in done.values() if r.get("eligible"))
    idx = open(idx_path, "a")
    t0, n_new = time.time(), 0
    import shutil
    for pos, (app, origin) in enumerate(app_order()):
        if n_elig >= a.target:
            break
        if app in done:
            continue
        free = shutil.disk_usage(OUT).free / 1e9
        if free < a.min_free_gb:
            print(f"STOP: only {free:.1f} GB free.", flush=True)
            break
        st = F.fetch_app(s, app, False)
        if st.get("status") != "ok":
            print(f"{app} FAILED {st}", flush=True)
            continue
        d = OUT / "apps" / app
        rec = {"app_id": app, "order": pos, "origin": origin,
               **{k: st.get(k) for k in ("filing_date", "app_type", "art_unit", "examiner", "family_id", "n_catalog")}}
        rec.update(screen(d, st))
        if rec["eligible"]:
            log = open(d / "fetch_log.jsonl", "a")
            rd = B.build(app)
            rec.update({"round_status": rd.get("status"), "label": rd.get("label_occurrence"),
                        "next_type": rd.get("next_type")})
            pubs = fetch_pubs(s, app, d, log)
            rec.update(pubs)
            if rd.get("status") == "ok":
                rec["sources"] = fetch_round_docs(s, app, d, rd, pubs.get("pgpub") in ("ok", "cached"), log)
            log.close()
            n_elig += 1
        rec["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        idx.write(json.dumps(rec) + "\n"); idx.flush()
        n_new += 1
        rate = (time.time() - t0) / n_new
        print(f"[{n_elig}/{a.target} eligible] {app} {origin} eligible={rec['eligible']} {rec.get('exclusion') or ''}"
              f" label={rec.get('label')} pgpub={rec.get('pgpub')} src={rec.get('sources')} | {rate:.1f}s/app",
              flush=True)
    print(f"done: {n_elig} eligible. index: {idx_path}", flush=True)


if __name__ == "__main__":
    main()
