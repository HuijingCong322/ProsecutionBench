"""Derive the t=1 round (O1, A1, cutoff, next event, label) from an app's ODP catalog.csv.
Usage: python3 scripts/build_rounds.py <app_id> [...]   (or --all)
Writes data_v0/apps/<app>/rounds.json and appends rows to data_v0/manifest.jsonl (rebuilt each run).
Rules follow the week plan, section 2 (CTNF/CTFR -> 1, NOA -> 0, other communications -> other,
RCE/appeal/abandonment first -> out_of_scope, nothing yet -> censored)."""
import csv, json, sys
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data_v0"
SUBSTANTIVE = {"CTNF", "CTFR"}
REPLY = {"A...", "A.NE", "A.I.", "A.AF", "AMSB", "REM", "CLM", "SPEC", "ABST", "DRW", "DRW.NE",
         "AF/D", "TRAN.LET", "XT/", "LET."}
PROC_NOTICE = {"NTC.A.NONCPL", "NINA"}          # non-compliant / informal amendment notices
SKIP = {"WFEE", "N417", "SRFW", "SRNT", "BIB", "FWCLM", "IIFW", "1449", "IDS"}
CORE_REPLY = {"A...", "A.NE", "A.I.", "A.AF", "AMSB", "REM", "CLM"}   # a reply must contain one of these
OOS_IN_PREFIX = ("RCEX", "N/AP", "AP.", "APBR", "AP_")              # RCE / appeal filings
# Examiner communications that end the search for the next event. Every other outgoing document
# (filing receipts, publication notices, POA letters, interview summaries, 892/1449 forms, ...) is
# administrative or accompanies an action; it is skipped and listed in rounds.json "skipped_outgoing".
TERMINAL = {"CTNF": 1, "CTFR": 1, "NOA": 0, "CTRS": "other", "CTAV": "other", "CTEQ": "other",
            "CTMS": "other", "ABN": "out_of_scope", "APEA": "out_of_scope", "APDA": "out_of_scope"}
ORIGINAL = {"SPEC", "CLM", "ABST"}


def load(app):
    rows = list(csv.DictReader(open(D / "apps" / app / "catalog.csv")))
    for r in rows:
        r["text_path"] = r["pdf_path"].replace("/pdf/", "/text/").replace(".pdf", ".txt") if r["pdf_path"] else ""
    return rows


