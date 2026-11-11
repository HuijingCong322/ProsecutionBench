"""Examiner profile corpus v2 (A's part of phase 1 of the RAG examiner-profile plan, Oct 2026).

For every test example (default: test_core) it downloads the examiner's OTHER applications, so that B (similar
past cases) and D (examiner numbers) can build one frozen profile per example. Run on the Mac (needs
USPTO_API_KEY; sequential calls only; resumable: re-running skips everything already on disk):

  cd ~/examinerbench && source ~/.zshrc
  python3 scripts/v2_profile_corpus.py --dry-run                      # no API calls: show the plan
  python3 scripts/v2_profile_corpus.py --phase own --only 2           # test run on 2 examiners
  caffeinate -i nohup python3 scripts/v2_profile_corpus.py --phase own > v2_own.log 2>&1 &
  caffeinate -i nohup python3 scripts/v2_profile_corpus.py --phase control > v2_control.log 2>&1 &
  tail -f v2_own.log          # Ctrl-C only stops tail;  pkill -f v2_profile_corpus.py  = safe stop

Rules
- Examiner of an example = the examiner who signed its O1 ("... should be directed to <name>"), i.e. the examiner
  known at the cutoff. ODP's examinerNameText is today's assignment; it is used only when O1 has no signature line
  (flagged signer_source = "odp_current").
- Window: other applications of that examiner filed in [cutoff - 8 years, cutoff - 1 year] (cutoff = A1 filing
  date of the example; the examiner's earliest cutoff when they have several examples).
- Excluded: non-utility applications; the 1,000 sample applications; any application whose family root
  (min of itself and its continuity parents) is a sample family, or that is a parent/child of a sample app.
- Usable = at least one CTNF/CTFR mailed before the cutoff AND signed by this examiner. Target --per-examiner
  usable applications (default 30) from a seeded random order of the candidates.
- Per usable application: search record (filing date, art unit, CPC, title, publication date; NO status),
  documents.json, transactions.json, continuity.json, PGPUB XML when published before the cutoff, and the USPTO
  XML of examiner actions and replies dated before the cutoff (text extracted with v1_text.process).
  Raw document/transaction lists contain the full history up to today: every user must cut them at the cutoff.
- phase control: for each example, a different examiner of the SAME art unit (art unit printed on the example's
  O1, i.e. at the time): first another test examiner already downloaded with >= --min-usable usable apps before
  this example's cutoff, else the most frequent other examiner in an ODP art-unit search, downloaded the same way
  with this example's cutoff. Falls back to the same work group (first 3 digits) and records the level used.

Outputs (data_v1/profile_corpus/):
  apps/<app>/raw/*.json, xml/*.xml.bin, pub/pgpub.*, text/*      one folder per downloaded application
  jobs.jsonl          one line per (role, examiner, cutoff) download job, with every screened candidate + reason
  cases.json          per example: examiner (signer), signer_source, O1 art unit, control examiner + level
  fetch_log.jsonl     one line per HTTP call
"""
import argparse, hashlib, json, os, random, re, shutil, sys, time, urllib.parse
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

R = Path(__file__).resolve().parent.parent
D = R / "data_v1"
OLD = D / "profiles" / "apps"            # v1.2 profile downloads (reused as a local cache, never modified)
OUT = D / "profile_corpus"
SEARCH = "https://api.uspto.gov/api/v1/patent/applications/search"
BASE = "https://api.uspto.gov/api/v1/patent/applications"
OA = ("CTNF", "CTFR")
# examiner actions and applicant replies whose text is kept (dated before the cutoff)
TEXT_CODES = {"CTNF", "CTFR", "NOA", "CTAV", "CTRS", "CTEQ", "CTMS", "EXIN",
              "REM", "CLM", "A...", "A.NE", "A.AF", "A.I.", "AMSB", "RCEX"}
FIELDS = ["applicationNumberText", "applicationMetaData.filingDate", "applicationMetaData.applicationTypeCode",
          "applicationMetaData.examinerNameText", "applicationMetaData.groupArtUnitNumber",
          "applicationMetaData.cpcClassificationBag", "applicationMetaData.inventionTitle",
          "applicationMetaData.earliestPublicationDate"]


