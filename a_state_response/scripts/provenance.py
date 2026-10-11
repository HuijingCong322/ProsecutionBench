"""Provenance rule for the state gold (reproducible from public USPTO documents).

Claim set at a stage = the result of applying, in date order, every applicant claim listing (CLM document)
filed on or before the boundary:
  - entered_claims : listings filed BEFORE the O1 mail date (the set the examiner examined in O1);
  - proposed_claims: the claim listing filed with the A1 reply.
Rule per claim number:
  status    = label in the latest listing that contains the claim ("original" for unlabelled as-filed claims);
  version_id= doc_id of the latest listing in which the claim was amended, added or first canceled
              (labels Currently Amended / New / Canceled); "as_filed" if never changed.
A claim of an earlier listing that a later listing does not mention is flagged "not listed".
This module only lists the candidates and the rule-derived answer; a human confirms each item."""
import csv, json, re, sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "A" / "scripts"))
from v1_build import load_claims, stem_of, claims_from_text, split_inline, strip_label  # noqa: E402
from v1_grounds import withdrawn_claims  # noqa: E402

CHANGE = {"currently_amended", "new"}
import v1_build as _V  # noqa: E402
# review-only: also split mid-paragraph labels written without a period ("... is started 7 (Currently Amended) ...")
_V.INLINE = re.compile(r"\s(\d{1,3})(?:\s*(?:-|\u2013|to|through)\s*(\d{1,3}))?\s*\.?\s*\(\s*((?:currently\s+amended|previously\s+presented|original|cancell?ed|withdrawn|new|not\s+entered))[^)]{0,20}\)", re.I)


def numbered(text):
    out, cur, nxt = [], None, 1
    for line in text.splitlines():
        m = re.match(r"^\W{0,3}(\d{1,3})\s*[.)]\s+(.*)", line.strip())
        if m and int(m.group(1)) == nxt:
            cur = {"number": nxt, "status": "original", "text": m.group(2)}; out.append(cur); nxt += 1
        elif cur is not None:
            cur["text"] += " " + line.strip()
    return out


def claim_docs(app):
    d = R / "data_v1" / "apps" / app
    cat = [r for r in csv.DictReader(open(d / "catalog.csv")) if r["official_date"] > "1900"]
    out = []
    for r in sorted(cat, key=lambda r: (r["official_date"], r["doc_id"])):
        if r["doc_code"] != "CLM" or r["direction"] != "INCOMING":
            continue
        stem = stem_of(r)
        t = d / "text" / f"{stem}.txt"
        txt = t.read_text() if t.exists() else ""
        cands = []
        xc, xs = load_claims(d, stem)                       # USPTO XML claim records (or OCR text)
        cands.append((xc, xs))
        if txt:                                             # listing text with "N. (Status)" labels
            tc = split_inline([dict(c, text=strip_label(c["text"])) for c in claims_from_text(txt)])
            cands.append((tc, "listing text"))
            cands.append((numbered(txt), "numbered (no status labels)"))
        def score(c):
            cl = c[0]; labelled = any(x.get("status") not in ("", "original", None) for x in cl) or c[1] != "numbered (no status labels)"
            return (len({x["number"] for x in cl}), labelled)
        cl, src = max(cands, key=score)
        is_filed = src == "numbered (no status labels)" or not any(x.get("status") not in ("", "original", None) for x in cl)
        out.append({"doc_id": r["doc_id"], "date": r["official_date"], "source": src, "filed": is_filed,
                    "claims": {c["number"]: c for c in cl}, "text_path": f"data_v1/apps/{app}/text/{stem}.txt"})
    # same-day documents: unlabelled (as-filed) claims before an amendment listing
    out.sort(key=lambda x: (x["date"], not x["filed"], x["doc_id"]))
    return out


def ranges(nums):
    nums = sorted(set(nums)); o = []
    for n in nums:
        if o and n == o[-1][1] + 1: o[-1][1] = n
        else: o.append([n, n])
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in o)


def summarize(state):
    g = {}
    for n, (s, v) in state.items():
        g.setdefault((s, v), []).append(n)
    return "; ".join(f"{ranges(v)}: {s} [{ver}]" for (s, ver), v in sorted(g.items(), key=lambda kv: min(kv[1])))


def apply_rule(docs, src=None):
    state, notes = {}, []
    src = {} if src is None else src                  # claim -> doc that last LISTED it (text source)
    for i, doc in enumerate(docs):
        listed = doc["claims"]
        if i > 0 and state:
            missing = sorted(set(state) - set(listed))
            if missing and listed:
                notes.append(f"{doc['date']} {doc['doc_id']} does not list claims {ranges(missing)}")
        for n, c in listed.items():
            src[n] = (doc["doc_id"], doc["date"], c.get("text", ""))
            s = c.get("status") or "original"
            prev = state.get(n)
            if (i == 0 or doc["filed"]) and s == "original":
                state[n] = ("original", "as_filed")
            elif s in CHANGE or (s == "canceled" and (not prev or prev[0] != "canceled")):
                state[n] = (s, doc["doc_id"])
            else:
                state[n] = (s, prev[1] if prev else ("as_filed" if s == "original" else "?"))
    return state, notes


def chain_text(docs):
    lines = []
    for d in docs:
        g = {}
        for n, c in d["claims"].items():
            g.setdefault(c.get("status") or "original", []).append(n)
        lines.append(f"{d['date']} CLM {d['doc_id']} ({d['source']}): " +
                     "; ".join(f"{ranges(v)} {k}" for k, v in sorted(g.items(), key=lambda kv: min(kv[1]))))
    return "\n".join(lines)


def stage_rule(app, stage):
    e = json.load(open(R / "data_v1" / "examples" / f"{app}.json"))
    o1 = e["o1"]["mail_date"]
    docs = claim_docs(app)
    before = [d for d in docs if d["date"] < o1]
    s_ent, s_prop = {}, {}
    ent, n1 = apply_rule(before, s_ent)
    # claims the O1 action withdraws from consideration (restriction/election) are "withdrawn" in the examined set
    o1t = [p for p in (R / "data_v1" / "apps" / app / "text").glob(f"*{e['o1']['doc_id']}*.txt") if "substantive" not in p.name]
    wd = withdrawn_claims(o1t[0].read_text()) if o1t else []
    for n in wd:
        if n in ent and ent[n][0] != "canceled":
            ent[n] = ("withdrawn", ent[n][1])
    if wd:
        n1 = n1 + [f"O1 {e['o1']['doc_id']} withdraws claims {ranges(wd)} from consideration"]
    a1 = [d for d in docs if d["doc_id"] in e["a1"]["doc_ids"]]
    prop, n2 = apply_rule(before + a1, s_prop) if a1 else ({}, [])
    prop = {n: v for n, v in prop.items() if a1 and n in a1[-1]["claims"]}
    return {"entered": (summarize(ent), chain_text(before), n1, f"claim listings filed before O1 ({o1})"),
            "proposed": (summarize(prop), chain_text(before + a1), n2, "listings before O1 + the A1 claim listing"),
            "text_source": {"entered": s_ent, "proposed": s_prop}}
