"""Backfill examiner profiles so they predate the examples' cutoffs (v1.1).
The first profile run searched filings 2004-2015 newest-first, so most profile actions fell in 2015-2017,
after most cutoffs. Here, per examiner whose examples have < 3 profile actions before the cutoff:
  window = filings in [earliest cutoff - 7 years, earliest cutoff - 1 year]
  candidates = utility apps of that examiner in the window, not in our sample and NOT in the family of
               any sample application (family = min(parents + app), as in data_v1)
  keep up to --per-examiner apps whose first examiner action (CTNF/CTFR) was mailed before the
  examiner's latest example cutoff; save documents.json + USPTO XML of their first two actions.
Order: family check of first-run profile apps first, then examiners with test examples, then the rest. Resumable. Output: profiles/apps/<app>/..., profiles/index_backfill.jsonl
Run on the Mac:  source ~/.zshrc; caffeinate -i python3 scripts/v1_profiles_backfill.py"""
import argparse, json, os, random, sys, time, urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odp_fetch as F  # noqa: E402
from v1_fetch import download, stem  # noqa: E402

D = Path(__file__).resolve().parent.parent / "data_v1"
P = D / "profiles"
SEARCH = "https://api.uspto.gov/api/v1/patent/applications/search"


def shift(d, years):
    y, m, dd = map(int, d.split("-"))
    return date(y + years, m, min(dd, 28)).isoformat()