# ---------------------------------------------------------------- names and signatures
SIG = re.compile(r"directed(?: to)?\s+(?:examiner\s+)?([A-Z][A-Za-z.'()\- ]{2,60}?)\s*(?:,|whose|at telephone|at \(|who)")
SUFFIX = {"JR", "SR", "II", "III", "IV"}


def letters(s):
    return re.sub(r"[^A-Z]", "", s.upper())


def odp_parts(name):
    """'MCCULLOCH JR, WILLIAM H' -> ('MCCULLOCH', 'WILLIAM', 'H')."""
    last, _, rest = name.partition(",")
    last = " ".join(t for t in last.split() if letters(t) not in SUFFIX)
    rest = [t for t in rest.replace(".", " ").split() if letters(t) not in SUFFIX]
    return letters(last), letters(rest[0]) if rest else "", letters(rest[1])[:1] if len(rest) > 1 else ""


def same_person(signer, odp_name):
    """Signer string from an Office Action vs an ODP name ('LAST, FIRST M').
    Same person if the last name matches a whole word of the signer (or the joined last 2-3 words; a word that only
    repeats letters after the name, e.g. 'HOLECEKOLECEK', also counts) AND another word agrees with the first name
    (first 3 letters: Nate/Nathaniel, Alex/Aleksey) or with the middle initial (Brant = Joseph B.); initials count.
    Name change (Wilson -> Arendt): same first name and middle initial."""
    last, first, mid = odp_parts(odp_name)
    signer = re.sub(r"\([^)]*\)", " ", signer)
    toks = [letters(t) for t in signer.replace(".", " ").replace("-", "").split() if letters(t) and letters(t) not in SUFFIX]
    if not toks or not last:
        return False
    last_ok = any(t == last or (len(last) >= 5 and t.startswith(last)) for t in toks) \
        or any(last == "".join(toks[-k:]) for k in (2, 3))
    rest = [t for t in toks if not (t == last or (len(last) >= 5 and t.startswith(last)))]
    first_ok = not first or not rest or any(
        t[:3] == first[:3] or (len(t) == 1 and t == first[0]) or (mid and t[:1] == mid) for t in rest)
    if last_ok and first_ok:
        return True
    return bool(first and mid and toks[0][:3] == first[:3] and len(toks) >= 3 and toks[1][:1] == mid)


def signer_of(text):
    m = SIG.findall(re.sub(r"\s+", " ", text or ""))
    return m[-1].strip() if m else None


def eid(name):
    return "ex_" + hashlib.sha1(name.encode()).hexdigest()[:10]


def shift(d, years):
    y, m, dd = map(int, d.split("-"))
    return date(y + years, m, min(dd, 28)).isoformat()


# ---------------------------------------------------------------- sample (the 1,000 examples)
def load_sample():
    idx = {r["app_id"]: r for r in map(json.loads, open(D / "index.jsonl")) if r.get("eligible")}
    exs = {p.stem: json.loads(p.read_text()) for p in sorted((D / "examples").glob("*.json"))}
    apps, fams, linked = set(exs), set(), set()
    for a, e in exs.items():
        fams.add(e.get("family_id") or a)
        cp = D / "apps" / a / "raw" / "continuity.json"
        if cp.exists():
            for b in json.loads(cp.read_text()).get("patentFileWrapperDataBag") or []:
                for k, f in (("parentContinuityBag", "parentApplicationNumberText"),
                             ("childContinuityBag", "childApplicationNumberText")):
                    linked |= {p.get(f) for p in (b.get(k) or []) if p.get(f)}
    return idx, exs, apps, fams, linked


BLOCK = re.compile(r"/([^/\n]{3,60})/\s*((?:Supervisory |Primary )?(?:Patent )?Examiner),? Art Unit (\d{4})")


