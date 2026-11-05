"""Phase 2: the "examiner history reference" block added to the LLM prompt, with every check done before any API call.

Two kinds of block (--examiner-input), both for the case's own examiner or another examiner of the same art unit
(--examiner-setting own | mismatched):
    card     the team's full profile text from the frozen package B_D_C_phase1_v4_reviewed: the examiner's statistics
             card (from all past applications before the cutoff) + 3 short past episodes. Run 2026-11-03; outputs
             {M}_state_profile_{own,mismatched}.
    history  the full dated event lists of the same 3 past applications, cut at the case's cutoff, no statistics
             (inputs/examiner_histories_v1.jsonl, built by build_examiner_histories.py). Outputs
             {M}_state_history_{own,mismatched}.
Checks (any failure stops the run; there is no silent fallback to "no examiner block"):
    the package release id and the sha256 of its profile_manifest.csv; each profile file's sha1 and its profile_text sha1;
    history only: the history file's sha1, and for every case the same cutoff, the same application ids in the same
    order as the package, and the text sha1.
"""
import csv, hashlib, json, os

RELEASE_ID = "B_D_C_v4_reviewed_2026_11_02"
SETTINGS = ("own", "mismatched")
KINDS = ("card", "history")
HISTORY_FILE_SHA1 = "5e5eaaa9c839787c01895f48b0c3bb314df44fba"


def _sha1(b):
    return hashlib.sha1(b).hexdigest()


def load(pkg, kind, setting, history_file=None):
    """pkg = the unzipped B_D_C_phase1_v4_reviewed folder. Returns ({sample_id: info}, run_info)."""
    if kind not in KINDS or setting not in SETTINGS:
        raise SystemExit(f"--examiner-input must be one of {KINDS}, --examiner-setting one of {SETTINGS}")
    rel = json.load(open(os.path.join(pkg, "RELEASE_MANIFEST.json"), encoding="utf-8"))
    if rel.get("release_id") != RELEASE_ID:
        raise SystemExit(f"Wrong profile package: release_id {rel.get('release_id')} (expected {RELEASE_ID})")
    man_path = os.path.join(pkg, "profile_manifest.csv")
    man_sha256 = hashlib.sha256(open(man_path, "rb").read()).hexdigest()
    if man_sha256 != rel["profile_manifest_sha256"]:
        raise SystemExit("profile_manifest.csv does not match RELEASE_MANIFEST.json (sha256). Re-download the package.")
    hist = {}
    if kind == "history":
        if not history_file or not os.path.exists(history_file) or _sha1(open(history_file, "rb").read()) != HISTORY_FILE_SHA1:
            raise SystemExit(f"examiner_histories file missing or not the frozen version ({history_file})")
        for x in open(history_file, encoding="utf-8"):
            h = json.loads(x)
            if h["variant"] == setting:
                hist[h["sample_id"]] = h
    out = {}
    for row in csv.DictReader(open(man_path, encoding="utf-8")):
        if row["setting"] != setting:
            continue
        raw = open(os.path.join(pkg, row["profile_path"]), "rb").read()
        if _sha1(raw) != row["profile_sha1"]:
            raise SystemExit(f"Profile file hash mismatch: {row['profile_path']}")
        p = json.loads(raw.decode("utf-8"))
        if _sha1(p["profile_text"].encode("utf-8")) != row["profile_text_sha1"] or p.get("profile_text_sha1") != row["profile_text_sha1"]:
            raise SystemExit(f"profile_text hash mismatch: {row['profile_path']}")
        if p["sample_id"] != row["sample_id"] or p["setting"] != setting or p["cutoff"] != row["cutoff"]:
            raise SystemExit(f"Profile id/setting/cutoff mismatch: {row['profile_path']}")
        info = dict(cutoff=row["cutoff"], profile_sha1=row["profile_sha1"], profile_text_sha1=row["profile_text_sha1"],
                    card_sha1=row["card_sha1"], retrieved_k=int(row["retrieved_k"]))
        if kind == "card":
            info["text"] = p["profile_text"]
        else:
            h = hist.get(row["sample_id"])
            if h is None or h["cutoff"] != row["cutoff"] \
                    or h["source_profile_sha1"] != p.get("reviewed_candidate_file_sha1") \
                    or [x["app_id"] for x in p.get("retrieved_cases") or []] != h["app_ids"] \
                    or _sha1(h["history_text"].encode("utf-8")) != h["history_sha1"]:
                raise SystemExit(f"history does not match the frozen package: {row['sample_id']} {setting}")
            info.update(text=h["history_text"], history_sha1=h["history_sha1"], app_ids=h["app_ids"])
        out[row["sample_id"]] = info
    if not out:
        raise SystemExit(f"No profiles for setting {setting}")
    run = dict(examiner_input=kind, release_id=rel["release_id"], profile_setting=setting,
               profile_manifest_sha256=man_sha256, n_cases=len(out))
    if kind == "history":
        run["history_file_sha1"] = HISTORY_FILE_SHA1
    return out, run


def check_case(h, rec):
    """The block must exist and be cut at the same A1 cutoff as the case."""
    if h is None:
        return "no examiner block for this case"
    if h["cutoff"] != rec["cutoff"]:
        return f"examiner block cutoff {h['cutoff']} != case cutoff {rec['cutoff']}"
    return None


def fields(h, run):
    """What every output row / cache record keeps about the examiner block."""
    f = dict(profile_release=run["release_id"], profile_setting=run["profile_setting"],
             profile_manifest_sha256=run["profile_manifest_sha256"], profile_sha1=h["profile_sha1"],
             profile_text_sha1=h["profile_text_sha1"], card_sha1=h["card_sha1"], retrieved_k=h["retrieved_k"])
    if run["examiner_input"] == "history":
        f.update(examiner_input="history", history_file_sha1=run["history_file_sha1"], history_sha1=h["history_sha1"],
                 past_app_ids=h["app_ids"], n_past_apps=len(h["app_ids"]))
    return f


def cache_parts(f, run):
    """Cache-key parts. The card parts are the ones used on 2026-11-03, so those cached answers stay valid."""
    parts = [f["profile_release"], f["profile_setting"], f["profile_sha1"], f["profile_text_sha1"]]
    if run["examiner_input"] == "history":
        parts += ["history", f["history_file_sha1"], f["history_sha1"]]
    return parts


def suffix(run):
    """Output tag suffix: card -> _profile_<setting> (as on 2026-11-03), history -> _history_<setting>."""
    return ("_profile_" if run["examiner_input"] == "card" else "_history_") + run["profile_setting"]


def add_args(ap):
    ap.add_argument("--profile-pkg", default=None,
                    help="unzipped B_D_C_phase1_v4_reviewed folder; adds the examiner block to the prompt")
    ap.add_argument("--examiner-input", default="history", choices=list(KINDS),
                    help="card = the team's full profile (statistics card + 3 short episodes); "
                         "history = full event lists of the same 3 past applications, no statistics")
    ap.add_argument("--examiner-setting", default="own", choices=list(SETTINGS),
                    help="own = this case's examiner; mismatched = another examiner of the same art unit (control)")
    ap.add_argument("--history-file", default=None, help="default: <root>/inputs/examiner_histories_v1.jsonl")
    ap.add_argument("--ids", default=None, help="comma-separated sample_ids (format check on a few cases)")
    ap.add_argument("--dump-prompts", default=None, help="folder: write the exact messages sent, one file per case")


def history_path(a):
    return a.history_file or os.path.join(a.root, "inputs", "examiner_histories_v1.jsonl")
