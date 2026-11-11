"""Attach examiner profiles to data_v1 examples (offline; run after v1_profiles.py and v1_build.py).
For every example, using only profile material dated BEFORE the example's cutoff:
  examiner_profile.stats : n profile applications, n examiner actions on the merits mailed before the
      cutoff, share of final rejections among them, and the examiner's observed t=1 second-action rate
      (on profile apps whose next action after the first reply was mailed before the cutoff)
  examiner_profile.oa_texts : up to 3 most recent profile Office Actions (USPTO XML text) before the cutoff
  mismatched_profile : the same fields for a different examiner of the same technology center
      (deterministic pairing), for the mismatched-profile control
Also extracts profile XML to profiles/apps/<app>/text/. Updates examples/<app>.json in place."""
import csv, hashlib, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v1_text import blocks, read_archive, PARSER, local  # noqa: E402
from lxml import etree  # noqa: E402

D = Path(__file__).resolve().parent.parent / "data_v1"
P = D / "profiles"
CORE_REPLY = {"A...", "A.NE", "A.I.", "A.AF", "AMSB", "REM", "CLM"}


def extract(app):
    d = P / "apps" / app
    (d / "text").mkdir(exist_ok=True)
    for f in (d / "xml").glob("*.xml.bin") if (d / "xml").exists() else []:
        stem = f.name[:-len(".xml.bin")]
        out = d / "text" / f"{stem}.txt"
        if out.exists():
            continue
        try:
            root = etree.fromstring(read_archive(f), PARSER)
            out.write_text(blocks(root))
            (d / "text" / f"{stem}.substantive.txt").write_text(blocks(root, substantive=True))
        except Exception as e:
            print(app, stem, "xml error", e)


def timeline(app):
    p = P / "apps" / app / "raw" / "documents.json"
    docs = sorted(json.loads(p.read_text()).get("documentBag") or [], key=lambda x: x.get("officialDate") or "")
    ev = [((x.get("officialDate") or "")[:10], x.get("documentCode") or "", x.get("directionCategory") or "",
           x.get("documentIdentifier")) for x in docs]
    oas = [e for e in ev if e[1] in ("CTNF", "CTFR") and e[2] == "OUTGOING"]
    t1 = None
    if oas:
        o1 = oas[0][0]
        rep = next((e for e in ev if e[0] > o1 and e[2] == "INCOMING" and e[1] in CORE_REPLY), None)
        if rep:
            nxt = next((e for e in ev if e[0] > rep[0] and e[2] == "OUTGOING" and e[1] in ("CTNF", "CTFR", "NOA")), None)
            if nxt:
                t1 = (nxt[0], 1 if nxt[1] in ("CTNF", "CTFR") else 0)
    return oas, t1


def profile(apps, cutoff):
    n_act = n_final = 0
    obs = []
    texts = []
    for a in apps:
        oas, t1 = TL[a]
        for date, code, _, did in oas:
            if date < cutoff:
                n_act += 1
                n_final += code == "CTFR"
                stem = f"{date}_{code}_{did}"
                tp = P / "apps" / a / "text" / f"{stem}.txt"
                if tp.exists():
                    texts.append({"app_id": a, "date": date, "doc_code": code,
                                  "text_path": f"profiles/apps/{a}/text/{stem}.txt",
                                  "substantive_path": f"profiles/apps/{a}/text/{stem}.substantive.txt"})
        if t1 and t1[0] < cutoff:
            obs.append(t1[1])
    texts = sorted(texts, key=lambda t: t["date"], reverse=True)[:3]
    return {"stats": {"n_profile_apps": len(apps), "n_actions_before_cutoff": n_act,
                      "final_rejection_share": round(n_final / n_act, 3) if n_act else None,
                      "n_t1_outcomes_observed": len(obs),
                      "second_action_rate": round(sum(obs) / len(obs), 3) if obs else None},
            "oa_texts": texts}


idx = {}
for fn in ("index.jsonl", "index_backfill.jsonl"):   # first run + v1.1 backfill (filed before the cutoffs)
    if (P / fn).exists():
        for r in map(json.loads, open(P / fn)):
            v = idx.setdefault(r["examiner"], {"profile_apps": []})
            have = {pa["app_id"] for pa in v["profile_apps"]}
            v["profile_apps"] += [pa for pa in r["profile_apps"] if pa["app_id"] not in have]
names = {json.loads(l)["app_id"]: json.loads(l).get("examiner") for l in open(D / "index.jsonl")}
SAMPLE = [json.loads(l) for l in open(D / "index.jsonl")]
SAMPLE_APPS = {r["app_id"] for r in SAMPLE if r.get("eligible")}
SAMPLE_FAMS = {r.get("family_id") or r["app_id"] for r in SAMPLE if r.get("eligible")}


def same_family(app):
    """True when the profile app is in the family of a sample application, or its family is unknown
    (no continuity record): such apps are not used."""
    cp = P / "apps" / app / "raw" / "continuity.json"
    if not cp.exists():
        return True
    parents = []
    for b in (json.loads(cp.read_text()).get("patentFileWrapperDataBag") or [{}]):
        parents += [p.get("parentApplicationNumberText") for p in (b.get("parentContinuityBag") or [])
                    if p.get("parentApplicationNumberText")]
    return min(parents + [app]) in SAMPLE_FAMS or bool(set(parents) & SAMPLE_APPS)
TL = {}
for ex, r in idx.items():
    for pa in r["profile_apps"]:
        extract(pa["app_id"])
        try:
            TL[pa["app_id"]] = timeline(pa["app_id"])
        except Exception as e:
            print(pa["app_id"], "timeline error", e)
apps_of = {ex: [pa["app_id"] for pa in r["profile_apps"] if pa["app_id"] in TL and not same_family(pa["app_id"])]
           for ex, r in idx.items()}

exs = [json.loads(p.read_text()) for p in sorted((D / "examples").glob("*.json"))]
by_tc = {}
for e in exs:
    by_tc.setdefault(e["tc"], set()).add(names.get(e["app_id"]))
n_with = 0
for e in exs:
    ex = names.get(e["app_id"])
    e["examiner_profile"] = profile(apps_of.get(ex, []), e["cutoff"]) if ex in apps_of else None
    others = sorted(x for x in by_tc[e["tc"]] if x and x != ex and x in apps_of)
    rich = [x for x in others if sum(1 for a in apps_of[x] for o in TL[a][0] if o[0] < e["cutoff"]) >= 3]
    others = rich or others
    if others:
        mm = random.Random(int(hashlib.sha1(e["app_id"].encode()).hexdigest(), 16)).choice(others)
        e["mismatched_profile"] = dict(profile(apps_of[mm], e["cutoff"]),
                                       examiner_id="ex_" + hashlib.sha1(mm.encode()).hexdigest()[:10])
    else:
        e["mismatched_profile"] = None
    n_with += bool(e["examiner_profile"] and e["examiner_profile"]["stats"]["n_actions_before_cutoff"])
    (D / "examples" / f"{e['app_id']}.json").write_text(json.dumps(e, indent=1))
print(f"examples: {len(exs)}; with >=1 profile action before cutoff: {n_with}")
