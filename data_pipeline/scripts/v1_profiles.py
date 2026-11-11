"""Examiner profiles for the personalized columns of Table 3 (dOcc, dR-L). Run after v1_fetch.py.
Needs USPTO_API_KEY; sequential, resumable. For every examiner of an eligible data_v1 application it
searches ODP for up to --per-examiner other applications by the same examiner (filed 2006-2016, other
families), saves their document list (for outcome statistics) and the USPTO XML of their first two
examiner actions on the merits (CTNF/CTFR) for text profiles. Which profile items are visible to a test
example is decided later from dates (only items mailed before that example's cutoff are used).
Output: data_v1/profiles/<app>/raw/documents.json, xml/*.xml.bin; data_v1/profiles/index.jsonl."""
import argparse, json, os, random, sys, time, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odp_fetch as F  # noqa: E402
from v1_fetch import download, stem  # noqa: E402

R = Path(__file__).resolve().parent.parent
D = R / "data_v1"
SEARCH = "https://api.uspto.gov/api/v1/patent/applications/search"


def search(session, name, log):
    """Default search order is newest first, so restrict to filings 2004-2015 (profile actions must
    predate our 2009-2017 cutoffs). Full records for 100 hits can exceed the response limit (HTTP 413),
    so ask only for the fields we need and use pages of 25."""
    rng = "&rangeFilters=" + urllib.parse.quote("applicationMetaData.filingDate 2004-01-01:2015-12-31")
    flds = "&fields=" + urllib.parse.quote("applicationNumberText,applicationMetaData.filingDate,"
                                           "applicationMetaData.applicationTypeCode")
    for field in ("applicationMetaData.examinerNameText", "examinerNameText"):
        q = urllib.parse.quote(f'{field}:"{name}"')
        for extra in (rng + flds, rng):
            bag = []
            for off in (0, 25, 50):
                st, body = F.call(session, f"{SEARCH}?q={q}&limit=25&offset={off}{extra}", log)
                if st != 200:
                    break
                page = json.loads(body).get("patentFileWrapperDataBag") or []
                bag += page
                if len(page) < 25:
                    break
            if bag:
                return bag
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-examiner", type=int, default=8)
    a = ap.parse_args()
    key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
    s = F.requests.Session()
    s.headers["X-API-KEY"] = key
    P = D / "profiles"
    (P / "apps").mkdir(parents=True, exist_ok=True)
    idx_path = P / "index.jsonl"
    # examiners already done = those with at least one profile app (zero-result ones are retried)
    done = {r["examiner"] for r in map(json.loads, open(idx_path)) if r["profile_apps"]} if idx_path.exists() else set()
    sample = [json.loads(l) for l in open(D / "index.jsonl")]
    sample = [r for r in sample if r.get("eligible") and r.get("examiner")]
    own = {r["app_id"] for r in sample}
    fams_by_ex = {}
    for r in sample:
        fams_by_ex.setdefault(r["examiner"], set()).add(r.get("family_id") or r["app_id"])
    log = open(P / "fetch_log.jsonl", "a")
    idx = open(idx_path, "a")
    exs = sorted(fams_by_ex)
    t0 = time.time()
    for i, ex in enumerate(exs, 1):
        if ex in done:
            continue
        bag = search(s, ex, log)
        cands = []
        for b in bag:
            md = b.get("applicationMetaData") or {}
            app = b.get("applicationNumberText")
            fd = md.get("filingDate") or ""
            if app and app not in own and "2004-01-01" <= fd <= "2015-12-31" and md.get("applicationTypeCode") == "UTL":
                cands.append(app)
        random.Random(ex).shuffle(cands)
        got = []
        for app in cands:
            if len(got) >= a.per_examiner:
                break
            d = P / "apps" / app
            (d / "raw").mkdir(parents=True, exist_ok=True)
            p = d / "raw" / "documents.json"
            if not p.exists():
                st, body = F.call(s, f"{F.BASE}/{app}/documents", log)
                if st != 200:
                    continue
                p.write_bytes(body)
            docs = sorted(json.loads(p.read_text()).get("documentBag") or [], key=lambda x: x.get("officialDate") or "")
            oas = [x for x in docs if x.get("documentCode") in ("CTNF", "CTFR") and x.get("directionCategory") == "OUTGOING"]
            if not oas:
                continue
            n_xml = 0
            for x in oas[:2]:
                o = next((o for o in x.get("downloadOptionBag") or [] if o.get("mimeTypeIdentifier") == "XML"), None)
                if o and download(s, o["downloadUrl"], d / "xml" / f"{stem(x)}.xml.bin", log) in ("ok", "cached"):
                    n_xml += 1
            got.append({"app_id": app, "n_oa_xml": n_xml})
        idx.write(json.dumps({"examiner": ex, "n_search": len(bag), "n_candidates": len(cands), "profile_apps": got}) + "\n")
        idx.flush()
        rate = (time.time() - t0) / i
        print(f"[{i}/{len(exs)}] {ex}: {len(got)} profile apps | {rate:.1f}s/examiner", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
