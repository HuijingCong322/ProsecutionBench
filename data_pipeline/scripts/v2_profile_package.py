"""Package and check the examiner profile corpus v2 for the team (offline, no API calls).

  cd ~/examinerbench && python3 scripts/v2_profile_package.py [build_folder]

Reads data_v1/profile_corpus/{cases.json, jobs.jsonl, apps/} (written by v2_profile_corpus.py) and writes
share/profile_corpus_v2/profile_corpus/ plus share/profile_corpus_v2.zip:
  cases.csv, profile_index.csv, actions.csv, MANIFEST.csv (sha1 of every file), checks.json, README.md
  apps/<app>/transactions.csv, catalog.csv, text/...
Only the download jobs that a case actually uses are packaged (own examiner + chosen control examiner).
No examiner names and no ODP status are written. Any failed check stops the script before the zip is made.
"""
import csv, hashlib, json, re, shutil, sys, zipfile
from collections import Counter
from pathlib import Path

R = Path(__file__).resolve().parent.parent
D = R / "data_v1"
SRC = D / "profile_corpus"
BUILD = Path(sys.argv[1]) if len(sys.argv) > 1 else R / "share" / "profile_corpus_v2"   # empty or new folder
OUT = BUILD / "profile_corpus"
ZIP = R / "share" / "profile_corpus_v2.zip"
TEXT_CODES = {"CTNF", "CTFR", "NOA", "CTAV", "CTRS", "CTEQ", "CTMS", "EXIN",
              "REM", "CLM", "A___", "A_NE", "A_AF", "A_I_", "AMSB", "RCEX"}      # codes as written in file names


def parse_stem(name):
    """'2013-03-12_CTNF_HE71YXALPXXIFW4.substantive.txt' -> ('2013-03-12', 'CTNF'); None for other files."""
    for ext in (".substantive.txt", ".claims.json", ".txt"):
        if name.endswith(ext) and re.match(r"\d{4}-\d{2}-\d{2}_", name):
            code, _, doc = name[11:-len(ext)].rpartition("_")
            return (name[:10], code) if code and doc else None
    return None


def eid(name):
    return "ex_" + hashlib.sha1(name.encode()).hexdigest()[:10]


