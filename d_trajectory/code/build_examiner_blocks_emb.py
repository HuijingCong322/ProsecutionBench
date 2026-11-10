"""profile_with_embedding: build the three examiner blocks (no API, deterministic).

    python build_examiner_blocks_emb.py --bpkg path/to/profile_bgem3_v1_shared_2026_11_05 \
        --corpus path/to/profile_corpus_v2.zip --out path/to/D_trajectory/inputs/examiner_blocks_emb_v1.jsonl

Inputs
  B's package B_shared_BGE_M3_dense_v1_2026_11_05 (unzipped folder profile_bgem3_v1_shared_2026_11_05):
    ranking_top3_links_before_review.csv  the top-3 past applications per case, ranked by BGE-M3 cosine similarity
                                          between this case's abstract + claims (before its cutoff) and each past
                                          application's abstract + claims; at most one per patent family.
                                          The raw top-3 is used for every case, so all 100 cases follow one rule.
                                          (B's later review removed 47 examples in the 10 cases it reviewed by hand;
                                          that review covered only those 10 cases.)
    full_ranking.csv                      every searchable past application of the examiner, with its score
                                          (stored with each one's events; topk_math.py reads the top-3 from it)
    candidate_profiles/<variant>/<id>.json + profile_manifest.csv
                                          only the field statistics_text is used: the team's frozen statistics card
                                          of the examiner (the same text as in B_D_C_phase1_v4_reviewed)
  A's profile_corpus_v2.zip: each past application's transactions.csv, catalog.csv and text/ files.

For each test_core case and each version (own = this case's examiner, mismatched = another examiner of the same art
unit), three blocks are written. Each one goes into {profile} of the frozen *_profile.txt prompts:
  card     statistics only: the examiner's statistics card, computed from all of the examiner's past applications
           before the cutoff, with its reading notes. No past-application examples.
  paths    the dated event list of each of the top-3 past applications, cut at the case's cutoff, and its status on
           that date (the same renderer and event codes as build_examiner_histories.py). No statistics.
  fulldoc  for each of the top-3 past applications: its abstract and claims as published (only if published before
           the cutoff), then every document A downloaded for it dated before the cutoff, in full and oldest first
           (examiner letters, applicant replies and remarks, claim listings; the raw USPTO text, the same kind of
           text the case's own record uses), then the same dated event list and status as "paths". Nothing is
           summarised or shortened. No statistics.
Also stored per case and version: the top-3 ids, families and scores, and the event lists of every searchable
candidate (topk_math.py uses the same events as the LLM blocks).
"""
import argparse, csv, hashlib, io, json, os, re, zipfile
from build_examiner_histories import events_for, status, LETTERS, REPLIES  # noqa  same events as phase 2

RELEASE = "B_shared_BGE_M3_dense_v1_2026_11_05"
VARIANTS = ("own", "mismatched")
DOC_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)_([A-Z0-9]+)\.txt$")


