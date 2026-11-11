"""Scale-up fetcher for ProsecutionBench (run on the Mac; needs USPTO_API_KEY, sequential calls only).

Frame: same as the pilot (OARD office_actions.csv, application numbers 11/960,000-14/999,999 whose
earliest OARD action is a CTNF, technology centers 1600-3700), about 2.1 million applications, minus the
64 pilot-sample and 3 dev applications. The frame is put in a fixed random order that is stratified by
technology center, so ANY prefix of the order is a proportional random sample. Stopping early is fine.

Per application (resumable; finished apps are listed in <out>/index.jsonl and skipped on restart):
  phase 1 (always): meta, transactions, continuity, document list (JSON, ~100 KB per app) and
                    catalog.csv / transactions.csv / status.json, exactly as odp_fetch.py writes them;
                    a quick eligibility screen (filing 2008-2015, utility, O1 = CTNF/CTFR, reply to O1);
  phase 2 (eligible apps): native office-action text (Office Action Text Retrieval API, small);
  phase 3 (only with --pdf, eligible apps): Table-8 PDFs (about 4 MB per app). Stops cleanly when free
                    disk space falls below --min-free-gb.

Usage (from ~/examinerbench):
  source ~/.zshrc
  caffeinate -i nohup python3 scripts/full_fetch.py --limit 5000 > full_fetch.log 2>&1 &
  tail -f full_fetch.log                              # watch progress; Ctrl-C only stops tail
  python3 scripts/full_fetch.py --limit 20000         # later: same order, continues where it stopped
  python3 scripts/full_fetch.py --limit 5000 --pdf    # also download Table-8 PDFs (needs disk space)
  python3 scripts/full_fetch.py --out /Volumes/MyDrive/data_full ...   # put data on an external drive
To stop a background run:  pkill -f full_fetch.py   (safe; the current app is redone on restart)
"""
import argparse, csv, json, os, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odp_fetch as F  # noqa: E402

R = Path(__file__).resolve().parent.parent
TCS = ["1600", "1700", "2100", "2400", "2600", "2800", "3600", "3700"]
SEED = 20261006
OA_TEXT_URL = "https://api.uspto.gov/api/v1/patent/oa/oa_actions/v1/records"
REPLY = ("A...", "A.NE", "A.I.", "AMSB", "REM", "CLM")


def build_frame(out):
    p = out / "frame_order.csv"
    if p.exists():
        return [r["app_id"] for r in csv.DictReader(open(p))]
    import numpy as np, pandas as pd
    print("building frame from data/raw/office_actions.csv (one-time, ~1 min) ...", flush=True)
    oa = pd.read_csv(R / "data/raw/office_actions.csv", usecols=["app_id", "document_cd", "mail_dt", "art_unit"],
                     dtype={"app_id": "int64", "document_cd": "string", "mail_dt": "string", "art_unit": "string"})
    oa = oa[(oa.app_id >= 11960000) & (oa.app_id <= 14999999)]
    first = oa.sort_values(["app_id", "mail_dt"]).groupby("app_id", as_index=False).first()
    first["tc"] = first.art_unit.str[:2] + "00"
    fr = first[(first.document_cd == "CTNF") & first.tc.isin(TCS)].copy()
    done = {11968167, 11968176, 11968173}
    sp = R / "data_v0" / "sample_ids.csv"
    if sp.exists():
        done |= {int(r["app_id"]) for r in csv.DictReader(open(sp))}
    fr = fr[~fr.app_id.isin(done)]
    rng = np.random.default_rng(SEED)
    fr["u"] = rng.random(len(fr))
    fr["rank"] = fr.groupby("tc")["u"].rank(method="first") - 1
    fr["key"] = (fr["rank"] + rng.random(len(fr))) / fr.groupby("tc")["u"].transform("size")
    fr = fr.sort_values("key")
    fr[["app_id", "tc", "mail_dt", "art_unit"]].rename(columns={"mail_dt": "oard_first_oa_date"}).to_csv(p, index=False)
    print(f"frame: {len(fr)} applications -> {p}", flush=True)
    return [str(a) for a in fr.app_id]