def build(app):
    rows = load(app)
    out = {"app_id": app, "status": "ok", "notes": []}
    o1 = next((r for r in rows if r["direction"] == "OUTGOING" and r["doc_code"] in SUBSTANTIVE), None)
    if not o1:
        out["status"] = "no_O1"
        (D / "apps" / app / "rounds.json").write_text(json.dumps(out, indent=2))
        return out
    before = [r for r in rows if r["official_date"] < o1["official_date"]]
    if any(r["doc_code"] == "CTRS" for r in before):
        out["notes"].append("restriction requirement before O1 (not used as O1)")
    after = [r for r in rows if r["official_date"] > o1["official_date"]]
    first_in = next((r for r in after if r["direction"] == "INCOMING" and r["doc_code"] in CORE_REPLY), None)
    if not first_in:
        out.update({"status": "no_reply", "o1": {"doc_id": o1["doc_id"], "code": o1["doc_code"],
                    "mail_date": o1["official_date"]}})
        (D / "apps" / app / "rounds.json").write_text(json.dumps(out, indent=2))
        return out
    a1_dates = [first_in["official_date"]]
    # extend the reply group if a non-compliance notice is answered by a supplemental filing
    i = 0
    while True:
        later = [r for r in rows if r["official_date"] > a1_dates[-1]]
        nxt_out = next((r for r in later if r["direction"] == "OUTGOING"
                        and (r["doc_code"] in TERMINAL or r["doc_code"] in PROC_NOTICE)), None)
        if nxt_out and nxt_out["doc_code"] in PROC_NOTICE:
            supp = next((r for r in later if r["direction"] == "INCOMING" and r["doc_code"] in REPLY
                         and r["official_date"] > nxt_out["official_date"]), None)
            out["notes"].append(f"{nxt_out['doc_code']} {nxt_out['official_date']} after first reply")
            if supp:
                a1_dates.append(supp["official_date"])
                out["procedural_interrupt"] = nxt_out["doc_id"]
                i += 1
                if i < 3:
                    continue
        break
    a1 = [r for r in rows if r["official_date"] in a1_dates and r["direction"] == "INCOMING"
          and r["doc_code"] not in SKIP]
    cutoff = a1_dates[-1]
    later = [r for r in rows if r["official_date"] > cutoff]
    same_day_out = [r for r in rows if r["official_date"] == cutoff and r["direction"] == "OUTGOING"
                    and r["doc_code"] in TERMINAL]
    oos = next((r for r in later if r["direction"] == "INCOMING" and r["doc_code"].startswith(OOS_IN_PREFIX)), None)
    nxt = next((r for r in later if r["direction"] == "OUTGOING" and r["doc_code"] in TERMINAL), None)
    skipped = sorted({r["doc_code"] for r in later if r["direction"] == "OUTGOING" and r["doc_code"] not in SKIP
                      and r["doc_code"] not in TERMINAL and (not nxt or r["official_date"] < nxt["official_date"])})
    out["skipped_outgoing"] = skipped
    if oos and (not nxt or oos["official_date"] <= nxt["official_date"]):
        label, nxt_type = "out_of_scope", oos["doc_code"]
    elif not nxt:
        label, nxt_type = "censored", None
    else:
        label, nxt_type = TERMINAL[nxt["doc_code"]], nxt["doc_code"]
    # v1.2: everything visible up to the cutoff except administrative codes: filing-day originals,
    # documents between filing and O1 (preliminary amendments, restriction requirements and their
    # replies with claim listings), O1 and later. Placeholder catalog rows (year 0001) are ignored.
    real = [r for r in rows if r["official_date"] > "1900"]
    first_day = min(r["official_date"] for r in real)
    inputs = [r for r in real if r["official_date"] <= cutoff and r["doc_code"] not in SKIP
              and r["direction"] != "INTERNAL"
              and ((r["official_date"] == first_day and r["doc_code"] in ORIGINAL)
                   or r["official_date"] > first_day)]
    out.update({
        "o1": {"doc_id": o1["doc_id"], "code": o1["doc_code"], "mail_date": o1["official_date"]},
        "a1": {"doc_ids": [r["doc_id"] for r in a1], "codes": [r["doc_code"] for r in a1],
               "filing_dates": a1_dates},
        "cutoff": cutoff,
        "next_event": ({"doc_id": nxt["doc_id"], "type": nxt["doc_code"], "mail_date": nxt["official_date"],
                        "source": "ODP documents catalog (officialDate)"} if nxt else None),
        "label_occurrence": label, "next_type": nxt_type,
        "ordering_uncertain": bool(same_day_out),
        "input_doc_ids": [r["doc_id"] for r in inputs],
        "target_doc_id": nxt["doc_id"] if nxt and label == 1 else None,
    })
    assert out["target_doc_id"] not in out["input_doc_ids"]
    assert all(r["official_date"] <= cutoff for r in rows if r["doc_id"] in out["input_doc_ids"])
    (D / "apps" / app / "rounds.json").write_text(json.dumps(out, indent=2))
    return out


def manifest(apps):
    with open(D / "manifest.jsonl", "w") as f:
        for app in apps:
            for r in load(app):
                tp = D / r["text_path"] if r["text_path"] else None
                has_text = bool(tp and tp.exists() and tp.stat().st_size > 50)
                cp = r["text_path"].replace("/text/", "/text_clean/") if has_text else ""
                stem = Path(r["pdf_path"]).stem if r["pdf_path"] else ""
                mp = f"apps/{app}/claims_markup/{stem}.txt" if stem else ""
                npth = f"apps/{app}/oa_text/{stem}.txt" if stem else ""
                f.write(json.dumps({"app_id": app, "doc_id": r["doc_id"], "doc_code": r["doc_code"],
                    "description": r["description"], "event_date": r["official_date"],
                    "date_type": "official_date", "direction": r["direction"], "pages": r["pages"],
                    "pdf_path": r["pdf_path"], "text_path": r["text_path"] if has_text else "",
                    "text_clean_path": cp if cp and (D / cp).exists() else "",
                    "claims_markup_path": mp if mp and (D / mp).exists() else "",
                    "native_text_path": npth if npth and (D / npth).exists() else "",
                    "extract_method": "tesseract_psm6_300dpi" if has_text else "",
                    "download_status": r["download_status"],
                    "extract_status": "ok" if has_text else "not_extracted"}) + "\n")


if __name__ == "__main__":
    apps = sorted(p.name for p in (D / "apps").iterdir() if p.is_dir()) if "--all" in sys.argv else sys.argv[1:]
    for a in apps:
        r = build(a)
        print(a, r.get("status"), "O1", (r.get("o1") or {}).get("mail_date"), "cutoff", r.get("cutoff"),
              "next", r.get("next_type"), (r.get("next_event") or {}).get("mail_date"),
              "label", r.get("label_occurrence"), "| inputs", len(r.get("input_doc_ids", [])), r.get("notes"))
    manifest(apps)
