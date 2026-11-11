"""Assemble data_v1 examples and Table 3 labels (offline; run after v1_fetch.py and v1_text.py).
Usage: python3 scripts/v1_build.py
Outputs (data_v1/):
  examples/<app>.json   one t=1 example: inputs (with text paths and source), target, all labels
  labels.csv            one row per example with the scalar labels and split
  splits.json           split rule and counts
Splits: (week-3 plan, scaled up) training information cutoff 2013-12-31. test = 300 examples with cutoff
after 2013-12-31: the 25 data_v0 test cases first, then frame order (random), one per family.
train = cutoff and next event on or before 2013-12-31 (later labels -> excluded_time_boundary).
Other post-2013 examples = dev. The 3 pilot apps are dev. Families with a test example are removed from
train/dev. gen_subset = 100 test examples with a second Office Action and target text: the 17 data_v0
generation cases first, then frame order."""
import csv, hashlib, json, re, sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v1_grounds import grounds  # noqa: E402

D = Path(__file__).resolve().parent.parent / "data_v1"
TYPE = {"CTNF": "nonfinal_rejection", "CTFR": "final_rejection", "NOA": "allowance", "CTRS": "restriction",
        "CTAV": "advisory_action", "CTEQ": "ex_parte_quayle", "CTMS": "misc_communication"}
REPLY_CODES = ("A...", "A.NE", "A.I.", "A.AF", "AMSB", "REM", "CLM")
GEN_N = 100
N_TEST = 300
N_CORE = 100
GEN_CORE = 50
LABEL = re.compile(r"^\W{0,3}(?:claims?\s+)?(\d{1,3})"
                   r"(?:(?:\s*[-\u2013]\s*|\s*(?:[.,:)]|\s)\s*(?:-|\u2013|to|through)\s*)(\d{1,3})\.?|\s*(?:[.,:)]|\s))"
                   r"[|:;.,\s]*\(\s*([A-Za-z][A-Za-z \-]{2,40})\s*\)", re.I)


def norm_status(s):
    s = (s or "").lower()
    for k, v in (("currently", "currently_amended"), ("previously", "previously_presented"), ("cancel", "canceled"),
                 ("withdrawn", "withdrawn"), ("not entered", "not_entered"), ("new", "new"), ("orig", "original"), ("orgin", "original"),
                 ("amended", "currently_amended")):
        if k in s:
            return v
    return s.replace(" ", "_")


def strip_label(t):
    return re.sub(r"^\W{0,3}(?:claims?\s+)?\d{1,3}\s*[.,:)]?\s*(?:\([^)]{2,40}\))?\s*[.:]?\s*", "", t or "").strip()


def _claim_body(rest):
    """True when text after a range label reads like a claim body ('The ...', 'A ...'): then the
    'range' is a struck renumbering such as '-3334 . (Withdrawn) The ...', not '2-5. (Canceled)'."""
    return bool(re.match(r"\W*(?:t\s?he|an?)\b", rest or "", re.I))


def _bad_range(lo, hi, status, rest):
    """Amended/new claims must carry text, so such a 'range' is a struck renumbering."""
    return hi <= lo or hi - lo > 150 or re.search(r"amend|new", status or "", re.I) is not None or _claim_body(rest)


def claims_from_text(text):
    """Claim listing from OCR text: [{number, status, text}] using '<n>. (<status>)' labels."""
    out, cur = [], None
    for line in text.splitlines():
        m = LABEL.match(line.strip())
        if m and m.group(2) and _bad_range(int(m.group(1)), int(m.group(2)), m.group(3), line.strip()[m.end():]):
            m = None   # a real range ("2-5. (Canceled)") carries no claim body; "-3334 . (...) The ..." is a struck renumbering
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            st = norm_status(m.group(3))
            for n in range(lo, min(hi, lo + 300) + 1):
                cur = {"number": n, "status": st, "text": ""}
                out.append(cur)
            cur["text"] = line.strip()[m.end():].strip()   # for a range: kept on the last number so split_inline sees later labels
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + line.strip()).strip()
    return out