def o1_info(e):
    """From the example's own O1: (signer, how it was found, O1 art unit, supervisor's art unit).
    Signer = name after "should be directed to"; if that name is missing in the text, the first full-name
    (not initials-only) non-supervisory signature block ("/Name/ Primary Examiner, Art Unit 1776")."""
    o1 = next((i for i in e["inputs"] if i.get("role") == "O1"), None)
    signer = au = spe_au = None
    how = "none"
    if o1 and o1.get("text_path") and (D / o1["text_path"]).exists():
        txt = (D / o1["text_path"]).read_text(errors="ignore")
        signer = signer_of(txt)
        how = "directed_to" if signer else "none"
        blocks_ = BLOCK.findall(txt)
        if signer is None:
            full = [b for b in blocks_ if not b[1].startswith("Supervisory")
                    and any(len(letters(t)) > 1 for t in b[0].replace(".", " ").split())]
            if full:
                signer, how = full[0][0].strip(), "signature_block"
        spe = [b for b in blocks_ if b[1].startswith("Supervisory")]
        spe_au = spe[0][2] if spe else None
    xs = list((D / "apps" / e["app_id"] / "xml").glob(f"*{e['o1']['doc_id']}*")) if e.get("o1") else []
    if xs:
        from v1_text import read_archive
        m = re.search(rb"GroupArtUnitNumber>\s*(\d{4})", read_archive(xs[0]), re.I)
        au = m.group(1).decode() if m else None
    return signer, how, au, spe_au


def resolve_examiners(exs, idx, scope, s, log, dry):
    """Per example: the examiner to profile. Returns {app: {...}}."""
    cases = {}
    for a, e in exs.items():
        if not (e.get("test_core") if scope == "test_core" else e.get("split") == "test"):
            continue
        cur = idx[a]["examiner"]
        signer, how, au, spe_au = o1_info(e)
        o1au = au or e["art_unit"]
        # 41xx = USPTO Patent Training Academy (new examiners, not a technology area): the control examiner is taken
        # from the art unit of the supervisory examiner who co-signed O1
        academy = o1au.startswith("41") and spe_au is not None
        rec = {"app_id": a, "cutoff": e["cutoff"], "o1_mail_date": e["o1"]["mail_date"],
               "o1_art_unit": o1au, "o1_art_unit_source": "o1_xml" if au else "odp_current",
               "control_art_unit": spe_au if academy else o1au,
               "control_art_unit_source": "o1_supervisor (training academy 41xx)" if academy else "o1_art_unit",
               "odp_current_examiner": cur, "o1_signer": signer, "o1_signer_found_by": how}
        if signer is None:
            rec.update(examiner=cur, signer_source="odp_current")
        elif same_person(signer, cur):
            rec.update(examiner=cur, signer_source="o1_signature")
        else:
            rec.update(examiner=None if dry else find_odp_name(s, signer, rec["cutoff"], log),
                       signer_source="o1_signature_reassigned")
            if not dry and rec["examiner"] is None:      # signer has no applications under their name in ODP
                rec.update(examiner=cur, signer_source="o1_signer_not_in_odp")
        cases[a] = rec
    return cases


def find_odp_name(s, signer, cutoff, log):
    """ODP spelling ('LAST, FIRST M') of an O1 signer who is not today's examiner of the case."""
    toks = [t for t in signer.replace(".", " ").split() if letters(t) and letters(t) not in SUFFIX]
    last, first = toks[-1].upper(), toks[0].upper()
    import odp_fetch as F
    for q in (f'applicationMetaData.examinerNameText:"{last}, {first}"*', f"applicationMetaData.examinerNameText:{last}"):
        url = (f"{SEARCH}?q={urllib.parse.quote(q)}&limit=50&rangeFilters="
               + urllib.parse.quote(f"applicationMetaData.filingDate {shift(cutoff, -8)}:{cutoff}")
               + "&fields=" + urllib.parse.quote("applicationMetaData.examinerNameText"))
        st, body = F.call(s, url, log)
        if st != 200:
            continue
        names = Counter((b.get("applicationMetaData") or {}).get("examinerNameText")
                        for b in json.loads(body).get("patentFileWrapperDataBag") or [])
        ok = [n for n, _ in names.most_common() if n and same_person(signer, n)]
        if ok:
            return ok[0]
    return None


