"""Independent check of share/profile_corpus_v2.zip (written separately from v2_profile_package.py; shares no code).
Reads only the zip, plus data_v1 examples (sample ids, families, O1 texts) and the raw continuity/search records of the
profile applications for an independent family recomputation.  Usage: python3 verify_profile_zip.py <examinerbench dir>"""
import csv, hashlib, io, json, random, re, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path

R = Path(sys.argv[1])
Z = zipfile.ZipFile(R / "share" / "profile_corpus_v2.zip")
D = R / "data_v1"
fails, notes = [], []


def F(msg):
    fails.append(msg)


def read(p):
    return Z.read("profile_corpus/" + p)


def table(p):
    return list(csv.DictReader(io.StringIO(read(p).decode())))


# A. zip integrity + manifest
bad = Z.testzip()
if bad:
    F(f"zip CRC error in {bad}")
names = [n for n in Z.namelist() if not n.endswith("/")]
man = {r["path"]: r for r in table("MANIFEST.csv")}
listed = {"profile_corpus/" + p for p in man} | {"profile_corpus/MANIFEST.csv"}
if set(names) != listed:
    F(f"zip files vs MANIFEST differ: {len(set(names) ^ listed)} paths")
for p, r in man.items():
    b = read(p)
    if hashlib.sha1(b).hexdigest() != r["sha1"] or len(b) != int(r["bytes"]):
        F(f"sha1/size mismatch {p}")
notes.append(f"A. zip: {len(names)} files, CRC ok={bad is None}, manifest checked")

# sample (the 1,000 examples)
exs = {p.stem: json.loads(p.read_text()) for p in (D / "examples").glob("*.json")}
s_apps = set(exs)
s_fams = {e.get("family_id") or a for a, e in exs.items()}
rel = set()
for a in exs:
    cp = D / "apps" / a / "raw" / "continuity.json"
    for b in (json.loads(cp.read_text()).get("patentFileWrapperDataBag") or []) if cp.exists() else []:
        for bag in ("parentContinuityBag", "childContinuityBag"):
            for x in b.get(bag) or []:
                rel |= {x.get("parentApplicationNumberText"), x.get("childApplicationNumberText")}
rel.discard(None)
test_core = {a for a, e in exs.items() if e.get("test_core")}

# B. cases.csv
cases = table("cases.csv")
idx = table("profile_index.csv")
by_ex = defaultdict(list)
for r in idx:
    by_ex[r["examiner_id"]].append(r)
if {c["sample_id"] for c in cases} != test_core or len(cases) != 100:
    F("cases.csv is not exactly the 100 test_core examples")
for c in cases:
    if c["cutoff"] != exs[c["sample_id"]]["cutoff"]:
        F(f"{c['sample_id']}: cutoff differs from the example")
    if not c["control_examiner_id"] or c["control_examiner_id"] == c["examiner_id"]:
        F(f"{c['sample_id']}: control examiner missing or equal to own")
    for k, col in (("examiner_id", "n_own_usable_before_cutoff"), ("control_examiner_id", "n_control_usable_before_cutoff")):
        n = sum(1 for r in by_ex.get(c[k], []) if r["first_signed_action"] < c["cutoff"])
        if n != int(c[col]):
            F(f"{c['sample_id']}: {col}={c[col]} but index gives {n}")
    if int(c["n_control_usable_before_cutoff"]) < 20:
        F(f"{c['sample_id']}: control has < 20 usable")
own_n = sorted(int(c["n_own_usable_before_cutoff"]) for c in cases)
notes.append(f"B. cases: 100 test_core, own usable before cutoff min {own_n[0]} / median {own_n[50]} / >=30: "
             f"{sum(n >= 30 for n in own_n)}; control min {min(int(c['n_control_usable_before_cutoff']) for c in cases)}")

# C. profile_index: one examiner per app, folders, families (recomputed from raw continuity)
apps_in_zip = {n.split("/")[2] for n in names if n.startswith("profile_corpus/apps/")}
cnt = Counter(r["app_id"] for r in idx)
if any(v > 1 for v in cnt.values()):
    F(f"apps under several examiners: {[a for a, v in cnt.items() if v > 1][:5]}")
if set(cnt) != apps_in_zip:
    F("profile_index apps != apps/ folders")
for r in idx:
    a = r["app_id"]
    cont = json.loads((D / "profile_corpus" / "apps" / a / "raw" / "continuity.json").read_text())
    par = {x.get("parentApplicationNumberText") for b in cont.get("patentFileWrapperDataBag") or []
           for x in b.get("parentContinuityBag") or []} - {None}
    root = min(par | {a})
    if root != r["family_root"]:
        F(f"{a}: family_root {r['family_root']} != recomputed {root}")
    if a in s_apps or root in s_fams or par & s_apps or a in rel:
        F(f"{a}: related to a sample application")
notes.append(f"C. index: {len(idx)} apps, one examiner each, families recomputed, none related to the 1,000 examples")

# D. dates: everything before the latest cutoff of the cases that use the examiner
lim = defaultdict(str)
for c in cases:
    for k in ("examiner_id", "control_examiner_id"):
        lim[c[k]] = max(lim[c[k]], c["cutoff"])
