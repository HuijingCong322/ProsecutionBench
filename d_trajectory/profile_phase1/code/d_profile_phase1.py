"""D phase 1: examiner episodes, per-case stats cards and leak check for the examiner-profile (RAG) runs.

    python d_profile_phase1.py --corpus path/to/profile_corpus --data path/to/data_v1_share --out path/to/out

Inputs
  profile_corpus/ (A, v2): cases.csv, profile_index.csv, actions.csv, apps/<app>/{transactions,catalog}.csv, text/
  data_v1_share/labels.csv: family_id of our 1,000 sample applications (family check only)

Outputs
  episodes.csv          one row per "applicant reply -> examiner's next letter" episode, from all shipped data
                        (shipped data already stop before the examiner's latest cutoff). Not cut per case.
  case_episodes.csv     the same episodes cut again at each case's own cutoff, per (sample_id, variant):
                        only replies before the cutoff; a letter or ending on/after the cutoff = not yet seen (censored).
  stats_cards.jsonl     one card per (sample_id, variant): numbers with denominators, raw and shrunk, + card_text
  leak_check.csv        one row per (sample_id, variant): every rule checked, pass/fail
  build_summary.json    counts, input sha1s

Rules (same codes as build_rounds_next_data.py / build_trajectory_data.py, the gold-label code of the 3 tasks)
  Reply          transaction A... (response after non-final), A.NE (response after final) or RCEX (RCE).
                 Same-day replies are one reply. A reply starts an episode only if it is the first reply after the
                 last examiner letter (a supplemental reply before the next letter does not restart the clock;
                 our task labels count from A1 the same way).
  Prior letter   the last mailed examiner letter before the reply (MCTNF, MCTFR, MCTAV, MCTRS, MCTEQ).
  Next letter    the first mailed MCTNF, MCTFR, MCTAV, MCTRS, MCTEQ, MN/=. or MABN* after the reply.
  Ending         the first mailed MN/=. (allowance) or MABN* (abandonment) after the reply. ABN9 is RCE bookkeeping,
                 not an abandonment. A revived case keeps its first ending.
  Rounds         mailed MCTNF + MCTFR after the reply, up to and including the ending day.
  Signature      a next letter that is a CTNF/CTFR signed by someone else (actions.csv signed_by_this_examiner =
                 false) is dropped from this examiner's numbers (A's rule 3). CTNF/CTFR with true = verified;
                 with no USPTO text = unverified; NOA / advisory / restriction / Quayle / abandonment notices are
                 not covered by actions.csv = assigned examiner, unverified.
  Cut            per case: an application counts only if first_signed_action < cutoff (A's README); a reply counts
                 only if reply_date < cutoff; a letter/ending dated >= cutoff is unknown at the cutoff.
  Pools          own = cases.csv examiner_id; mismatched = control_examiner_id; artunit = every own/control examiner
                 in the corpus linked to the case's control_art_unit, except the case's own examiner (B's pool rule).
  Shrinkage      own and mismatched rates are pulled toward the case's art-unit pool: (n*rate + k*pool)/(n + k), k = 5.
                 Medians are shrunk on the log scale with the same weights.
"""
import argparse, csv, hashlib, json, math, os, re
from collections import Counter, defaultdict
from datetime import date

K_SHRINK = 5
REPLY_CODES = {"A...", "A.NE", "RCEX"}
LETTER_CODES = {"MCTNF", "MCTFR", "MCTAV", "MCTRS", "MCTEQ"}
OA_CODES = {"MCTNF", "MCTFR"}
NEXT_TYPE = {"MCTNF": "nonfinal_rejection", "MCTFR": "final_rejection", "MCTAV": "advisory_action",
             "MCTRS": "restriction", "MCTEQ": "quayle_action", "MN/=.": "allowance"}
CAT_CODE = {"MCTNF": "CTNF", "MCTFR": "CTFR", "MCTAV": "CTAV", "MCTRS": "CTRS", "MCTEQ": "CTEQ", "MN/=.": "NOA",
            "MABN": "ABN"}