# ---------------------------------------------------------------- one application
class Fetcher:
    def __init__(self, s, log):
        self.s, self.log = s, log

    def json(self, app, name, url):
        d = OUT / "apps" / app / "raw"
        p = d / f"{name}.json"
        if p.exists():
            return json.loads(p.read_text())
        old = OLD / app / "raw" / f"{name}.json"
        d.mkdir(parents=True, exist_ok=True)
        if old.exists():
            shutil.copy2(old, p)
            return json.loads(p.read_text())
        import odp_fetch as F
        st, body = F.call(self.s, url, self.log)
        if st != 200:
            return None
        p.write_bytes(body)
        return json.loads(body)

    def xml(self, app, doc):
        from v1_fetch import download, stem
        o = next((o for o in doc.get("downloadOptionBag") or [] if o.get("mimeTypeIdentifier") == "XML"), None)
        if not o:
            return "no_xml"
        p = OUT / "apps" / app / "xml" / f"{stem(doc)}.xml.bin"
        old = OLD / app / "xml" / p.name
        if not p.exists() and old.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, p)
        return download(self.s, o["downloadUrl"], p, self.log)

    def oa_signer(self, app, doc):
        """Signer of one examiner action (downloads its XML; None when no USPTO text)."""
        from v1_fetch import stem
        from v1_text import blocks, read_archive, PARSER
        from lxml import etree
        if self.xml(app, doc) not in ("ok", "cached"):
            return None
        root = etree.fromstring(read_archive(OUT / "apps" / app / "xml" / f"{stem(doc)}.xml.bin"), PARSER)
        return signer_of(blocks(root)) if root is not None else None


def family_reason(cont, app, sample_apps, sample_fams, linked):
    parents = []
    for b in cont.get("patentFileWrapperDataBag") or [{}]:
        parents += [p.get("parentApplicationNumberText") for p in (b.get("parentContinuityBag") or [])
                    if p.get("parentApplicationNumberText")]
    if app in sample_apps:
        return "sample_app"
    if min(parents + [app]) in sample_fams:
        return "sample_family"
    if set(parents) & sample_apps or app in linked:
        return "linked_to_sample"
    return None