_INL_ST = r"(?:currently\s+amended|previously\s+presented|original|cancell?ed|withdrawn|new|not\s+entered)"
INLINE = re.compile(r"\s(\d{1,3})(?:\s*(?:-|\u2013|to|through)\s*(\d{1,3}))?\s*\.\s*\(\s*(" + _INL_ST + r")[^)]{0,20}\)", re.I)


def _label_status(raw):
    m = LABEL.match((raw or "").strip())
    return norm_status(m.group(3)) if m else None


def split_inline(claims):
    """Split claims whose text carries further labelled claims mid-paragraph
    (e.g. '... rod support. 10. (Currently Amended) The ...'); the source document puts several
    claims in one paragraph / one <pat:Claim> record. Only labels numbered above the host claim
    and not already present are split; no text is dropped."""
    have = {c["number"] for c in claims}
    out = []
    claims = list(claims)
    for c in claims:
        txt, cur = c.get("text") or "", c
        pieces, last = [], 0
        for m in INLINE.finditer(txt):
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            if lo <= c["number"] or hi < lo or hi - lo >= 300 or lo in have:
                continue
            prev = re.findall(r"[A-Za-z]+", txt[max(0, m.start() - 12):m.start()])
            if prev and prev[-1].lower() in ("claim", "claims", "and", "or", "to", "of", "through"):
                continue
            if hi > lo and _bad_range(lo, hi, m.group(3), txt[m.end():]):
                continue
            pieces.append((m, lo, hi))
        if not pieces:
            out.append(c); continue
        host = dict(c, text=txt[:pieces[0][0].start()].strip())
        if c.get("_label_status"):   # merged record: its status category belongs to the last claim
            host["status"] = c["_label_status"]
        out.append(host)
        for i, (m, lo, hi) in enumerate(pieces):
            end = pieces[i + 1][0].start() if i + 1 < len(pieces) else len(txt)
            body = txt[m.end():end].strip()
            st = norm_status(m.group(3))
            for n in range(lo, hi + 1):
                out.append({"number": n, "status": st, "depends_on": [], "text": body if hi == lo else ""})
                have.add(n)
    return out


def load_claims(app_dir, stem):
    """Claims of one claim document: USPTO XML when available, else OCR text. Returns (claims, source)."""
    j = app_dir / "text" / f"{stem}.claims.json"
    if j.exists():
        res = []
        for c in json.loads(j.read_text()):
            if not (c.get("number") or "").isdigit():
                continue
            res.append({"number": int(c["number"]), "status": norm_status(c.get("status")),
                        "depends_on": [int(x) for x in c.get("depends_on", []) if str(x).isdigit()],
                        "text": strip_label(c.get("text")),
                        "_label_status": _label_status(c.get("text"))})
        if res:
            return [{k: v for k, v in c.items() if k != "_label_status"} for c in split_inline(res)], "uspto_xml"
    t = app_dir / "text" / f"{stem}.txt"
    if t.exists():
        return split_inline([dict(c, text=strip_label(c["text"])) for c in claims_from_text(t.read_text())]), "ocr"
    return [], "none"


def pgpub_date(app_dir):
    """Publication date (YYYY-MM-DD) of the PGPUB from its XML publication-reference, or ''."""
    p = app_dir / "pub" / "pgpub.xml"
    if not p.exists():
        return ""
    m = re.search(r"<publication-reference>.*?<date>(\d{8})</date>", p.read_text(errors="replace"), re.S)
    return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ""


def pub_claims(app_dir, name):
    p = app_dir / "text" / f"{name}_claims.json"
    if not p.exists():
        return []
    return [{"number": int(c["number"]), "status": "original" if name == "pgpub" else "granted",
             "depends_on": [int(x) for x in c.get("depends_on", []) if str(x).isdigit()], "text": strip_label(c["text"])}
            for c in json.loads(p.read_text()) if (c.get("number") or "").isdigit()]