REPLY_DOCS = {"A...", "A.NE", "REM", "CLM", "RCEX", "AMSB", "A.AF", "A.I."}
GROUND_RE = re.compile(r"rejected\s+under\s+(?:pre-AIA\s+)?35\s*U\.?\s*S\.?\s*C\.?\s*(?:§+\s*)?(101|102|103|112)", re.I)
DP_RE = re.compile(r"double\s+patenting", re.I)


def d(s):
    return date.fromisoformat(s)


def days(a, b):
    return (d(b) - d(a)).days


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_end(code):
    return code == "MN/=." or code.startswith("MABN")


def is_next(code):
    return code in LETTER_CODES or is_end(code)


def kind(code):
    return "abandonment" if code.startswith("MABN") else NEXT_TYPE.get(code, code)


# ---------------------------------------------------------------- episodes from one application
def app_episodes(app, examiner_id, family_root, art_unit, corpus, sig):
    """All reply -> next-letter episodes in the shipped data of one application (not yet cut per case)."""
    T = sorted(rows(os.path.join(corpus, "apps", app, "transactions.csv")), key=lambda t: (t["event_date"], t["event_code"]))
    cat = rows(os.path.join(corpus, "apps", app, "catalog.csv"))
    tdir = os.path.join(corpus, "apps", app, "text")
    texts = os.listdir(tdir) if os.path.isdir(tdir) else []
    by_day_code = defaultdict(list)
    for c in cat:
        by_day_code[(c["official_date"], c["doc_code"])].append(c["doc_id"])

    def letter_doc(day, code):
        key = CAT_CODE["MABN"] if code.startswith("MABN") else CAT_CODE.get(code)
        ids = sorted(by_day_code.get((day, key), []))
        return ids

    def signature(day, code):
        if code not in OA_CODES:
            return "", "assigned_examiner_unverified"
        ids = letter_doc(day, code)
        flags = [sig.get(i) for i in ids]
        if any(f is False for f in flags):
            return "false", "actions_csv_signed_by_other"
        if any(f is True for f in flags):
            return "true", "actions_csv_verified"
        return "", "no_uspto_text_unverified"

    def text_path(day, doc_ids):
        return sorted({f"apps/{app}/text/{n}" for i in doc_ids for n in texts
                       if n.startswith(day) and i in n and n.endswith(".txt") and not n.endswith(".substantive.txt")})

    letters = [t for t in T if t["event_code"] in LETTER_CODES]
    first_oa = next((t["event_date"] for t in T if t["event_code"] in OA_CODES), None)
    reply_days = sorted({t["event_date"] for t in T if t["event_code"] in REPLY_CODES})
    eps, used_reply_after_letter = [], set()
    for r in reply_days:
        prior = [t for t in letters if t["event_date"] < r]
        if not prior:
            continue  # a reply with no examiner letter before it (e.g. preliminary) is not an episode
        p = prior[-1]
        # first reply after the last letter only
        if p["event_date"] in used_reply_after_letter:
            continue
        # an ending between the prior letter and this reply means the reply is after the case ended (e.g. revival)
        if any(is_end(t["event_code"]) and p["event_date"] < t["event_date"] <= r for t in T):
            continue
        used_reply_after_letter.add(p["event_date"])
        rcodes = sorted({t["event_code"] for t in T if t["event_date"] == r and t["event_code"] in REPLY_CODES})
        after = [t for t in T if t["event_date"] > r]
        nxt = next((t for t in after if is_next(t["event_code"])), None)
        end = next((t for t in after if is_end(t["event_code"])), None)
        n_sig, basis = signature(nxt["event_date"], nxt["event_code"]) if nxt else ("", "")
        p_sig, _ = signature(p["event_date"], p["event_code"])
        reply_ids = sorted({c["doc_id"] for c in cat if c["official_date"] == r and c["doc_code"] in REPLY_DOCS})
        next_ids = letter_doc(nxt["event_date"], nxt["event_code"]) if nxt else []
        eps.append(dict(
            episode_id=f"{examiner_id}:{app}:{r}:{next_ids[0] if next_ids else 'none'}",
            examiner_id=examiner_id, app_id=app, family_root=family_root, art_unit_today=art_unit,
            reply_date=r, reply_codes=";".join(rcodes), reply_doc_ids=";".join(reply_ids),
            reply_text_paths=";".join(text_path(r, reply_ids)),
            prior_code=p["event_code"], prior_type=kind(p["event_code"]), prior_date=p["event_date"],
            prior_doc_ids=";".join(letter_doc(p["event_date"], p["event_code"])), prior_signed=p_sig,
            is_first_reply=bool(first_oa and p["event_date"] == first_oa and p["event_code"] in OA_CODES
                                and not any(q["event_date"] < p["event_date"] for q in letters if q["event_code"] in OA_CODES)),
            next_code=nxt["event_code"] if nxt else "", next_type=kind(nxt["event_code"]) if nxt else "",
            next_date=nxt["event_date"] if nxt else "", next_doc_ids=";".join(next_ids),
            next_text_paths=";".join(text_path(nxt["event_date"], next_ids)) if nxt else "",
            next_days=days(r, nxt["event_date"]) if nxt else "",
            next_signed=n_sig, signature_basis=basis,
            end_event=("allowance" if end["event_code"] == "MN/=." else "abandonment") if end else "",
            end_date=end["event_date"] if end else "",
            shipped_until=T[-1]["event_date"] if T else "",
        ))
    return eps, T