def run_job(fx, role, name, cutoff_lo, cutoff_hi, for_cases, per_examiner, max_tries, sample, jobs_f, done):
    """Download up to per_examiner usable applications of `name`, usable = first signed CTNF/CTFR < cutoff_lo."""
    key = f"{role}|{name}|{cutoff_lo}"
    if key in done:
        return done[key]
    import odp_fetch as F
    sample_apps, sample_fams, linked = sample
    lo, hi = shift(cutoff_lo, -8), shift(cutoff_lo, -1)
    bag = []
    for off in range(0, 300, 50):
        q = urllib.parse.quote('applicationMetaData.examinerNameText:"%s"' % name)
        url = (f"{SEARCH}?q={q}&limit=50&offset={off}&rangeFilters=" + urllib.parse.quote(f"applicationMetaData.filingDate {lo}:{hi}")
               + "&fields=" + urllib.parse.quote(",".join(FIELDS)))
        st, body = F.call(fx.s, url, fx.log)
        if st != 200:
            break
        page = json.loads(body).get("patentFileWrapperDataBag") or []
        bag += page
        if len(page) < 50:
            break
    # ODP's quoted name search also returns longer names ("LY, ANH" finds "LY, ANH VU H", a different examiner):
    # keep only records whose examiner name is exactly the searched name
    recs = {b.get("applicationNumberText"): b for b in bag if b.get("applicationNumberText")
            and (b.get("applicationMetaData") or {}).get("examinerNameText") == name}
    cands = sorted(recs)
    random.Random(key).shuffle(cands)
    screened, usable = [], []
    for app in cands:
        if len(usable) >= per_examiner or len(screened) >= max_tries:
            break
        meta = recs[app].get("applicationMetaData") or {}
        row = {"app_id": app}
        screened.append(row)
        if meta.get("applicationTypeCode") != "UTL":
            row["reason"] = "not_utility"; continue
        if app in sample_apps:
            row["reason"] = "sample_app"; continue
        cont = fx.json(app, "continuity", f"{BASE}/{app}/continuity")
        if cont is None:
            row["reason"] = "continuity_failed"; continue
        fr = family_reason(cont, app, sample_apps, sample_fams, linked)
        if fr:
            row["reason"] = fr; continue
        docs = fx.json(app, "documents", f"{BASE}/{app}/documents")
        if docs is None:
            row["reason"] = "documents_failed"; continue
        bagd = sorted(docs.get("documentBag") or [], key=lambda x: (x.get("officialDate") or "", x.get("documentIdentifier") or ""))
        oas = [x for x in bagd if x.get("documentCode") in OA and x.get("directionCategory") == "OUTGOING"
               and (x.get("officialDate") or "")[:10] < cutoff_hi]
        if not oas or (oas[0].get("officialDate") or "")[:10] >= cutoff_lo:
            row["reason"] = "no_action_before_cutoff"; continue
        signed = []
        for x in oas:
            sg = fx.oa_signer(app, x)
            signed.append({"doc_id": x.get("documentIdentifier"), "date": (x.get("officialDate") or "")[:10],
                           "code": x.get("documentCode"), "signer": sg,
                           "signed_by_this_examiner": None if sg is None else same_person(sg, name)})
        row["actions"] = signed
        first_ok = next((o["date"] for o in signed if o["signed_by_this_examiner"]), None)
        if not first_ok or first_ok >= cutoff_lo:
            row["reason"] = "no_signed_action_before_cutoff"; continue
        # usable: fetch the rest
        (OUT / "apps" / app / "raw").mkdir(parents=True, exist_ok=True)
        (OUT / "apps" / app / "raw" / "search_record.json").write_text(json.dumps(recs[app], indent=1))
        fx.json(app, "transactions", f"{BASE}/{app}/transactions")
        pub = meta.get("earliestPublicationDate") or ""
        row["pgpub"] = "after_cutoff" if not pub or pub >= cutoff_hi else fetch_pgpub(fx, app)
        n_txt = 0
        for x in bagd:
            if (x.get("officialDate") or "")[:10] < cutoff_hi and (x.get("documentCode") or "") in TEXT_CODES:
                n_txt += fx.xml(app, x) in ("ok", "cached")
        from v1_text import process
        process(OUT / "apps" / app, False)
        row.update(reason="usable", first_signed_action=first_ok, n_text_docs=n_txt)
        usable.append(row)
    rec = {"role": role, "examiner_id": eid(name), "examiner": name, "cutoff": cutoff_lo, "cutoff_max": cutoff_hi,
           "window": [lo, hi], "for_cases": for_cases, "n_search": len(bag), "n_exact_name": len(recs),
           "n_screened": len(screened),
           "n_usable": len(usable), "usable": [u["app_id"] for u in usable], "screened": screened}
    jobs_f.write(json.dumps(rec) + "\n"); jobs_f.flush()
    done[key] = rec
    return rec


def fetch_pgpub(fx, app):
    """PGPUB full-text XML only (never the grant, which is after every profile cutoff)."""
    from v1_fetch import download, find_meta, MAX_PUB_BYTES
    import odp_fetch as F
    d = OUT / "apps" / app
    if (d / "pub").exists() and any(p for p in (d / "pub").glob("pgpub.*") if not p.name.endswith(".download")):
        return "cached"
    ap = d / "raw" / "associated.json"
    if not ap.exists() and (OLD / app / "raw" / "associated.json").exists():
        shutil.copy2(OLD / app / "raw" / "associated.json", ap)
    if not ap.exists():
        st, body = F.call(fx.s, f"{BASE}/{app}/associated-documents", fx.log)
        if st != 200:
            return f"assoc_http_{st}"
        ap.write_bytes(body)
    m = find_meta(json.loads(ap.read_text()), "pgpubDocumentMetaData")
    url = (m or {}).get("fileLocationURI")
    if not url:
        return "none"
    tmp = d / "pub" / "pgpub.download"
    res = download(fx.s, url, tmp, fx.log, MAX_PUB_BYTES)
    if tmp.exists():
        head = tmp.read_bytes()[:600]
        ext = "zip" if head[:2] == b"PK" else "tar" if head[257:262] == b"ustar" else "xml" \
            if head.lstrip()[:1] == b"<" else "bin"
        tmp.rename(d / "pub" / f"pgpub.{ext}")
    return res