def search(s, name, lo, hi, log):
    rng = "&rangeFilters=" + urllib.parse.quote(f"applicationMetaData.filingDate {lo}:{hi}")
    flds = "&fields=" + urllib.parse.quote("applicationNumberText,applicationMetaData.filingDate,"
                                           "applicationMetaData.applicationTypeCode")
    for field in ("applicationMetaData.examinerNameText", "examinerNameText"):
        q = urllib.parse.quote(f'{field}:"{name}"')
        bag = []
        for off in (0, 25, 50, 75):
            st, body = F.call(s, f"{SEARCH}?q={q}&limit=25&offset={off}{rng}{flds}", log)
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
    ap.add_argument("--per-examiner", type=int, default=6)
    ap.add_argument("--max-candidates", type=int, default=25)
    ap.add_argument("--only-test", action="store_true", help="only examiners with test examples")
    a = ap.parse_args()
    key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
    s = F.requests.Session()
    s.headers["X-API-KEY"] = key
    sample = [r for r in map(json.loads, open(D / "index.jsonl")) if r.get("eligible") and r.get("examiner")]
    own = {r["app_id"] for r in sample}
    fams = {r.get("family_id") or r["app_id"] for r in sample}
    name_of = {r["app_id"]: r["examiner"] for r in sample}
    # first-run profile action dates per examiner (from the saved document lists)
    first_run = {}
    for r in map(json.loads, open(P / "index.jsonl")):
        ds = first_run.setdefault(r["examiner"], [])
        for pa in r["profile_apps"]:
            dp = P / "apps" / pa["app_id"] / "raw" / "documents.json"
            if dp.exists():
                ds += [(x.get("officialDate") or "")[:10] for x in json.loads(dp.read_text()).get("documentBag") or []
                       if x.get("documentCode") in ("CTNF", "CTFR") and x.get("directionCategory") == "OUTGOING"]
    need = {}
    for f in (D / "examples").glob("*.json"):
        e = json.loads(f.read_text())
        ex = name_of.get(e["app_id"])
        n = sum(1 for d0 in first_run.get(ex, []) if d0 < e["cutoff"])
        if ex and n < 3:
            v = need.setdefault(ex, {"cutoffs": [], "test": False})
            v["cutoffs"].append(e["cutoff"]); v["test"] |= e["split"] == "test"
    idx_path = P / "index_backfill.jsonl"
    done = {r["examiner"] for r in map(json.loads, open(idx_path))} if idx_path.exists() else set()
    order = sorted((x for x in need if need[x]["test"] or not a.only_test), key=lambda x: (not need[x]["test"], x))
    log = open(P / "fetch_log.jsonl", "a")
    idx = open(idx_path, "a")
    # phase 1 (first): family check for first-run profile apps that can be visible to some example
    # (first examiner action before the examiner's latest example cutoff): fetch their continuity
    max_cut = {}
    for f in (D / "examples").glob("*.json"):
        e = json.loads(f.read_text())
        ex = name_of.get(e["app_id"])
        if ex:
            max_cut[ex] = max(max_cut.get(ex, ""), e["cutoff"])
    todo = []
    for r in map(json.loads, open(P / "index.jsonl")):
        for pa in r["profile_apps"]:
            d = P / "apps" / pa["app_id"]
            if (d / "raw" / "continuity.json").exists() or not (d / "raw" / "documents.json").exists():
                continue
            docs = json.loads((d / "raw" / "documents.json").read_text()).get("documentBag") or []
            first = min(((x.get("officialDate") or "")[:10] for x in docs
                         if x.get("documentCode") in ("CTNF", "CTFR") and x.get("directionCategory") == "OUTGOING"), default="")
            if first and first < max_cut.get(r["examiner"], ""):
                todo.append(pa["app_id"])
    print(f"phase 1 (first): continuity for {len(todo)} first-run profile apps", flush=True)
    for j, app in enumerate(todo, 1):
        st, body = F.call(s, f"{F.BASE}/{app}/continuity", log)
        if st == 200:
            (P / "apps" / app / "raw" / "continuity.json").write_bytes(body)
        if j % 50 == 0:
            print(f"  continuity {j}/{len(todo)}", flush=True)
    t0, k = time.time(), 0
    for i, ex in enumerate(order, 1):
        if ex in done:
            continue
        k += 1
        lo_cut, hi_cut = min(need[ex]["cutoffs"]), max(need[ex]["cutoffs"])
        lo, hi = shift(lo_cut, -7), shift(lo_cut, -1)
        bag = search(s, ex, lo, hi, log)
        cands = [b.get("applicationNumberText") for b in bag
                 if b.get("applicationNumberText") not in own
                 and (b.get("applicationMetaData") or {}).get("applicationTypeCode") == "UTL"]
        random.Random(ex).shuffle(cands)
        got, tried = [], 0
        for app in cands:
            if len(got) >= a.per_examiner or tried >= a.max_candidates:
                break
            tried += 1
            d = P / "apps" / app
            (d / "raw").mkdir(parents=True, exist_ok=True)
            cp = d / "raw" / "continuity.json"
            if not cp.exists():
                st, body = F.call(s, f"{F.BASE}/{app}/continuity", log)
                if st != 200:
                    continue
                cp.write_bytes(body)
            parents = []
            for b in (json.loads(cp.read_text()).get("patentFileWrapperDataBag") or [{}]):
                parents += [p.get("parentApplicationNumberText") for p in (b.get("parentContinuityBag") or [])
                            if p.get("parentApplicationNumberText")]
            if min(parents + [app]) in fams or set(parents) & own:
                continue
            p = d / "raw" / "documents.json"
            if not p.exists():
                st, body = F.call(s, f"{F.BASE}/{app}/documents", log)
                if st != 200:
                    continue
                p.write_bytes(body)
            docs = sorted(json.loads(p.read_text()).get("documentBag") or [], key=lambda x: x.get("officialDate") or "")
            oas = [x for x in docs if x.get("documentCode") in ("CTNF", "CTFR") and x.get("directionCategory") == "OUTGOING"]
            if not oas or (oas[0].get("officialDate") or "")[:10] >= hi_cut:
                continue
            n_xml = 0
            for x in oas[:2]:
                o = next((o for o in x.get("downloadOptionBag") or [] if o.get("mimeTypeIdentifier") == "XML"), None)
                if o and download(s, o["downloadUrl"], d / "xml" / f"{stem(x)}.xml.bin", log) in ("ok", "cached"):
                    n_xml += 1
            got.append({"app_id": app, "n_oa_xml": n_xml, "first_oa": (oas[0].get("officialDate") or "")[:10]})
        idx.write(json.dumps({"examiner": ex, "window": [lo, hi], "n_search": len(bag), "n_candidates": len(cands),
                              "has_test": need[ex]["test"], "profile_apps": got}) + "\n")
        idx.flush()
        print(f"[{i}/{len(order)}] {ex} test={need[ex]['test']} window {lo}..{hi}: {len(got)} apps "
              f"| {(time.time() - t0) / k:.1f}s/examiner", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
