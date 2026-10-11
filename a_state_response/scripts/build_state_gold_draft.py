"""Pre-fill the 20 gold state snapshots (10 gold apps x O1/A1 cutoff) for human review (A).
Sources (all dated on or before the cutoff):
  entered claims  = the claim set examined in O1: latest claim listing filed before O1 (USPTO XML
                    claims, else OCR text), or the PGPUB claims when there is none (version 'as_filed')
  proposed claims = A1 claim listing from the reviewed data_v0 claim markup (<ins> kept, <del> and
                    [[ ]] removed); status from the listing label
  rejections      = (claim, ground) pairs parsed from the O1 text, status 'outstanding', evidence = O1
                    doc_id + the rejection sentence
Outputs: A/gold/state_gold_draft.jsonl and A/gold/state_gold_review.csv (one row per claim list and per rejection statement to confirm). After review, corrected snapshots are saved as A/gold/state_gold.jsonl."""
import csv, json, re, sys
from pathlib import Path

A = Path(__file__).resolve().parent.parent
R = A.parent
S = R / "data_v1_share"
sys.path.insert(0, str(R / "scripts"))
from v1_build import claims_from_text, split_inline, load_claims, pub_claims, pgpub_date, norm_status, strip_label, stem_of  # noqa: E402
from v1_grounds import STMT, claim_numbers, ground_of, withdrawn_claims  # noqa: E402

D1 = R / "data_v1" / "apps"


def deps(text):
    out = set()
    for m in re.finditer(r"\bclaims?\s+((?:\d{1,3}(?:\s*(?:-|–|to|through|,|and|or)\s*)?)+)", text, re.I):
        out |= claim_numbers(m.group(1))
    return sorted(out)


def numbered_claims(text):
    """Claims without status labels (as filed): split on lines starting with 'N.' in increasing order."""
    out, cur, nxt = [], None, 1
    for line in text.splitlines():
        m = re.match(r"^\W{0,3}(\d{1,3})\s*[.)]\s+(.*)", line.strip())
        if m and int(m.group(1)) == nxt:
            cur = {"number": nxt, "status": "original", "text": m.group(2)}
            out.append(cur); nxt += 1
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + line.strip()).strip()
    return out


def clean_markup(t):
    t = re.sub(r"<del>.*?</del>", "", t, flags=re.S)
    t = re.sub(r"\[\[.*?\]\]", "", t)
    return re.sub(r"</?ins>", "", t)


def o1_rejections(text, doc_id):
    t = re.sub(r"\s+", " ", text)
    out = {}
    for m in STMT.finditer(t):
        nums = claim_numbers(m.group(1))
        if not nums or max(nums) > 500:
            continue
        gs = ["objection"] if m.group(2).startswith("objected") else ground_of(t[m.end(): m.end() + 300])
        sent = t[m.start(): m.start() + 400]
        sent = " ".join(re.split(r"(?<=\.)\s+(?=[A-Z])", sent)[0].split()[:30])
        for n in nums:
            for g in gs:
                out.setdefault((n, g), {"claim_id": n, "ground": g, "status": "outstanding", "references": [],
                                        "evidence": [{"doc_id": doc_id, "span": sent}]})
    return [out[k] for k in sorted(out)]