def _toks(p):
    return Counter(re.findall(r"[a-z0-9]+", p.read_text().lower())) if p.exists() else Counter()


def contained(filed, pub, min_share=0.95):
    """True when >= min_share of the filed document's word tokens also occur in the publication text."""
    f, g = _toks(filed), _toks(pub)
    n = sum(f.values())
    return n > 0 and sum((f & g).values()) / n >= min_share


def stem_of(r):
    return f"{r['official_date']}_{r['doc_code'].replace('/', '-').replace('.', '_')}_{r['doc_id']}"


def text_paths(app, app_dir, stem, sources):
    p = app_dir / "text" / f"{stem}.txt"
    s = app_dir / "text" / f"{stem}.substantive.txt"
    return {"text_path": f"apps/{app}/text/{stem}.txt" if p.exists() else "",
            "substantive_path": f"apps/{app}/text/{stem}.substantive.txt" if s.exists() else "",
            "source": sources.get(stem, "none")}


def build(rec):
    app = rec["app_id"]
    d = D / "apps" / app
    rd = json.loads((d / "rounds.json").read_text())
    if rd.get("status") != "ok":
        return None
    cat = list(csv.DictReader(open(d / "catalog.csv")))
    by = {r["doc_id"]: r for r in cat}
    srcs = {r["doc_id"]: r for r in csv.DictReader(open(d / "doc_sources.csv"))} if (d / "doc_sources.csv").exists() else {}
    sources = json.loads((d / "text" / "sources.json").read_text()) if (d / "text" / "sources.json").exists() else {}
    cutoff, o1 = rd["cutoff"], rd["o1"]
    nxt = rd.get("next_event") or {}
    snapshot = (rec.get("fetched_at") or "")[:10]

    # inputs ---------------------------------------------------------------------------------------
    inputs, dropped = [], []
    # A pre-grant publication is visible only from its publication date; a late PGPUB can print claims
    # amended during prosecution, so it is used only when published on or before the A1 cutoff.
    pub_date = pgpub_date(d)
    has_pgpub = (d / "text" / "pgpub_claims.json").exists() and bool(pub_date) and pub_date <= cutoff
    if (d / "text" / "pgpub_claims.json").exists() and not has_pgpub:
        dropped.append({"doc_id": "pgpub", "reason": f"published {pub_date or 'unknown'} after cutoff {cutoff}"})
    if has_pgpub:
        for part in ("description", "claims", "abstract"):
            ext = "json" if part == "claims" else "txt"
            inputs.append({"doc_id": f"pgpub_{part}", "doc_code": {"description": "SPEC", "claims": "CLM",
                           "abstract": "ABST"}[part], "date": pub_date,
                           "role": "pre_grant_publication", "text_path": f"apps/{app}/text/pgpub_{part}.{ext}",
                           "substantive_path": "", "source": "pgpub_xml"})
    # as-filed SPEC/CLM/ABST fetched separately (v1_fetch_filed.py) where the PGPUB came out after O1
    extra = [i for i, x in srcs.items() if x.get("role") == "input_filed" and i not in rd["input_doc_ids"] and i in by]
    for did in sorted(extra, key=lambda i: by[i]["official_date"]) + list(rd["input_doc_ids"]):
        r = by[did]
        s = srcs.get(did, {})
        if s.get("source") in ("not_needed",) or (s.get("source") == "pgpub"):
            continue
        if not s:
            continue
        inputs.append({"doc_id": did, "doc_code": r["doc_code"], "date": r["official_date"],
                       "role": "O1" if did == o1["doc_id"] else "A1" if did in rd["a1"]["doc_ids"] else "record",
                       **text_paths(app, d, stem_of(r), sources)})
    target = None
    if nxt:
        r = by[nxt["doc_id"]]
        target = {"doc_id": nxt["doc_id"], "doc_code": r["doc_code"], "date": r["official_date"],
                  **text_paths(app, d, stem_of(r), sources)}

    # occurrence / type ---------------------------------------------------------------------------
    occ = rd.get("label_occurrence")
    lab = {"occurrence": occ if occ in (0, 1) else None,
           "next_type": TYPE.get(rd.get("next_type")) or (rd.get("next_type") and f"out_of_scope:{rd['next_type']}"),
           "censored": occ == "censored", "ordering_uncertain": rd.get("ordering_uncertain", False)}

    # disposition (first allowance or abandonment after the cutoff; right-censored at the snapshot) --
    later = [r for r in cat if r["official_date"] > cutoff and r["direction"] == "OUTGOING"]
    disp = next((r for r in later if r["doc_code"] in ("NOA", "ABN")), None)
    if disp is None and (d / "transactions.csv").exists():
        for e in csv.DictReader(open(d / "transactions.csv")):
            if e["event_date"] > cutoff and ("abandon" in (e["event_description"] or "").lower()):
                disp = {"official_date": e["event_date"][:10], "doc_code": "ABN"}
                break
    end = disp["official_date"] if disp else snapshot
    lab["disposition"] = {"event": {"NOA": "allowance", "ABN": "abandonment"}.get(disp["doc_code"]) if disp else None,
                          "censored": disp is None,
                          "time_days": (date.fromisoformat(end) - date.fromisoformat(cutoff)).days if end else None,
                          "event_date": disp["official_date"] if disp else None, "censor_date": None if disp else snapshot}
    lab["remaining_oas"] = sum(1 for r in later if r["doc_code"] in ("CTNF", "CTFR") and r["official_date"] <= end)

    # claim versions -------------------------------------------------------------------------------
    a1_ids = rd["a1"]["doc_ids"]
    a1_clm = [by[i] for i in a1_ids if by[i]["doc_code"] == "CLM"]
    prev_clm = [r for r in cat if r["doc_code"] == "CLM" and r["direction"] == "INCOMING"
                and r["official_date"] < rd["a1"]["filing_dates"][0] and r["doc_id"] in srcs]
    pre, pre_src = [], "none"
    for r in sorted(prev_clm, key=lambda r: r["official_date"], reverse=True):
        if r["official_date"] == cat[0]["official_date"] and has_pgpub:
            break
        pre, pre_src = load_claims(d, stem_of(r))
        if pre:
            break
    if not pre and has_pgpub:
        pre, pre_src = pub_claims(d, "pgpub"), "pgpub_xml"
    a1c, a1_src = (load_claims(d, stem_of(a1_clm[-1])) if a1_clm else ([], "no_claim_listing_in_A1"))
    post = {}
    a2 = next((i for i, s in srcs.items() if s.get("role") == "label_only_A2_claims"), None)
    if a2:
        for c in load_claims(d, stem_of(by[a2]))[0]:
            if c["status"] == "previously_presented":
                post[c["number"]] = c["text"]
    lab["claims_pre_a1"] = {"source": pre_src, "claims": pre}
    lab["claims_a1"] = {"source": a1_src, "claims": a1c}
    lab["claims_post_a1_clean"] = {"source": "A2_previously_presented" if post else "none",
                                   "claims": [{"number": n, "text": t} for n, t in sorted(post.items())
                                              if any(c["number"] == n and c["status"] in ("currently_amended", "new") for c in a1c)]}
    lab["claims_granted"] = {"source": "grant_xml" if (d / "text" / "grant_claims.json").exists() else "none",
                             "claims": pub_claims(d, "grant")}

    # response strategy ----------------------------------------------------------------------------
    st = {c["status"] for c in a1c}
    codes = [by[i]["doc_code"] for i in a1_ids]
    window = [r for r in cat if o1["mail_date"] < r["official_date"] <= cutoff]
    strat = set()
    if "currently_amended" in st: strat.add("amend_claims")
    if "new" in st: strat.add("add_claims")
    prev_canceled = {c["number"] for c in pre if c["status"] == "canceled"}
    if any(c["status"] == "canceled" and c["number"] not in prev_canceled for c in a1c): strat.add("cancel_claims")
    if "REM" in codes: strat.add("argue")
    if any(c in ("SPEC", "A.NE") for c in codes) or any(c == "SPEC" for c in codes): strat.add("amend_specification")
    if "DRW" in codes or "DRW.NE" in codes: strat.add("amend_drawings")
    if any(r["doc_code"] in ("EXIN", "INTV.SUM.APP", "INTV.SUM.EX") or "interview" in (r["description"] or "").lower()
           for r in window): strat.add("interview")
    if any(r["doc_code"].startswith(("DIST", "DISQ")) or "terminal disclaimer" in (r["description"] or "").lower()
           for r in window): strat.add("terminal_disclaimer")
    if any(r["doc_code"].startswith(("DECL", "AF/D", "RULE")) or "declaration" in (r["description"] or "").lower()
           or "affidavit" in (r["description"] or "").lower() for r in window if r["direction"] == "INCOMING"):
        strat.add("declaration_affidavit")
    lab["response_strategy"] = sorted(strat)

    # grounds and rejection status -------------------------------------------------------------------
    def oa_grounds(doc):
        if not doc or not doc.get("text_path"):
            return None
        return grounds((D / doc["text_path"]).read_text())
    o1_doc = next((x for x in inputs if x["doc_id"] == o1["doc_id"]), None)
    g1 = oa_grounds(o1_doc)
    g2 = oa_grounds(target) if target and target["doc_code"] in ("CTNF", "CTFR") else None
    lab["grounds_o1"] = {"source": (o1_doc or {}).get("source"), "pairs": g1}
    lab["grounds_o2"] = {"source": (target or {}).get("source"), "pairs": g2}
    status = None
    if g1 is not None and (g2 is not None or occ == 0):
        canceled = {c["number"] for c in a1c if c["status"] == "canceled"}
        s2 = set(map(tuple, g2 or []))
        status = []
        for c, g in g1:
            if g == "objection":
                continue
            v = "moot_claim_canceled" if c in canceled else "overcome_allowed" if occ == 0 else \
                "maintained" if (c, g) in s2 else "withdrawn_or_overcome"
            status.append({"claim": c, "ground": g, "status": v})
    lab["rejection_status"] = status
    return {"app_id": app, "family_id": rec.get("family_id") or app, "origin": rec["origin"], "order": rec["order"],
            "art_unit": rec.get("art_unit"), "tc": (str(rec.get("art_unit") or "")[:2] + "00"),
            "examiner_id": "ex_" + hashlib.sha1((rec.get("examiner") or "").encode()).hexdigest()[:10],
            "filing_date": rec.get("filing_date"), "o1": o1, "a1": rd["a1"], "cutoff": cutoff,
            "snapshot_date": snapshot, "inputs": inputs, "dropped_duplicate_doc_ids": dropped, "target": target, "labels": lab}