def screen(app_dir, st):
    rows = list(csv.DictReader(open(app_dir / "catalog.csv")))
    o1 = next((r["official_date"] for r in rows if r["doc_code"] in ("CTNF", "CTFR")), None)
    reply = o1 and any(r["official_date"] > o1 and (r["doc_code"] in REPLY or r["doc_code"].startswith("A..."))
                       for r in rows)
    fd = st.get("filing_date") or ""
    ok_date = "2008-01-01" <= fd <= "2015-12-31"
    ok_type = (st.get("app_type") or "") == "UTL"
    reasons = [n for n, ok in [("filing_date", ok_date), ("not_utility", ok_type), ("no_O1", bool(o1)),
                               ("no_reply_to_O1", bool(reply))] if not ok]
    return {"o1_date": o1, "eligible": not reasons, "exclusion": ";".join(reasons)}


def oa_text(session, app_dir, app):
    out = app_dir / "raw" / "oa_text.json"
    if out.exists():
        return "cached"
    for attempt in range(5):
        wait = F.MIN_GAP - (time.time() - F._last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.post(OA_TEXT_URL, data={"criteria": f"patentApplicationNumber:{app}", "rows": 100, "start": 0},
                             timeout=120)
        except Exception:
            time.sleep(5 * (attempt + 1))
            continue
        finally:
            F._last[0] = time.time()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(6 * (attempt + 1))
            continue
        if r.status_code == 200:
            out.write_bytes(r.content)
            return "ok"
        return f"http_{r.status_code}"
    return "failed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(R / "data_full"))
    ap.add_argument("--limit", type=int, default=5000, help="process the first N apps of the frame order")
    ap.add_argument("--pdf", action="store_true", help="also download Table-8 PDFs for eligible apps")
    ap.add_argument("--min-free-gb", type=float, default=10.0)
    a = ap.parse_args()
    key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
    out = Path(a.out)
    (out / "apps").mkdir(parents=True, exist_ok=True)
    order = build_frame(out)[: a.limit]
    idx_path = out / "index.jsonl"
    done = {}
    if idx_path.exists():
        for line in open(idx_path):
            try:
                r = json.loads(line)
                done[r["app_id"]] = r
            except Exception:
                pass
    F.ROOT = out / "apps"
    real_wanted = F.wanted
    s = F.requests.Session()
    s.headers["X-API-KEY"] = key
    todo = [x for x in order if x not in done or (a.pdf and done[x].get("eligible") and not done[x].get("pdf_done"))]
    print(f"frame order: {len(order)} | already done: {len(order) - len(todo)} | to do: {len(todo)} | pdf: {a.pdf}",
          flush=True)
    t0, n_err = time.time(), 0
    idx = open(idx_path, "a")
    for i, app in enumerate(todo, 1):
        free = shutil.disk_usage(out).free / 1e9
        if free < a.min_free_gb:
            print(f"STOP: only {free:.1f} GB free (< --min-free-gb {a.min_free_gb}).", flush=True)
            break
        F.wanted = lambda code, mode_all: False          # phase 1: no PDFs
        st = F.fetch_app(s, app, False)
        if st.get("status") != "ok":
            n_err += 1
            print(f"[{i}/{len(todo)}] {app} FAILED {st}", flush=True)
            if n_err >= 20 and n_err == i:
                sys.exit("20 failures in a row at the start; check the key / network and rerun.")
            continue
        app_dir = F.ROOT / app
        rec = {"app_id": app, **{k: st.get(k) for k in ("filing_date", "app_type", "art_unit", "app_status",
                                                        "family_id", "n_catalog")}}
        rec.update(screen(app_dir, st))
        if rec["eligible"]:
            rec["oa_text"] = oa_text(s, app_dir, app)
            if a.pdf:
                F.wanted = real_wanted                    # phase 3: Table-8 PDFs (JSON is cached)
                st2 = F.fetch_app(s, app, False)
                rec.update({"pdf_done": True, "n_pdf": st2.get("n_downloaded"), "pdf_bytes": st2.get("bytes")})
        rec["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        idx.write(json.dumps(rec) + "\n")
        idx.flush()
        rate = (time.time() - t0) / i
        print(f"[{i}/{len(todo)}] {app} tc={st.get('art_unit')} eligible={rec['eligible']} "
              f"{rec['exclusion'] or ''} | {rate:.1f}s/app, ETA {rate * (len(todo) - i) / 3600:.1f} h, "
              f"free {free:.0f} GB", flush=True)
    F.wanted = real_wanted
    print("done. index:", idx_path, flush=True)


if __name__ == "__main__":
    main()