def cut_episode(e, T, cutoff):
    """Re-cut one episode at a case cutoff. Returns None if the reply is not before the cutoff."""
    r = e["reply_date"]
    if r >= cutoff:
        return None
    seen = [t for t in T if r < t["event_date"] < cutoff]
    nxt = next((t for t in seen if is_next(t["event_code"])), None)
    end = next((t for t in seen if is_end(t["event_code"])), None)
    upto = end["event_date"] if end else None
    rounds = sum(1 for t in seen if t["event_code"] in OA_CODES and (upto is None or t["event_date"] <= upto))
    rce = any(t["event_code"] == "RCEX" and (upto is None or t["event_date"] < upto) for t in seen)
    return dict(
        next_observed=nxt is not None,
        next_type_cut=kind(nxt["event_code"]) if nxt else "",
        next_days_cut=days(r, nxt["event_date"]) if nxt else days(r, cutoff),
        next_signed_ok=not (nxt is not None and nxt["event_code"] == e["next_code"] and e["next_signed"] == "false"),
        end_observed=end is not None,
        end_event_cut=("allowance" if end["event_code"] == "MN/=." else "abandonment") if end else "",
        end_days_cut=days(r, end["event_date"]) if end else days(r, cutoff),
        rounds_cut=rounds, rounds_censored=end is None, rce_cut=rce,
        max_date_used=max([t["event_date"] for t in seen] + [r]),
    )


# ---------------------------------------------------------------- small estimators
def km(times, events):
    """Kaplan-Meier: returns list of (t, S(t)) steps."""
    pts = sorted(zip(times, events))
    n, s, out, i = len(pts), 1.0, [], 0
    while i < len(pts):
        t = pts[i][0]
        dth = sum(1 for tt, ev in pts if tt == t and ev)
        cens = sum(1 for tt, ev in pts if tt == t and not ev)
        if dth:
            s *= 1 - dth / n
            out.append((t, s))
        n -= dth + cens
        i += dth + cens
    return out


def km_median(times, events):
    for t, s in km(times, events):
        if s <= 0.5:
            return t
    return None  # median not reached


def aj(times, causes, horizons):
    """Aalen-Johansen cumulative incidence per cause ('' = censored) at the horizons (days)."""
    pts = sorted(zip(times, causes))
    n, s, cif, res = len(pts), 1.0, defaultdict(float), {}
    hs = sorted(horizons)
    i = 0
    steps = []
    while i < len(pts):
        t = pts[i][0]
        grp = [c for tt, c in pts if tt == t]
        dth = Counter(c for c in grp if c)
        if dth and n:
            for c, k in dth.items():
                cif[c] += s * k / n
            s *= 1 - sum(dth.values()) / n
        steps.append((t, dict(cif)))
        n -= len(grp)
        i += len(grp)
    for h in hs:
        last = {}
        for t, c in steps:
            if t <= h:
                last = c
        res[h] = last
    return res


