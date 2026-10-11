"""Gold review sheet v2: automatic reference vs frozen-prompt model output, side by side (A).
Input : gold/state_gold_draft.jsonl (auto reference), outputs/state_predictions.jsonl (frozen prompt).
Output: gold/state_gold_review_v2.csv. One row per (app, stage, claim list) summary, per rejection ground,
        and per amended/new claim whose two texts differ (similarity < 0.90).
Reviewer: open the cited document (doc_id) in the PDF / text, fill 'decision' with auto / model / fix,
and put the correct value in 'correction' when 'fix'. Rows with agree=yes need only a quick look."""
import csv, json, difflib, re
from collections import defaultdict
from pathlib import Path

A = Path(__file__).resolve().parent.parent


def st(r):
    return r.get("state", r) or {}


def ranges(nums):
    nums = sorted(set(nums)); out = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out)


def claim_summary(cl):
    g = defaultdict(list)
    for c in cl:
        g[(c.get("status"), c.get("version_id"))].append(int(c["claim_id"]))
    return "; ".join(f"{ranges(v)}: {s} [{ver}]" for (s, ver), v in sorted(g.items(), key=lambda kv: min(kv[1])))


def rej_summary(rj):
    g = defaultdict(list)
    for r in rj:
        g[r.get("ground")].append(int(r["claim_id"]))
    return {k: ranges(v) for k, v in g.items()}


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"\[\[.*?\]\]", "", t or "")).strip().lower()


ref = {(r["app_id"], r["stage"]): r for r in map(json.loads, open(A / "gold" / "state_gold_draft.jsonl"))}
pred = {(r["app_id"], r["stage"]): r for r in map(json.loads, open(A / "outputs" / "state_predictions.jsonl"))
        if r.get("group") == "gold"}
rows = []
for k in sorted(ref):
    app, stage = k
    R, P = st(ref[k]), st(pred.get(k, {}))
    if not pred.get(k):
        rows.append({"app_id": app, "stage": stage, "what": "MODEL OUTPUT MISSING"}); continue
    for lst in ("entered_claims", "proposed_claims"):
        a, b = claim_summary(R.get(lst, [])), claim_summary(P.get(lst, []))
        src = next((c.get("source", {}).get("doc_id") for c in R.get(lst, []) if c.get("source")), "")
        rows.append({"app_id": app, "stage": stage, "what": f"{lst} (status [version_id])", "doc_id": src,
                     "auto": a, "model": b, "agree": "yes" if a == b else "NO"})
        rc = {c["claim_id"]: c for c in R.get(lst, [])}
        for c in P.get(lst, []):
            r = rc.get(c["claim_id"])
            if not r or r.get("status") not in ("currently_amended", "new") and c.get("status") not in ("currently_amended", "new"):
                continue
            sim = difflib.SequenceMatcher(None, norm(r.get("text")), norm(c.get("text")), autojunk=False).ratio()
            if sim < 0.90:
                rows.append({"app_id": app, "stage": stage, "what": f"{lst} claim {c['claim_id']} text (sim {sim:.2f})",
                             "doc_id": (r.get("source") or {}).get("doc_id", ""), "auto": r.get("text", "")[:1500],
                             "model": c.get("text", "")[:1500], "agree": "NO"})
    ra, rb = rej_summary(R.get("rejections", [])), rej_summary(P.get("rejections", []))
    ev = {r["ground"]: (r.get("evidence") or [{}])[0] for r in R.get("rejections", [])}
    for g in sorted(set(ra) | set(rb)):
        e = ev.get(g, {})
        rows.append({"app_id": app, "stage": stage, "what": f"rejection {g}: claims", "doc_id": e.get("doc_id", ""),
                     "auto": ra.get(g, "(none)"), "model": rb.get(g, "(none)"), "agree": "yes" if ra.get(g) == rb.get(g) else "NO",
                     "evidence": e.get("span", "")})
    sa = sorted({(r["claim_id"], r["ground"], r["status"]) for r in R.get("rejections", [])})
    sb = sorted({(r["claim_id"], r["ground"], r["status"]) for r in P.get("rejections", [])})
    stat = lambda s: ", ".join(f"{x}" for x in sorted({t[2] for t in s}))
    rows.append({"app_id": app, "stage": stage, "what": "rejection statuses used", "auto": stat(sa), "model": stat(sb),
                 "agree": "yes" if stat(sa) == stat(sb) else "NO"})
cols = ["app_id", "stage", "what", "doc_id", "agree", "auto", "model", "evidence", "decision (auto/model/fix)", "correction"]
with open(A / "gold" / "state_gold_review_v2.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
n_no = sum(r.get("agree") == "NO" for r in rows)
print(f"rows {len(rows)}; disagreements {n_no}; apps {len({r['app_id'] for r in rows})}")