ex_of = {r["app_id"]: r["examiner_id"] for r in idx}
pub = {r["app_id"]: r["pgpub_date"] for r in idx}
n_files = Counter()
for n in names:
    if not n.startswith("profile_corpus/apps/"):
        continue
    _, _, a, *rest = n.split("/")
    L = lim[ex_of[a]]
    f = rest[-1]
    if f in ("transactions.csv", "catalog.csv"):
        rows = list(csv.reader(io.StringIO(Z.read(n).decode())))[1:]
        late = [x for x in rows if not x[0] or x[0][:10] >= L]
        if late:
            F(f"{a}/{f}: {len(late)} rows dated >= {L}")
        n_files[f] += 1
    elif re.match(r"\d{4}-\d{2}-\d{2}_", f):
        if f[:10] >= L:
            F(f"{a}/{f}: dated >= {L}")
        if Z.getinfo(n).file_size == 0:
            if f.endswith(".substantive.txt"):
                n_files["empty_substantive (form paragraphs only)"] += 1
            else:
                F(f"{a}/{f}: empty file")
        if f.endswith(".json"):
            json.loads(Z.read(n))
        n_files["dated_text"] += 1
    elif f.startswith("pgpub_"):
        if not (pub[a] and pub[a] < L):
            F(f"{a}/{f}: PGPUB published {pub[a]} not before {L}")
        n_files["pgpub"] += 1
    else:
        F(f"unexpected file {n}")
for r in idx:
    if r["first_signed_action"] >= lim[r["examiner_id"]]:
        F(f"{r['app_id']}: first signed action not before the latest cutoff")
notes.append(f"D. dates: {dict(n_files)} checked, all before the latest cutoff of their examiner")

# E. actions.csv consistent with the index
acts = table("actions.csv")
first = defaultdict(str)
for x in acts:
    if x["date"] >= lim[x["examiner_id"]]:
        F(f"action {x['doc_id']} dated >= cutoff")
    if x["signed_by_this_examiner"] == "true" and (not first[x["app_id"]] or x["date"] < first[x["app_id"]]):
        first[x["app_id"]] = x["date"]
for r in idx:
    if first[r["app_id"]] != r["first_signed_action"]:
        F(f"{r['app_id']}: first_signed_action {r['first_signed_action']} != actions.csv {first[r['app_id']]}")
notes.append(f"E. actions: {len(acts)} rows, first signed action consistent for every app")

# F. no names, no status
cj = json.loads((D / "profile_corpus" / "cases.json").read_text())
people = {x["examiner"] for x in cj.values()} | {x.get("control_examiner") for x in cj.values()} - {None}
for p in ("cases.csv", "profile_index.csv", "actions.csv", "checks.json", "README.md"):
    body = read(p).decode().upper()
    hit = [n for n in people if n.upper() in body]
    if hit:
        F(f"{p} contains examiner names {hit[:3]}")
    if "APPLICATIONSTATUS" in body.replace("_", ""):
        F(f"{p} mentions ODP status fields")
notes.append("F. no examiner names in csv/json/README, no ODP status fields")

# G. identity end to end: examiner_id <-> name, and signer of sampled profile actions vs that name (last name)
eid = lambda s: "ex_" + hashlib.sha1(s.encode()).hexdigest()[:10]
name_of = {}
for a, x in cj.items():
    name_of[eid(x["examiner"])] = x["examiner"]
    if x.get("control_examiner"):
        name_of[eid(x["control_examiner"])] = x["control_examiner"]
for c in cases:
    if name_of.get(c["examiner_id"]) != cj[c["sample_id"]]["examiner"]:
        F(f"{c['sample_id']}: examiner_id does not hash to the resolved examiner")
SIG = re.compile(r"directed(?: to)?\s+(?:examiner\s+)?([A-Z][A-Za-z.'()\- ]{2,60}?)\s*(?:,|whose|at telephone|at \(|who)")
rng = random.Random(20261027)
checked = mism = 0
for x, rows in sorted(by_ex.items()):
    last = re.sub(r"[^A-Z]", "", name_of[x].split(",")[0].replace(" JR", "").replace(" III", "").upper())
    for r in rng.sample(rows, min(3, len(rows))):
        f = [n for n in names if n.startswith(f"profile_corpus/apps/{r['app_id']}/text/{r['first_signed_action']}_CT")
             and n.endswith(".txt") and not n.endswith("substantive.txt")]
        if not f:
            F(f"{r['app_id']}: no text for the first signed action"); continue
        m = SIG.findall(re.sub(r"\s+", " ", Z.read(f[0]).decode(errors="ignore")))
        checked += 1
        if not m or last not in re.sub(r"[^A-Z ]", "", m[-1].upper()).split() + [re.sub(r"[^A-Z]", "", m[-1].upper())[-len(last):]]:
            mism += 1
            notes.append(f"   check by hand: {r['app_id']} examiner {name_of[x]} / signer {m[-1] if m else None}")
notes.append(f"G. identity: {checked} sampled first signed actions, {mism} without the examiner's last name")
for c in cases:          # the case's own O1 signer vs the examiner we profile
    e = exs[c["sample_id"]]
    t = (D / next(i["text_path"] for i in e["inputs"] if i.get("role") == "O1")).read_text(errors="ignore")
    m = SIG.findall(re.sub(r"\s+", " ", t))
    last = re.sub(r"[^A-Z]", "", name_of[c["examiner_id"]].split(",")[0].upper())
    if m and last not in re.sub(r"[^A-Z]", "", m[-1].upper()) and c["signer_source"] == "o1_signature":
        notes.append(f"   check by hand: case {c['sample_id']} O1 signer {m[-1]} vs {name_of[c['examiner_id']]}")

print("\n".join(notes))
print(f"\nFAILURES: {len(fails)}")
for f in fails[:40]:
    print("  ", f)