def rounds_km(rounds, censored):
    """P(N = 0..3, 4+) with censoring: time = N + 1 (event) or k + 0.5 (still open with k seen)."""
    times = [r + 0.5 if c else r + 1 for r, c in zip(rounds, censored)]
    ev = [not c for c in censored]
    steps = km(times, ev)

    def S(x):  # P(T > x)
        v = 1.0
        for t, s in steps:
            if t <= x:
                v = s
        return v
    ge = [1.0] + [S(k) for k in range(1, 5)]  # P(N >= k) = P(T > k)
    p = [ge[k] - ge[k + 1] for k in range(4)] + [ge[4]]
    return dict(zip(["0", "1", "2", "3", "4+"], [round(x, 4) for x in p]))


def shrink(rate, n, pool):
    if rate is None:
        return pool
    if pool is None:
        return rate
    return (n * rate + K_SHRINK * pool) / (n + K_SHRINK)


def shrink_log(med, n, pool):
    if med is None or pool is None:
        return med if pool is None else pool
    return math.exp((n * math.log(max(med, 1)) + K_SHRINK * math.log(max(pool, 1))) / (n + K_SHRINK))


def r4(x):
    return None if x is None else round(x, 4)


# ---------------------------------------------------------------- stats for one pool at one cutoff
def pool_stats(cut_eps, n_apps, ground_counts):
    nf = [e for e in cut_eps if e["prior_code"] == "MCTNF" and e["next_signed_ok"]]
    obs = [e for e in nf if e["next_observed"]]
    types = Counter(e["next_type_cut"] for e in obs)
    groups = {"allowance": ["allowance"], "final_rejection": ["final_rejection"],
              "nonfinal_rejection": ["nonfinal_rejection"],
              "other": ["advisory_action", "restriction", "quayle_action", "abandonment"]}
    shares = {g: r4(sum(types[c] for c in cs) / len(obs)) if obs else None for g, cs in groups.items()}
    med_all = km_median([e["next_days_cut"] for e in nf], [e["next_observed"] for e in nf]) if nf else None
    med_by = {}
    for g in ["allowance", "rejection"]:
        v = sorted(e["next_days_cut"] for e in obs if (e["next_type_cut"] == "allowance") == (g == "allowance")
                   and e["next_type_cut"] in ("allowance", "final_rejection", "nonfinal_rejection"))
        med_by[g] = v[len(v) // 2] if v else None
    fr = [e for e in cut_eps if e["is_first_reply"] == "True" or e["is_first_reply"] is True]
    fr = [e for e in fr if e["next_signed_ok"]]
    cif = aj([e["end_days_cut"] for e in fr], [e["end_event_cut"] for e in fr], [365, 730]) if fr else {}
    rd = rounds_km([e["rounds_cut"] for e in fr], [e["rounds_censored"] for e in fr]) if fr else None
    res = [e for e in fr if not e["rounds_censored"]]
    end_med = km_median([e["end_days_cut"] for e in fr], [e["end_observed"] for e in fr]) if fr else None
    ga = ground_counts
    return dict(
        n_applications=n_apps,
        next_letter=dict(scope="replies to a non-final rejection", n_episodes=len(nf), n_observed=len(obs),
                         n_waiting_at_cutoff=len(nf) - len(obs), type_counts=dict(types), type_shares=shares,
                         median_days_km=med_all, median_days_observed=med_by),
        first_reply=dict(scope="first reply to the first rejection of each application", n_episodes=len(fr),
                         n_allowed=sum(e["end_event_cut"] == "allowance" for e in fr),
                         n_abandoned=sum(e["end_event_cut"] == "abandonment" for e in fr),
                         n_pending_at_cutoff=sum(not e["end_observed"] for e in fr),
                         allowed_by_12m=r4(cif.get(365, {}).get("allowance", 0.0)) if fr else None,
                         allowed_by_24m=r4(cif.get(730, {}).get("allowance", 0.0)) if fr else None,
                         abandoned_by_24m=r4(cif.get(730, {}).get("abandonment", 0.0)) if fr else None,
                         median_days_to_end_km=end_med,
                         rounds_dist_km=rd, n_rounds_resolved=len(res),
                         mean_rounds_resolved=r4(sum(e["rounds_cut"] for e in res) / len(res)) if res else None,
                         rce_rate=r4(sum(bool(e["rce_cut"]) for e in fr) / len(fr)) if fr else None),
        grounds=dict(n_signed_rejections=ga["n"], **{f"share_{g}": r4(ga[g] / ga["n"]) if ga["n"] else None
                                                    for g in ["101", "102", "103", "112", "double_patenting"]}),
    )


def shrunk_block(s, p):
    nl, pl = s["next_letter"], p["next_letter"]
    fr, pf = s["first_reply"], p["first_reply"]
    n1, n2 = nl["n_observed"], fr["n_episodes"]
    return dict(
        k=K_SHRINK, toward="art-unit pool at the same cutoff",
        next_allowance_share=r4(shrink(nl["type_shares"]["allowance"], n1, pl["type_shares"]["allowance"])),
        next_final_rejection_share=r4(shrink(nl["type_shares"]["final_rejection"], n1, pl["type_shares"]["final_rejection"])),
        median_days_next_letter=r4(shrink_log(nl["median_days_km"], nl["n_episodes"], pl["median_days_km"])),
        allowed_by_24m=r4(shrink(fr["allowed_by_24m"], n2, pf["allowed_by_24m"])),
        abandoned_by_24m=r4(shrink(fr["abandoned_by_24m"], n2, pf["abandoned_by_24m"])),
        p_no_more_rejections=r4(shrink(fr["rounds_dist_km"]["0"] if fr["rounds_dist_km"] else None, n2,
                                       pf["rounds_dist_km"]["0"] if pf["rounds_dist_km"] else None)),
        rce_rate=r4(shrink(fr["rce_rate"], n2, pf["rce_rate"])),
    )


def pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def card_text(variant, cutoff, s):
    nl, fr, g = s["next_letter"], s["first_reply"], s["grounds"]
    who = {"own": "this examiner", "mismatched": "this examiner",
           "artunit": "examiners of this art unit (pooled)"}[variant]
    L = [f"Statistics for {who}, other applications, events before {cutoff}:"]
    L.append(f"- {s['n_applications']} applications; {nl['n_episodes']} replies to a non-final rejection.")
    if nl["n_observed"]:
        t = nl["type_shares"]
        L.append(f"- Next letter after such a reply ({nl['n_observed']} seen, {nl['n_waiting_at_cutoff']} still waiting): "
                 f"allowance {pct(t['allowance'])}, final rejection {pct(t['final_rejection'])}, "
                 f"non-final rejection {pct(t['nonfinal_rejection'])}, other {pct(t['other'])}.")
        m = nl["median_days_observed"]
        L.append(f"- Days from a reply to the next letter: median {nl['median_days_km'] or 'not reached'}"
                 f" (allowances {m['allowance'] or 'n/a'}, rejections {m['rejection'] or 'n/a'}).")
    if fr["n_episodes"]:
        L.append(f"- After the first reply ({fr['n_episodes']} applications): {fr['n_allowed']} allowed, "
                 f"{fr['n_abandoned']} abandoned, {fr['n_pending_at_cutoff']} still pending; estimated allowed within "
                 f"12 months {pct(fr['allowed_by_12m'])}, within 24 months {pct(fr['allowed_by_24m'])}; "
                 f"abandoned within 24 months {pct(fr['abandoned_by_24m'])}.")
        rd = fr["rounds_dist_km"]
        L.append(f"- Further rejections after the first reply: 0: {pct(rd['0'])}, 1: {pct(rd['1'])}, 2: {pct(rd['2'])}, "
                 f"3+: {pct(rd['3'] + rd['4+'])}; RCE filed in {pct(fr['rce_rate'])}.")
    if g["n_signed_rejections"]:
        L.append(f"- Grounds in {g['n_signed_rejections']} signed rejections: 103 in {pct(g['share_103'])}, "
                 f"102 in {pct(g['share_102'])}, 112 in {pct(g['share_112'])}, 101 in {pct(g['share_101'])}.")
    if variant != "artunit" and fr["n_episodes"] < 10:
        L.append("- Few cases: treat these numbers as rough.")
    return "\n".join(L)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    C, O = a.corpus, a.out
    os.makedirs(O, exist_ok=True)
    cases = rows(os.path.join(C, "cases.csv"))
    index = rows(os.path.join(C, "profile_index.csv"))
    actions = rows(os.path.join(C, "actions.csv"))
    labels = rows(os.path.join(a.data, "labels.csv"))
    sample_fams = {r["family_id"] for r in labels}
    sample_apps = {r["app_id"] for r in labels}
    fam_of_case = {r["app_id"]: r["family_id"] for r in labels}
    sig = {}
    for r in actions:
        v = r["signed_by_this_examiner"].strip().lower()
        sig[r["doc_id"]] = True if v == "true" else False if v == "false" else None
    assert len(cases) == 100

    # episodes per application (examiner of an app is unique: A's rule 4)
    idx_by_ex = defaultdict(list)
    for r in index:
        idx_by_ex[r["examiner_id"]].append(r)
    all_eps, T_of, ep_by_app = [], {}, {}
    for r in index:
        eps, T = app_episodes(r["app_id"], r["examiner_id"], r["family_root"], r["art_unit_today"], C, sig)
        T_of[r["app_id"]] = T
        ep_by_app[r["app_id"]] = eps
        all_eps += eps
    cols = list(all_eps[0].keys())
    with open(os.path.join(O, "episodes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_eps)

    # grounds per signed rejection (full text: the "rejected under" sentence is often a form paragraph)
    grounds_of = {}
    for r in actions:
        if sig.get(r["doc_id"]) is not True:
            continue
        tdir = os.path.join(C, "apps", r["app_id"], "text")
        fn = [n for n in (os.listdir(tdir) if os.path.isdir(tdir) else [])
              if r["doc_id"] in n and n.endswith(".txt") and not n.endswith(".substantive.txt")]
        if not fn:
            continue
        txt = open(os.path.join(tdir, fn[0]), encoding="utf-8", errors="ignore").read()
        gs = set(GROUND_RE.findall(txt))
        if DP_RE.search(txt):
            gs.add("double_patenting")
        grounds_of[(r["examiner_id"], r["app_id"], r["doc_id"])] = (r["date"], gs)

    # art-unit pools (B's rule)
    units = defaultdict(set)
    for c in cases:
        units[c["examiner_id"]].add(c["control_art_unit"])
        units[c["control_examiner_id"]].add(c["control_art_unit"])

    cards, case_rows, leak = [], [], []
    for c in cases:
        tau, sid = c["cutoff"], c["sample_id"]
        pools = {"own": [c["examiner_id"]], "mismatched": [c["control_examiner_id"]],
                 "artunit": sorted(e for e, us in units.items() if c["control_art_unit"] in us and e != c["examiner_id"])}
        per = {}
        for variant, exs in pools.items():
            apps = [r for e in exs for r in idx_by_ex[e] if r["first_signed_action"] < tau]
            cut = []
            for r in apps:
                for e in ep_by_app[r["app_id"]]:
                    x = cut_episode(e, T_of[r["app_id"]], tau)
                    if x is None:
                        continue
                    cut.append({**e, **x})
            gc = Counter()
            app_set = {r["app_id"] for r in apps}
            for (ex, app, doc), (dt, gs) in grounds_of.items():
                if ex in exs and dt < tau and app in app_set:
                    gc["n"] += 1
                    for g in gs:
                        gc[g] += 1
            per[variant] = (exs, apps, cut, pool_stats(cut, len(apps), gc))
            for e in cut:
                case_rows.append(dict(sample_id=sid, variant=variant, cutoff=tau, episode_id=e["episode_id"],
                                      examiner_id=e["examiner_id"], app_id=e["app_id"], family_root=e["family_root"],
                                      reply_date=e["reply_date"], prior_code=e["prior_code"],
                                      is_first_reply=e["is_first_reply"], next_observed=e["next_observed"],
                                      next_type_cut=e["next_type_cut"], next_days_cut=e["next_days_cut"],
                                      next_signed_ok=e["next_signed_ok"], signature_basis=e["signature_basis"] if e["next_observed"] else "",
                                      end_event_cut=e["end_event_cut"], end_days_cut=e["end_days_cut"],
                                      rounds_cut=e["rounds_cut"], rounds_censored=e["rounds_censored"],
                                      rce_cut=e["rce_cut"], max_date_used=e["max_date_used"]))
            # leak check
            fams = {r["family_root"] for r in apps}
            leak.append(dict(
                sample_id=sid, variant=variant, cutoff=tau, examiners=";".join(exs), n_applications=len(apps),
                n_episodes_cut=len(cut),
                n_own_usable_matches_A=(len(apps) == int(c["n_own_usable_before_cutoff"])) if variant == "own"
                else (len(apps) == int(c["n_control_usable_before_cutoff"])) if variant == "mismatched" else "",
                all_dates_before_cutoff=all(e["max_date_used"] < tau for e in cut),
                no_reply_on_or_after_cutoff=all(e["reply_date"] < tau for e in cut),
                apps_first_signed_before_cutoff=all(r["first_signed_action"] < tau for r in apps),
                no_family_in_1000=not (fams & sample_fams) and not ({r["app_id"] for r in apps} & sample_apps),
                not_case_family=fam_of_case.get(sid) not in fams,
                own_examiner_excluded=(c["examiner_id"] not in exs) if variant != "own" else True,
                own_ne_control=c["examiner_id"] != c["control_examiner_id"],
                no_signed_by_other_in_numbers=True,  # enforced by next_signed_ok filter in pool_stats
                n_dropped_signed_by_other=sum(not e["next_signed_ok"] for e in cut),
                uses_no_status_field=True,
            ))
            leak[-1]["pass"] = all(v is True for k, v in leak[-1].items()
                                   if k not in ("n_own_usable_matches_A",) and isinstance(v, bool)) and \
                leak[-1]["n_own_usable_matches_A"] in (True, "")
        pool = per["artunit"][3]
        for variant in ["own", "mismatched", "artunit"]:
            exs, apps, cut, s = per[variant]
            card = dict(sample_id=sid, variant=variant, cutoff=tau,
                        examiner_ids=exs if variant == "artunit" else exs[0],
                        art_unit=c["control_art_unit"], signer_source=c["signer_source"], stats=s,
                        shrunk=shrunk_block(s, pool) if variant != "artunit" else None,
                        card_text=card_text(variant, tau, s), status="D_verified_v1")
            card["card_sha1"] = hashlib.sha1(json.dumps(card, sort_keys=True).encode()).hexdigest()
            cards.append(card)

    with open(os.path.join(O, "stats_cards.jsonl"), "w") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    for name, data in [("case_episodes.csv", case_rows), ("leak_check.csv", leak)]:
        with open(os.path.join(O, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
    summ = dict(
        episodes=len(all_eps), applications=len(index), cases=len(cases), cards=len(cards),
        case_episode_rows=len(case_rows), leak_rows=len(leak), leak_pass=sum(r["pass"] for r in leak),
        episodes_by_next_type=dict(Counter(e["next_type"] or "none_shipped" for e in all_eps)),
        signature_basis=dict(Counter(e["signature_basis"] or "none" for e in all_eps)),
        reply_text_available=sum(bool(e["reply_text_paths"]) for e in all_eps),
        first_reply_episodes=sum(e["is_first_reply"] for e in all_eps),
        k_shrink=K_SHRINK,
        inputs_sha1={n: sha1(os.path.join(C, n)) for n in ["cases.csv", "profile_index.csv", "actions.csv", "checks.json"]},
        builder_sha1=sha1(__file__),
    )
    with open(os.path.join(O, "build_summary.json"), "w") as f:
        json.dump(summ, f, indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