def sha1(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


def main():
    cases = json.loads((SRC / "cases.json").read_text())
    jobs = [json.loads(l) for l in open(SRC / "jobs.jsonl")]
    # re-check every signature with the final name rule (v2_profile_corpus.same_person); an application stays usable
    # only if this examiner signed an action before the job's cutoff
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from v2_profile_corpus import same_person
    n_rechecked = Counter()
    for j in jobs:
        for r in j["screened"]:
            for o in r.get("actions", []):
                new = same_person(o["signer"], j["examiner"]) if o["signer"] else None
                n_rechecked["changed" if new != o["signed_by_this_examiner"] else "same"] += 1
                o["signed_by_this_examiner"] = new
            if r.get("reason") == "usable":
                sr = json.loads((SRC / "apps" / r["app_id"] / "raw" / "search_record.json").read_text())
                if (sr.get("applicationMetaData") or {}).get("examinerNameText") != j["examiner"]:
                    r["reason"] = "examiner_name_not_exact"; n_rechecked["apps_dropped_name"] += 1
                    continue
                first = next((o["date"] for o in r["actions"] if o["signed_by_this_examiner"]), None)
                if not first or first >= j["cutoff"]:
                    r["reason"] = "no_signed_action_before_cutoff (rechecked)"; n_rechecked["apps_dropped"] += 1
                else:
                    r["first_signed_action"] = first
    own = {j["examiner"]: j for j in jobs if j["role"] == "own"}
    ctl = {(j["examiner"], c): j for j in jobs if j["role"] == "control" for c in j["for_cases"]}
    exs = {p.stem: json.loads(p.read_text()) for p in (D / "examples").glob("*.json")}
    s_apps = set(exs)
    s_fams = {e.get("family_id") or a for a, e in exs.items()}
    linked = set()
    for a in exs:
        cp = D / "apps" / a / "raw" / "continuity.json"
        if cp.exists():
            for b in json.loads(cp.read_text()).get("patentFileWrapperDataBag") or []:
                for k, f in (("parentContinuityBag", "parentApplicationNumberText"),
                             ("childContinuityBag", "childApplicationNumberText")):
                    linked |= {p.get(f) for p in (b.get(k) or []) if p.get(f)}

    errors, warn = [], []
    used = {}            # examiner -> list of jobs used
    rows_cases = []
    for a, c in sorted(cases.items()):
        oj = own.get(c["examiner"])
        if oj is None or a not in oj["for_cases"]:
            errors.append(f"{a}: no own download job"); continue
        cj = None
        if c.get("control_examiner"):
            cj = own.get(c["control_examiner"]) if "test examiner" in c["control_level"] else ctl.get((c["control_examiner"], a))
            if cj is None:
                errors.append(f"{a}: control job missing")
            if c["control_examiner"] in (c["examiner"], c["odp_current_examiner"]):
                errors.append(f"{a}: control examiner is the case's own examiner")
        for j in (oj, cj):
            if j:
                used.setdefault(j["examiner"], []).append(j)
        before = lambda j: sum(1 for r in j["screened"] if r.get("reason") == "usable" and r["first_signed_action"] < c["cutoff"])
        n_own, n_ctl = before(oj), (before(cj) if cj else 0)
        if n_own < 20:
            warn.append(f"{a}: own examiner has {n_own} usable applications before the cutoff")
        if cj is None:
            errors.append(f"{a}: no control examiner")
        elif n_ctl < 20:
            errors.append(f"{a}: control examiner has only {n_ctl} usable applications before the cutoff")
        rows_cases.append({"sample_id": a, "cutoff": c["cutoff"], "o1_mail_date": c["o1_mail_date"],
                           "o1_art_unit": c["o1_art_unit"], "examiner_id": eid(c["examiner"]),
                           "signer_source": c["signer_source"], "signer_found_by": c.get("o1_signer_found_by", ""),
                           "n_own_usable_before_cutoff": n_own,
                           "control_art_unit": c.get("control_art_unit", c["o1_art_unit"]),
                           "control_art_unit_source": c.get("control_art_unit_source", "o1_art_unit"),
                           "control_examiner_id": eid(c["control_examiner"]) if cj else "",
                           "control_level": c.get("control_level", ""), "n_control_usable_before_cutoff": n_ctl})
    # latest cutoff of any case that uses each examiner (texts after it must not exist)
    max_cut = {}
    for rc in rows_cases:
        for k in ("examiner_id", "control_examiner_id"):
            if rc[k]:
                max_cut[rc[k]] = max(max_cut.get(rc[k], ""), rc["cutoff"])

    if OUT.exists():
        sys.exit(f"{OUT} already exists: use a new build folder (python3 scripts/v2_profile_package.py <folder>)")
    (OUT / "apps").mkdir(parents=True)
    idx_rows, act_rows, seen = [], [], set()
    stats = Counter()
    for name, js in sorted(used.items()):
        x = eid(name)
        for j in js:
            for r in j["screened"]:
                if r.get("reason") != "usable" or (x, r["app_id"]) in seen:
                    continue
                seen.add((x, r["app_id"]))
                app = r["app_id"]
                src = SRC / "apps" / app
                cont = json.loads((src / "raw" / "continuity.json").read_text())
                parents = [p.get("parentApplicationNumberText") for b in cont.get("patentFileWrapperDataBag") or []
                           for p in b.get("parentContinuityBag") or [] if p.get("parentApplicationNumberText")]
                root = min(parents + [app])
                if app in s_apps or root in s_fams or set(parents) & s_apps or app in linked:
                    errors.append(f"{app}: shares a family with a sample application")
                meta = json.loads((src / "raw" / "search_record.json").read_text()).get("applicationMetaData") or {}
                if any("tatus" in k for k in meta):
                    errors.append(f"{app}: status field in search record")
                tx = json.loads((src / "raw" / "transactions.json").read_text()) if (src / "raw" / "transactions.json").exists() else None
                if not tx:
                    errors.append(f"{app}: no transactions"); continue
                dst = OUT / "apps" / app
                (dst / "text").mkdir(parents=True, exist_ok=True)
                ev = sorted(((e.get("eventDate") or "", e.get("eventCode") or "", e.get("eventDescriptionText") or "")
                             for w in tx.get("patentFileWrapperDataBag") or [] for e in w.get("eventDataBag") or []))
                with open(dst / "transactions.csv", "w", newline="") as f:
                    w = csv.writer(f); w.writerow(["event_date", "event_code", "event_description"])
                    w.writerows([e for e in ev if e[0] and e[0][:10] < max_cut[x]])
                stats["transactions_not_shipped_after_cutoff"] += sum(1 for e in ev if not e[0] or e[0][:10] >= max_cut[x])
                docs = sorted(json.loads((src / "raw" / "documents.json").read_text()).get("documentBag") or [],
                              key=lambda d: (d.get("officialDate") or "", d.get("documentIdentifier") or ""))
                with open(dst / "catalog.csv", "w", newline="") as f:
                    w = csv.writer(f); w.writerow(["official_date", "doc_code", "direction", "doc_id"])
                    w.writerows([((d.get("officialDate") or "")[:10], d.get("documentCode"), d.get("directionCategory"),
                                  d.get("documentIdentifier")) for d in docs
                                 if (d.get("officialDate") or "")[:10] and (d.get("officialDate") or "")[:10] < max_cut[x]])
                n_txt = 0
                for t in sorted((src / "text").glob("*")) if (src / "text").exists() else []:
                    m = parse_stem(t.name)
                    if m and m[1] in TEXT_CODES:
                        if m[0] >= max_cut[x]:
                            stats["texts_not_shipped_after_cutoff"] += 1; continue
                        shutil.copy2(t, dst / "text" / t.name); n_txt += t.name.endswith(".txt") and not t.name.endswith("substantive.txt")
                    elif t.name in ("pgpub_abstract.txt", "pgpub_claims.json"):
                        pub = meta.get("earliestPublicationDate") or ""
                        if not pub or pub >= max_cut[x]:
                            stats["pgpub_not_shipped_after_cutoff"] += 1; continue
                        shutil.copy2(t, dst / "text" / t.name); stats["pgpub_files"] += 1
                cpc = meta.get("cpcClassificationBag") or []
                idx_rows.append({"examiner_id": x, "app_id": app, "family_root": root,
                                 "filing_date": meta.get("filingDate", ""),
                                 "art_unit_today": meta.get("groupArtUnitNumber", ""),
                                 "cpc": ";".join(re.sub(r"\s+", "", c) for c in cpc),
                                 "title": (meta.get("inventionTitle") or "").strip(),
                                 "pgpub_date": meta.get("earliestPublicationDate", ""),
                                 "first_signed_action": r["first_signed_action"], "n_text_docs": n_txt})
                for o in r["actions"]:
                    act_rows.append({"examiner_id": x, "app_id": app, "doc_id": o["doc_id"], "date": o["date"],
                                     "code": o["code"],
                                     "signed_by_this_examiner": "" if o["signed_by_this_examiner"] is None
                                     else str(o["signed_by_this_examiner"]).lower()})
                    stats["signed_" + str(o["signed_by_this_examiner"])] += 1

    def write(name, rows):
        with open(OUT / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write("cases.csv", rows_cases); write("profile_index.csv", idx_rows); write("actions.csv", act_rows)

    # leakage / identity checks on the packaged files themselves
    owner = Counter(r["app_id"] for r in idx_rows)
    errors += [f"{a}: listed under {n} examiners" for a, n in owner.items() if n > 1]
    ex_of = {r["app_id"]: r["examiner_id"] for r in idx_rows}
    pub_of = {r["app_id"]: r["pgpub_date"] for r in idx_rows}
    for d in sorted((OUT / "apps").iterdir()):
        lim = max_cut[ex_of[d.name]]
        for t in (d / "text").iterdir():
            m = parse_stem(t.name)
            if m and m[0] >= lim:
                errors.append(f"{d.name}/{t.name}: shipped but dated {m[0]} >= {lim}")
            if t.name.startswith("pgpub_") and not (pub_of[d.name] and pub_of[d.name] < lim):
                errors.append(f"{d.name}/{t.name}: PGPUB shipped but published {pub_of[d.name]} (latest cutoff {lim})")
        for f in ("transactions.csv", "catalog.csv"):
            for row in list(csv.reader(open(d / f)))[1:]:
                if not row[0] or row[0][:10] >= lim:
                    errors.append(f"{d.name}/{f}: row dated {row[0]} >= {lim}"); break
        stats["apps_scanned"] += 1
    if set(ex_of) != {d.name for d in (OUT / "apps").iterdir()}:
        errors.append("apps/ folders and profile_index.csv do not match")
    names = {c["examiner"] for c in cases.values()} | {c.get("control_examiner") or "" for c in cases.values()}
    for f in ("cases.csv", "profile_index.csv", "actions.csv"):
        body = (OUT / f).read_text().upper()
        hit = [n for n in names if n and n.upper() in body]
        if hit:
            errors.append(f"{f}: contains examiner names {hit[:3]}")
    n_own = [rc["n_own_usable_before_cutoff"] for rc in rows_cases]
    n_ctl = [rc["n_control_usable_before_cutoff"] for rc in rows_cases if rc["control_examiner_id"]]
    checks = {"cases": len(rows_cases), "examiners_own": len({rc["examiner_id"] for rc in rows_cases}),
              "examiners_control": len({rc["control_examiner_id"] for rc in rows_cases if rc["control_examiner_id"]}),
              "profile_applications": len({r["app_id"] for r in idx_rows}), "index_rows": len(idx_rows),
              "own_usable_before_cutoff": {"min": min(n_own), "median": sorted(n_own)[len(n_own) // 2],
                                           "n_ge_30": sum(v >= 30 for v in n_own), "n_lt_20": sum(v < 20 for v in n_own)},
              "control_usable_before_cutoff": {"n": len(n_ctl), "min": min(n_ctl) if n_ctl else None,
                                               "median": sorted(n_ctl)[len(n_ctl) // 2] if n_ctl else None},
              "control_level": dict(Counter(rc["control_level"] for rc in rows_cases)),
              "signer_source": dict(Counter(rc["signer_source"] for rc in rows_cases)),
              "action_signatures": {k: v for k, v in stats.items() if k.startswith("signed_")},
              "pgpub_files": stats["pgpub_files"], "signature_recheck": dict(n_rechecked),
              "not_shipped": {k: stats[k] for k in ("texts_not_shipped_after_cutoff", "pgpub_not_shipped_after_cutoff",
                                                     "transactions_not_shipped_after_cutoff")},
              "examiners_used_with_several_cutoffs": sorted({x for x in max_cut if len({rc["cutoff"] for rc in rows_cases
                                                    if x in (rc["examiner_id"], rc["control_examiner_id"])}) > 1}),
              "apps_scanned_for_dates": stats["apps_scanned"],
              "errors": errors, "warnings": warn}
    (OUT / "checks.json").write_text(json.dumps(checks, indent=1))
    print(json.dumps({k: v for k, v in checks.items() if k not in ("errors",)}, indent=1))
    if errors:
        print(f"{len(errors)} ERRORS, e.g.:", *errors[:15], sep="\n  ")
        sys.exit("not packaged: fix the errors first")
    fmt = R / "scripts" / "PROFILE_CORPUS_FORMAT.md"
    readme = fmt.read_text() if fmt.exists() else "# Examiner profile corpus v2\n"
    readme += "\n## Counts and checks (generated)\n\n```\n" + json.dumps({k: v for k, v in checks.items() if k != "errors"}, indent=1) + "\n```\n"
    (OUT / "README.md").write_text(readme)
    files = sorted(p for p in OUT.rglob("*") if p.is_file())
    with open(OUT / "MANIFEST.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["path", "sha1", "bytes"])
        w.writerows([(str(p.relative_to(OUT)), sha1(p), p.stat().st_size) for p in files])
    z = ZIP
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(OUT.parent))
    print(f"packaged {len(files) + 1} files -> {z} ({z.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