def ranges(nums):
    nums, out, i = sorted(set(nums)), [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(out)


def review_claims(app, stage, kind, snap):
    by = {}
    for c in snap[kind]:
        by.setdefault((c["status"], c["version_id"]), []).append(c["claim_id"])
    val = "; ".join(f"{ranges(v)}: {st} (version {ver})" for (st, ver), v in sorted(by.items(), key=lambda x: min(x[1])))
    return {"app_id": app, "stage": stage, "what": kind + f" ({len(snap[kind])} claims; texts in the jsonl)",
            "auto_value": val, "evidence": snap[kind][0]["source"]["doc_id"] if snap[kind] else "",
            "auto_source": snap["draft_sources"][kind], "check (ok / fix)": "", "correction": ""}


gold = [r["app_id"] for r in csv.DictReader(open(S / "gold_subset.csv"))]
OUT = "state_gold"
if "--dev" in sys.argv:                 # automatic reference for the 3 dev apps (not human-reviewed)
    gold, OUT = ["11968167", "11968173", "11968176"] + (A / "inputs" / "tune_apps.txt").read_text().split(), "state_dev_auto"
snaps, review = [], []
for app in gold:
    e = json.loads((S / "examples" / f"{app}.json").read_text())
    cat = list(csv.DictReader(open(S / "apps" / app / "catalog.csv")))
    by = {r["doc_id"]: r for r in cat}
    o1d = e["o1"]["mail_date"]
    d = D1 / app
    # claims examined in O1
    # latest amendment-style claim listing before O1, including preliminary amendments filed on the
    # filing date itself (a listing counts when it carries amendment status labels)
    AMEND = {"currently_amended", "new", "canceled", "previously_presented", "withdrawn"}
    prev = [r for r in cat if r["doc_code"] == "CLM" and r["direction"] == "INCOMING" and "1900" < r["official_date"] < o1d]
    entered, ent_src, ent_ver, ent_doc = [], "pgpub_xml", "as_filed", "pgpub_claims"
    for r in sorted(prev, key=lambda r: (r["official_date"], r["doc_id"]), reverse=True):
        cl, src = load_claims(d, stem_of(r))
        if cl and any(c["status"] in AMEND for c in cl):
            entered, ent_src, ent_ver = cl, src, r["doc_id"]
            break
    pd = pgpub_date(d)
    if not entered and pd and pd <= o1d:   # a PGPUB published after O1 can print later-amended claims
        entered = pub_claims(d, "pgpub")
    if not entered:                       # no PGPUB: claims filed on the filing date
        first = [r for r in cat if r["doc_code"] == "CLM" and r["direction"] == "INCOMING" and r["official_date"] == e["filing_date"]]
        for r in first:
            cl, src = load_claims(d, stem_of(r))
            if not cl and (d / "text" / f"{stem_of(r)}.txt").exists():
                cl, src = numbered_claims((d / "text" / f"{stem_of(r)}.txt").read_text()), "ocr (filed claims)"
            if cl:
                entered, ent_src, ent_doc = [dict(c, status="original") for c in cl], src, r["doc_id"]
                break
    ent = [{"claim_id": c["number"], "version_id": ent_ver if c["status"] not in ("original", "") or ent_ver == "as_filed" else "as_filed",
            "text": "" if c["status"] == "canceled" else c["text"], "dependencies": deps(c["text"]),
            "status": c["status"] or "original", "entry_status": "entered",
            "source": {"doc_id": ent_doc if ent_ver == "as_filed" else ent_ver, "span": ""}} for c in entered]
    # O1 rejections; claims the O1 says are withdrawn from consideration (restriction/election)
    o1 = next(x for x in e["inputs"] if x["doc_id"] == e["o1"]["doc_id"])
    o1_text = (S / o1["text_path"]).read_text()
    rej = o1_rejections(o1_text, o1["doc_id"])
    wd = set(withdrawn_claims(o1_text))
    for c in ent:
        if c["claim_id"] in wd and c["status"] != "canceled":
            c["status"] = "withdrawn"
            c["source"] = {"doc_id": o1["doc_id"], "span": "withdrawn from consideration"}
    # A1 proposed claims
    a1_clm = [i for i in e["a1"]["doc_ids"] if by[i]["doc_code"] == "CLM"]
    proposed, prop_src = [], "none"
    if a1_clm:
        stem = stem_of(by[a1_clm[-1]])
        mk = R / "data_v0" / "apps" / app / "claims_markup" / f"{stem}.txt"
        if mk.exists():
            cl = split_inline([dict(c, text=strip_label(c["text"])) for c in claims_from_text(clean_markup(mk.read_text()))])
            prop_src = "data_v0 reviewed claims_markup"
        else:   # listing text (labels incl. ranges such as "1-7. (Canceled)"), else USPTO XML claim records
            tp = d / "text" / f"{stem}.txt"
            cl = split_inline([dict(c, text=strip_label(c["text"])) for c in claims_from_text(tp.read_text())]) if tp.exists() else []
            prop_src = "A1 listing text (USPTO XML)"
            if not cl:
                cl, prop_src = load_claims(d, stem)
        prev_ver = {c["claim_id"]: c["version_id"] for c in ent}
        seen = set()
        for c in cl:
            if c["number"] in seen:
                continue
            seen.add(c["number"])
            changed = c["status"] in ("currently_amended", "new") or (
                c["status"] == "canceled" and next((x["status"] for x in ent if x["claim_id"] == c["number"]), "") != "canceled")
            proposed.append({"claim_id": c["number"],
                             "version_id": a1_clm[-1] if changed else prev_ver.get(c["number"], "as_filed"),
                             "text": "" if c["status"] == "canceled" else c["text"],
                             "dependencies": deps(c["text"]), "status": c["status"], "entry_status": "unknown",
                             "source": {"doc_id": a1_clm[-1], "span": ""}})
    for stage, cut in (("O1_cutoff", o1d), ("A1_cutoff", e["cutoff"])):
        snap = {"sample_id": f"{app}_t1", "app_id": app, "stage": stage, "cutoff": cut,
                "entered_claims": ent, "proposed_claims": proposed if stage == "A1_cutoff" else [],
                "rejections": rej, "notes": "",
                "draft_sources": {"entered_claims": ent_src, "proposed_claims": prop_src if stage == "A1_cutoff" else "",
                                  "rejections": "parsed from O1 text"}}
        snaps.append(snap)
        if stage == "A1_cutoff":          # O1 rows already cover entered claims and rejections
            if snap["proposed_claims"]:
                review.append(review_claims(app, stage, "proposed_claims", snap))
            continue
        review.append(review_claims(app, stage, "entered_claims", snap))
        by_stmt = {}
        for x in snap["rejections"]:
            by_stmt.setdefault((x["evidence"][0]["span"], x["ground"]), []).append(x["claim_id"])
        for (span, g), cl in by_stmt.items():
            review.append({"app_id": app, "stage": "O1_cutoff (same at A1)", "what": f"rejection {g}",
                           "auto_value": "claims " + ranges(cl), "evidence": span,
                           "auto_source": "parsed from O1 text", "check (ok / fix)": "", "correction": ""})
(A / "gold").mkdir(exist_ok=True)
with open(A / "gold" / f"{OUT}_draft.jsonl", "w") as f:
    for s in snaps:
        f.write(json.dumps(s) + "\n")
with open(A / "gold" / f"{OUT}_review.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(review[0].keys()))
    w.writeheader(); w.writerows(review)
for s in snaps:
    print(s["app_id"], s["stage"], "entered", len(s["entered_claims"]), s["draft_sources"]["entered_claims"],
          "| proposed", len(s["proposed_claims"]), "| rejections", len(s["rejections"]))
print("review rows:", len(review))