def main():
    recs = [json.loads(l) for l in open(D / "index.jsonl")]
    recs = [r for r in recs if r.get("eligible") and r.get("round_status") == "ok"]
    exs = []
    for r in recs:
        try:
            e = build(r)
        except Exception as ex:
            print(r["app_id"], "build error", repr(ex))
            continue
        if e:
            exs.append(e)
    # ---- splits (week-3 plan, scaled up) -------------------------------------------------------
    TRAIN_END = "2013-12-31"
    v0 = {r["app_id"]: r for r in csv.DictReader(open(D.parent / "data_v0" / "labels.csv"))}
    v0_test = {a for a, r in v0.items() if r["cutoff"] > TRAIN_END}
    v0_gen = {a for a in v0_test if v0[a]["eligible_gen"] == "True"}
    order = sorted(exs, key=lambda e: (e["app_id"] not in v0_test, e["order"]))
    test, fams = [], set()
    for e in order:
        if len(test) >= N_TEST:
            break
        if e["origin"] != "v0_dev" and e["cutoff"] > TRAIN_END and e["family_id"] not in fams:
            test.append(e["app_id"])
            fams.add(e["family_id"])
    core = set(test[:N_CORE])                       # tier 1: data_v0 test cases first, then random
    test = set(test)
    for e in exs:
        nd = ((e["target"] or {}).get("date")) or (e["labels"]["disposition"].get("event_date"))
        if e["origin"] == "v0_dev":
            e["split"] = "dev"
        elif e["app_id"] in test:
            e["split"] = "test"
        elif e["family_id"] in fams:
            e["split"] = "excluded_family_overlap"
        elif e["cutoff"] > TRAIN_END:
            e["split"] = "dev"
        elif nd and nd > TRAIN_END:
            e["split"] = "excluded_time_boundary"      # label not yet observed by the training cutoff
        else:
            e["split"] = "train"
    gen_order = sorted((e for e in exs if e["split"] == "test" and e["labels"]["occurrence"] == 1
                        and e["target"] and e["target"]["text_path"]),
                       key=lambda e: (e["app_id"] not in v0_gen, e["order"]))
    gid = {e["app_id"] for e in gen_order[:GEN_N]}
    gen_core = {e["app_id"] for e in gen_order if e["app_id"] in core}
    gen_core = {e["app_id"] for e in [g for g in gen_order if g["app_id"] in core][:GEN_CORE]}
    gold = {r["app_id"] for r in csv.DictReader(open(D / "gold_subset.csv"))} if (D / "gold_subset.csv").exists() else set()
    (D / "examples").mkdir(exist_ok=True)
    rows = []
    for e in exs:
        e["gen_subset"] = e["app_id"] in gid
        e["test_core"] = e["app_id"] in core
        e["gen_core"] = e["app_id"] in gen_core
        e["gold_subset"] = e["app_id"] in gold
        (D / "examples" / f"{e['app_id']}.json").write_text(json.dumps(e, indent=1))
        L = e["labels"]
        rows.append({"app_id": e["app_id"], "split": e["split"], "test_core": e["test_core"],
                     "gen_core": e["gen_core"], "gen_subset": e["gen_subset"], "gold_subset": e["gold_subset"], "tc": e["tc"],
                     "art_unit": e["art_unit"], "examiner_id": e["examiner_id"], "family_id": e["family_id"],
                     "cutoff": e["cutoff"], "occurrence": L["occurrence"], "next_type": L["next_type"],
                     "censored": L["censored"], "ordering_uncertain": L["ordering_uncertain"],
                     "disp_event": L["disposition"]["event"], "disp_time_days": L["disposition"]["time_days"],
                     "disp_censored": L["disposition"]["censored"], "remaining_oas": L["remaining_oas"],
                     "strategy": ";".join(L["response_strategy"]),
                     "n_grounds_o1": len(L["grounds_o1"]["pairs"] or []),
                     "n_grounds_o2": "" if L["grounds_o2"]["pairs"] is None else len(L["grounds_o2"]["pairs"]),
                     "claims_a1_source": L["claims_a1"]["source"], "n_post_a1_clean": len(L["claims_post_a1_clean"]["claims"]),
                     "target_source": (e["target"] or {}).get("source", ""),
                     "n_inputs_ocr": sum(x["source"] == "ocr" for x in e["inputs"]),
                     "n_inputs_missing_text": sum(not x["text_path"] for x in e["inputs"])})
    with open(D / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    info = {"rule": __doc__.split("Splits:")[1].strip(), "train_information_cutoff": TRAIN_END,
            "counts": dict(Counter(e["split"] for e in exs)), "gen_subset": len(gid),
            "v0_test_in_test": len(v0_test & test), "v0_gen_in_gen": len(v0_gen & gid),
            "test_core": len(core), "gen_core": len(gen_core),
            "v0_test_in_core": len(v0_test & core), "v0_gen_in_gen_core": len(v0_gen & gen_core)}
    (D / "splits.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