def usable_before(rec, cutoff):
    """Number of usable apps of a job whose first signed action is before `cutoff`."""
    return sum(1 for r in rec["screened"] if r.get("reason") == "usable" and r["first_signed_action"] < cutoff)


def au_search(fx, au, cutoff, exclude):
    import odp_fetch as F
    lo, hi = shift(cutoff, -8), shift(cutoff, -1)
    names = Counter()
    for off in range(0, 200, 50):
        q = urllib.parse.quote('applicationMetaData.groupArtUnitNumber:"%s"' % au)
        url = (f"{SEARCH}?q={q}&limit=50&offset={off}"
               "&rangeFilters=" + urllib.parse.quote(f"applicationMetaData.filingDate {lo}:{hi}")
               + "&fields=" + urllib.parse.quote("applicationMetaData.examinerNameText"))
        st, body = F.call(fx.s, url, fx.log)
        if st != 200:
            break
        page = json.loads(body).get("patentFileWrapperDataBag") or []
        names.update((b.get("applicationMetaData") or {}).get("examinerNameText") for b in page)
        if len(page) < 50:
            break
    return [n for n, k in sorted(names.items(), key=lambda t: (-t[1], t[0] or "")) if n and n not in exclude]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["own", "control"], default="own")
    ap.add_argument("--scope", choices=["test_core", "test"], default="test_core")
    ap.add_argument("--per-examiner", type=int, default=30)
    ap.add_argument("--max-tries", type=int, default=90, help="max candidates screened per examiner")
    ap.add_argument("--min-usable", type=int, default=20, help="control examiner needs this many before the cutoff")
    ap.add_argument("--only", type=int, default=0, help="test run: first N examiners only")
    ap.add_argument("--dry-run", action="store_true", help="no API calls: print examiners and signer checks")
    ap.add_argument("--redo", action="append", default=[], metavar="NAME",
                    help="download this examiner's own job again (exact-name rule); the new job line replaces the old")
    ap.add_argument("--refresh-cases", action="store_true",
                    help="re-resolve examiners/control art units; keeps control picks of unchanged cases")
    a = ap.parse_args()

    idx, exs, sample_apps, sample_fams, linked = load_sample()
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT / "fetch_log.jsonl", "a")
    s = None
    if not a.dry_run:
        import odp_fetch as F
        key = os.environ.get("USPTO_API_KEY") or sys.exit("USPTO_API_KEY is not set. Run:  source ~/.zshrc")
        s = F.requests.Session()
        s.headers["X-API-KEY"] = key
    cp = OUT / "cases.json"
    cases = json.loads(cp.read_text()) if cp.exists() else {}
    if not cases or a.dry_run or a.refresh_cases:
        old = cases
        cases = resolve_examiners(exs, idx, a.scope, s, log, a.dry_run)
        for k, c in cases.items():          # keep a control pick only if examiner and control art unit are unchanged
            o = old.get(k) or {}
            if o.get("examiner") == c["examiner"] and (o.get("control_art_unit") or o.get("o1_art_unit")) == c["control_art_unit"]:
                c.update({f: o[f] for f in o if f.startswith("control_") and f not in ("control_art_unit", "control_art_unit_source")})
            elif o:
                print("re-resolved:", k, o.get("examiner"), "->", c["examiner"], "| control art unit",
                      o.get("control_art_unit") or o.get("o1_art_unit"), "->", c["control_art_unit"], flush=True)
        if not a.dry_run:
            cp.write_text(json.dumps(cases, indent=1))
    by_ex = {}
    for c in cases.values():
        if c["examiner"]:
            by_ex.setdefault(c["examiner"], []).append(c)
    order = sorted(by_ex, key=lambda n: (min(c["cutoff"] for c in by_ex[n]), n))
    if a.dry_run:
        print(f"examples: {len(cases)}  examiners: {len(by_ex)}  sample apps: {len(sample_apps)}  "
              f"sample families: {len(sample_fams)}  linked apps: {len(linked)}")
        print("signer_source:", Counter(c["signer_source"] for c in cases.values()))
        print("O1 art unit source:", Counter(c["o1_art_unit_source"] for c in cases.values()))
        print("O1 art unit != today's art unit:", sum(c["o1_art_unit"] != exs[c["app_id"]]["art_unit"] for c in cases.values()))
        for c in cases.values():
            if c["signer_source"] != "o1_signature" or c["o1_signer_found_by"] != "directed_to" or c["control_art_unit"] != c["o1_art_unit"]:
                print("  ", c["app_id"], c["signer_source"], c["o1_signer_found_by"], "| today:", c["odp_current_examiner"],
                      "| O1 signer:", c["o1_signer"], "| control AU:", c["control_art_unit"], c["control_art_unit_source"])
        multi = {n: [c["app_id"] for c in v] for n, v in by_ex.items() if len(v) > 1}
        print("examiners with several examples:", multi)
        return

    jp = OUT / "jobs.jsonl"
    done = {f"{r['role']}|{r['examiner']}|{r['cutoff']}": r for r in map(json.loads, open(jp))} if jp.exists() else {}
    done = {k: r for k, r in done.items() if r["examiner"] not in a.redo}
    jobs_f = open(jp, "a")
    fx = Fetcher(s, log)
    sample = (sample_apps, sample_fams, linked)
    unresolved = [c["app_id"] for c in cases.values() if not c["examiner"]]
    if unresolved:
        print("WARNING: O1 signer not found in ODP for", unresolved, "- these examples are skipped; check by hand", flush=True)
    t0 = time.time()
    if a.phase == "own":
        todo = order[:a.only] if a.only else order
        for i, n in enumerate(todo, 1):
            cs = by_ex[n]
            rec = run_job(fx, "own", n, min(c["cutoff"] for c in cs), max(c["cutoff"] for c in cs),
                          [c["app_id"] for c in cs], a.per_examiner, a.max_tries, sample, jobs_f, done)
            print(f"[{i}/{len(todo)}] {eid(n)} cases={len(cs)} search={rec['n_search']} screened={rec['n_screened']} "
                  f"usable={rec['n_usable']} | {(time.time() - t0) / i / 60:.1f} min/examiner", flush=True)
    else:
        own = {r["examiner"]: r for r in done.values() if r["role"] == "own"}
        todo = sorted(cases.values(), key=lambda c: c["cutoff"])
        todo = todo[:a.only] if a.only else todo
        for i, c in enumerate(todo, 1):
            if c.get("control_examiner") or not c["examiner"]:
                continue
            me, au, cut = c["examiner"], c.get("control_art_unit") or c["o1_art_unit"], c["cutoff"]
            pick = None
            for level, match in (("art_unit", lambda x: x == au), ("work_group", lambda x: x[:3] == au[:3])):
                peers = sorted((p for p in cases.values() if p["examiner"] and p["examiner"] != me
                                and match(p.get("control_art_unit") or p["o1_art_unit"]) and p["examiner"] in own
                                and usable_before(own[p["examiner"]], cut) >= a.min_usable),
                               key=lambda p: hashlib.sha1((c["app_id"] + p["examiner"]).encode()).hexdigest())
                if peers:
                    pick = (peers[0]["examiner"], level + " (test examiner)", own[peers[0]["examiner"]]); break
                if level == "art_unit":
                    for n in au_search(fx, au, cut, {me, c["odp_current_examiner"]})[:3]:
                        rec = run_job(fx, "control", n, cut, cut, [c["app_id"]], a.per_examiner, a.max_tries,
                                      sample, jobs_f, done)
                        if rec["n_usable"] >= a.min_usable:
                            pick = (n, "art_unit (ODP search)", rec); break
                    if pick:
                        break
            if pick:
                c.update(control_examiner=pick[0], control_examiner_id=eid(pick[0]), control_level=pick[1],
                         control_usable_before_cutoff=usable_before(pick[2], cut))
            else:
                c.update(control_examiner=None, control_level="none_found")
            cp.write_text(json.dumps(cases, indent=1))
            print(f"[{i}/{len(todo)}] {c['app_id']} AU {au}: control={c.get('control_examiner_id')} "
                  f"level={c['control_level']} | {(time.time() - t0) / i / 60:.1f} min/case", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