def sha1(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Corpus:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = set(self.z.namelist())
        self.pgpub = {}
        for r in csv.DictReader(io.StringIO(self.z.read("profile_corpus/profile_index.csv").decode("utf-8"))):
            self.pgpub[r["app_id"]] = r.get("pgpub_date") or ""

    def read(self, name):
        return self.z.read(name).decode("utf-8", "replace")

    def catalog(self, app):
        raw = self.read(f"profile_corpus/apps/{app}/catalog.csv")
        return {r["doc_id"]: r for r in csv.DictReader(io.StringIO(raw))}

    def documents(self, app, cutoff):
        """Every text document of the application dated strictly before the cutoff, oldest first."""
        base = f"profile_corpus/apps/{app}/text/"
        files = sorted(n[len(base):] for n in self.names if n.startswith(base) and "/" not in n[len(base):])
        cat = self.catalog(app)
        docs = []
        pg = self.pgpub.get(app, "")
        if pg and pg < cutoff:
            if "pgpub_abstract.txt" in files:
                docs.append(dict(date=pg, doc_id="pgpub_abstract", doc_code="ABST", role="pre_grant_publication",
                                 source="pgpub_xml", text=self.read(base + "pgpub_abstract.txt").strip()))
            if "pgpub_claims.json" in files:
                claims = json.loads(self.read(base + "pgpub_claims.json"))
                text = "\n".join(c["text"] if str(c["text"]).lstrip().startswith(f"{c['number']}.") else f"{c['number']}. {c['text']}"
                                 for c in claims)
                docs.append(dict(date=pg, doc_id="pgpub_claims", doc_code="CLM", role="pre_grant_publication",
                                 source="pgpub_xml", text=text.strip()))
        for f in files:
            if f.endswith(".claims.json") or f.endswith(".substantive.txt") or f.startswith("pgpub"):
                continue  # .claims.json repeats the CLM text; .substantive repeats the letter without form paragraphs
            m = DOC_RE.match(f)
            if not m or m.group(1) >= cutoff:
                continue
            d, did = m.group(1), m.group(3)
            c = cat.get(did, {})
            role = {"OUTGOING": "examiner", "INCOMING": "applicant"}.get(c.get("direction", ""), "record")
            docs.append(dict(date=d, doc_id=did, doc_code=c.get("doc_code") or m.group(2).replace("_", "."),
                             role=role, source="uspto_xml", text=self.read(base + f).strip()))
        docs.sort(key=lambda x: (x["date"], 0 if x["role"] == "pre_grant_publication" else 1, x["doc_id"]))
        return docs


def event_lines(ev, cutoff):
    L = [f"- {e['date']} {e['label']}" for e in ev] or ["- no examiner letters or applicant replies before the cutoff"]
    return L + [f"Status on {cutoff}: {status(ev)}."]


CARD_FOOT = ("Use this reference to inform the task while grounding the prediction in the current application's "
             "record. Read each statistic with its stated denominator, time window, and raw or adjusted definition. "
             "Pending or censored outcomes remain unknown at the cutoff. The downloaded reference sample may not "
             "represent the examiner's full workload.")

FOOT = ("Use this reference to inform the task while grounding the prediction in the current application's record. "
        "Pending outcomes remain unknown at the cutoff. These few applications may not represent the examiner's full "
        "workload.")


def card_text(cutoff, stats):
    """Statistics only: the frozen statistics text of the examiner (all past applications before the cutoff)."""
    return (f"Examiner history reference available before {cutoff}\n\nHistorical statistics\n{stats.strip()}\n\n"
            f"{CARD_FOOT}\n")


def paths_text(cutoff, apps):
    L = [f"Examiner history reference available before {cutoff}", "",
         "Past applications of this examiner (other patent families), the ones most similar to this application by the "
         "text of their abstract and claims. Each list shows the dated prosecution events of one application, only "
         f"events before {cutoff}. Nothing after that date is shown.", ""]
    if not apps:
        L.append("No past applications are supplied for this examiner.")
    for i, x in enumerate(apps, 1):
        L.append(f"Past application {i}: {x['app_id']}")
        L += event_lines(x["events"], cutoff)
        L.append("")
    L.append(FOOT)
    return "\n".join(L).strip() + "\n"


def fulldoc_text(cutoff, apps):
    L = [f"Examiner history reference available before {cutoff}", "",
         "Past applications of this examiner (other patent families), the ones most similar to this application by the "
         "text of their abstract and claims. For each application: its documents in full, oldest first, each starting "
         "with a header line [doc_id | document code | date | role | text source], then its dated prosecution events "
         f"and its status. Only documents and events dated before {cutoff} are shown. The text is machine-extracted, so "
         "ignore spacing, line-break and recognition artifacts.", ""]
    if not apps:
        L.append("No past applications are supplied for this examiner.")
    for i, x in enumerate(apps, 1):
        L.append(f"=== Past application {i}: {x['app_id']} ===")
        L.append("Documents:")
        if not x["docs"]:
            L.append("(no document text before the cutoff)")
        for d in x["docs"]:
            L.append(f"[{d['doc_id']} | {d['doc_code']} | {d['date']} | {d['role']} | {d['source']}]")
            L.append(d["text"])
            L.append("")
        L.append("Dated events:")
        L += event_lines(x["events"], cutoff)
        L.append("")
    L.append(FOOT)
    return "\n".join(L).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpkg", required=True, help="unzipped profile_bgem3_v1_shared_2026_11_05 folder")
    ap.add_argument("--corpus", required=True, help="A's profile_corpus_v2.zip")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rel = json.load(open(os.path.join(a.bpkg, "RELEASE_MANIFEST.json"), encoding="utf-8"))
    if rel.get("release_id") != RELEASE:
        raise SystemExit(f"Not B's {RELEASE} package (release {rel.get('release_id')})")
    corpus = Corpus(a.corpus)
    top = read_csv(os.path.join(a.bpkg, "ranking_top3_links_before_review.csv"))
    full = read_csv(os.path.join(a.bpkg, "full_ranking.csv"))
    man = {(r["sample_id"], r["variant"]): r for r in read_csv(os.path.join(a.bpkg, "profile_manifest.csv"))}
    cases = sorted({(r["sample_id"], r["cutoff"]) for r in full if r["variant"] in VARIANTS} |
                   {(r["sample_id"], r["cutoff"]) for r in top if r["variant"] in VARIANTS})
    rows, n_docs, n_chars = [], 0, 0
    for sid, cutoff in cases:
        for v in VARIANTS:
            m = man[(sid, v)]
            if m["cutoff"] != cutoff:
                raise SystemExit(f"cutoff mismatch {sid} {v}")
            raw = open(os.path.join(a.bpkg, m["profile_path"]), "rb").read()
            if hashlib.sha1(raw).hexdigest() != m["profile_sha1"]:
                raise SystemExit(f"B profile file hash mismatch {sid} {v}")
            prof = json.loads(raw.decode("utf-8"))
            stats = prof["statistics_text"]
            if sha1(stats) != prof["statistics_text_sha1"] or prof["cutoff"] != cutoff \
                    or f"before {cutoff}:" not in stats.splitlines()[0]:
                raise SystemExit(f"statistics text check failed {sid} {v}")
            t3 = sorted([r for r in top if r["sample_id"] == sid and r["variant"] == v], key=lambda r: int(r["rank"]))
            apps = []
            for r in t3:
                ev = events_for(corpus.z, r["historical_app_id"], cutoff)
                docs = corpus.documents(r["historical_app_id"], cutoff)
                assert all(e["date"] < cutoff for e in ev) and all(d["date"] < cutoff for d in docs)
                apps.append(dict(app_id=r["historical_app_id"], family=r["family_id"], rank=int(r["rank"]),
                                 similarity=round(float(r["similarity"]), 6), events=ev, docs=docs))
                n_docs += len(docs); n_chars += sum(len(d["text"]) for d in docs)
            cands = []
            for r in sorted([r for r in full if r["sample_id"] == sid and r["variant"] == v],
                            key=lambda r: int(r["application_rank"])):
                cands.append(dict(app_id=r["app_id"], family=r["family_id"], rank=int(r["application_rank"]),
                                  similarity=round(float(r["score"]), 6), events=events_for(corpus.z, r["app_id"], cutoff)))
            ct, pt, ft = card_text(cutoff, stats), paths_text(cutoff, apps), fulldoc_text(cutoff, apps)
            rows.append(dict(sample_id=sid, variant=v, cutoff=cutoff, release=RELEASE,
                             top3=[dict(app_id=x["app_id"], family=x["family"], rank=x["rank"], similarity=x["similarity"],
                                        n_docs=len(x["docs"]), doc_ids=[d["doc_id"] for d in x["docs"]]) for x in apps],
                             candidates=cands,
                             card_text=ct, card_sha1=sha1(ct), statistics_text_sha1=prof["statistics_text_sha1"],
                             paths_text=pt, paths_sha1=sha1(pt), fulldoc_text=ft, fulldoc_sha1=sha1(ft)))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    k = [len(r["top3"]) for r in rows]
    print(f"{len(rows)} case x version rows; top-3 sizes {dict((x, k.count(x)) for x in sorted(set(k)))}; "
          f"{n_docs} documents, {n_chars:,} characters of past-application text; wrote {a.out}")
    print("file sha1:", hashlib.sha1(open(a.out, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
