"""The examiner history given to the LLM: full event lists of 3 past applications, cut at each case's cutoff (no API).

    python build_examiner_histories.py --pkg path/to/B_D_C_phase1_v4_reviewed --corpus path/to/profile_corpus_v2.zip \
        --out path/to/D_trajectory/inputs/examiner_histories_v1.jsonl

For each test_core case and each version (own, mismatched):
  - the past applications = the 3 chosen by the team's retrieval in the frozen v4 package (retrieved_cases[].app_id,
    TF-IDF similarity to this case's documents), in the same order (3 for most cases; 1, 2 or 0 where the package has
    fewer);
  - each application's events come from A's profile_corpus_v2 apps/<app_id>/transactions.csv, keeping ONLY events
    dated strictly before the case's cutoff, and only these kinds (same codes as our answer keys):
        examiner letters (mailed):  MCTNF non-final rejection, MCTFR final rejection, MCTAV advisory action,
                                    MCTRS restriction requirement, MCTEQ Ex parte Quayle action,
                                    MN/=. notice of allowance, MABN* notice of abandonment
        applicant actions:          A... reply to a non-final action, A.NE reply to a final action, RCEX RCE filed
    ABN9 is RCE bookkeeping and is not shown. Same-day duplicates are shown once.
  - the last line gives the status at the cutoff: allowed / abandoned (date) or still pending.
Writes one JSON line per (sample_id, variant) with the text shown to the model, its sha1, and the structured events
(used by history_math.py, so the model and the math see exactly the same events).
"""
import argparse, csv, hashlib, io, json, os, zipfile

LETTERS = {"MCTNF": "examiner mailed a non-final rejection", "MCTFR": "examiner mailed a final rejection",
           "MCTAV": "examiner mailed an advisory action", "MCTRS": "examiner mailed a restriction requirement",
           "MCTEQ": "examiner mailed an Ex parte Quayle action", "MN/=.": "examiner mailed a notice of allowance"}
REPLIES = {"A...": "applicant filed a reply to a non-final rejection", "A.NE": "applicant filed a reply to a final rejection",
           "RCEX": "applicant filed a request for continued examination (RCE)"}
ABANDON = "USPTO mailed a notice of abandonment"


def kind(code):
    if code in LETTERS:
        return "letter"
    if code.startswith("MABN"):
        return "abandonment"
    if code in REPLIES:
        return "reply"
    return None


def events_for(z, app, cutoff):
    raw = z.read(f"profile_corpus/apps/{app}/transactions.csv").decode("utf-8", "replace")
    ev, seen = [], set()
    for r in csv.DictReader(io.StringIO(raw)):
        d, c = r["event_date"], r["event_code"].strip()
        k = kind(c)
        if k is None or not d or d >= cutoff:
            continue
        label = ABANDON if k == "abandonment" else LETTERS.get(c) or REPLIES[c]
        key = (d, label)
        if key in seen:
            continue
        seen.add(key)
        ev.append(dict(date=d, code=c, kind=k, label=label))
    ev.sort(key=lambda e: (e["date"], 0 if e["kind"] == "reply" else 1))
    return ev


def status(ev):
    for e in ev:
        if e["code"] == "MN/=.":
            return f"allowed (notice of allowance mailed {e['date']})"
        if e["kind"] == "abandonment":
            return f"abandoned (notice mailed {e['date']})"
    return "still pending"


def history_text(cutoff, apps):
    L = [f"Examiner history reference available before {cutoff}", "",
         "Past applications of this examiner (other patent families). Each list shows the dated prosecution events of "
         f"one application, only events before {cutoff}. Nothing after that date is shown.", ""]
    if not apps:
        L.append("No past applications are supplied for this examiner.")
    for i, (app, ev) in enumerate(apps, 1):
        L.append(f"Past application {i}: {app}")
        if not ev:
            L.append("- no examiner letters or applicant replies before the cutoff")
        for e in ev:
            L.append(f"- {e['date']} {e['label']}")
        L.append(f"Status on {cutoff}: {status(ev)}.")
        L.append("")
    L.append("Use this reference to inform the task while grounding the prediction in the current application's record. "
             "Pending outcomes remain unknown at the cutoff. These few applications may not represent the examiner's "
             "full workload.")
    return "\n".join(L).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    z = zipfile.ZipFile(a.corpus)
    rows, n_events, n_pending = [], 0, 0
    for v in ["own", "mismatched"]:
        folder = os.path.join(a.pkg, "candidate_profiles", v)
        for f in sorted(os.listdir(folder)):
            p = json.load(open(os.path.join(folder, f), encoding="utf-8"))
            cutoff = p["cutoff"]
            apps = []
            for rc in p.get("retrieved_cases") or []:
                ev = events_for(z, rc["app_id"], cutoff)
                assert all(e["date"] < cutoff for e in ev)
                apps.append((rc["app_id"], ev))
                n_events += len(ev); n_pending += status(ev) == "still pending"
            text = history_text(cutoff, apps)
            rows.append(dict(sample_id=p["sample_id"], variant=v, cutoff=cutoff, k=len(apps),
                             app_ids=[x for x, _ in apps], source_profile_sha1=p.get("reviewed_candidate_file_sha1"),
                             events={x: ev for x, ev in apps}, history_text=text,
                             history_sha1=hashlib.sha1(text.encode("utf-8")).hexdigest()))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} histories, {sum(r['k'] for r in rows)} past applications, {n_events} events, "
          f"{n_pending} applications still pending at their cutoff; wrote {a.out}")
    print("file sha1:", hashlib.sha1(open(a.out, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
