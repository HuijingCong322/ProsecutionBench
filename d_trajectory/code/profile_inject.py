"""Phase 2 (examiner personalization): load the team's frozen v4 profiles and check every hash before any API call.

The team package B_D_C_phase1_v4_reviewed (release B_D_C_v4_reviewed_2026_11_02) holds
    RELEASE_MANIFEST.json      release id + sha256 of profile_manifest.csv
    profile_manifest.csv       one row per (sample_id, setting): file sha1, profile_text sha1, card_sha1, retrieved_k
    candidate_profiles/<setting>/<sample_id>.json   the profile; only its "profile_text" goes to the model

Rules (team, 2026-11-03): use only this package, send only profile_text, record the hashes in every output.
Any hash mismatch stops the run (no silent fallback to "no profile").
"""
import csv, hashlib, json, os

RELEASE_ID = "B_D_C_v4_reviewed_2026_11_02"
SETTINGS = ("own", "mismatched", "artunit")
MODES = ("full", "examples_only")
# Addendum A (2026-11-03, decided after the GPT full-profile results; see personalization_protocol.md section 9):
# "examples_only" removes the "Historical statistics" section, i.e. every examiner statistic that is defined like a
# task target (median days to the next letter, rounds distribution, allowed/abandoned within 12/24 months), and the
# one sentence that tells the reader how to read those statistics. Everything else in profile_text is unchanged.
STATS_START = "\n\nHistorical statistics\n"
EXAMPLES_START = "\n\nRetrieved historical episodes\n"
STATS_SENTENCE = "Read each statistic with its stated denominator, time window, and raw or adjusted definition. "


def derive_text(text, mode):
    if mode == "full":
        return text
    a, b = text.find(STATS_START), text.find(EXAMPLES_START)
    if not (0 < a < b) or text.count(STATS_START) != 1 or text.count(EXAMPLES_START) != 1:
        raise SystemExit("profile_text layout not as expected; cannot remove the statistics section")
    if text.count(STATS_SENTENCE) != 1:
        raise SystemExit("statistics reading sentence not found exactly once")
    out = (text[:a] + text[b:]).replace(STATS_SENTENCE, "")
    for leak in ("Statistics for this examiner", "median", "within 24 months", "Further rejections after"):
        if leak in out:
            raise SystemExit(f"examples_only text still contains '{leak}'")
    return out


def _sha1_bytes(b):
    return hashlib.sha1(b).hexdigest()


def load_profiles(pkg, setting, mode="full"):
    """pkg = the unzipped B_D_C_phase1_v4_reviewed folder. Returns ({sample_id: info}, release_info)."""
    if mode not in MODES:
        raise SystemExit(f"--profile-mode must be one of {MODES}")
    if setting not in SETTINGS:
        raise SystemExit(f"--profile-setting must be one of {SETTINGS}")
    rel = json.load(open(os.path.join(pkg, "RELEASE_MANIFEST.json"), encoding="utf-8"))
    if rel.get("release_id") != RELEASE_ID:
        raise SystemExit(f"Wrong profile package: release_id {rel.get('release_id')} (expected {RELEASE_ID})")
    man_path = os.path.join(pkg, "profile_manifest.csv")
    man_sha256 = hashlib.sha256(open(man_path, "rb").read()).hexdigest()
    if man_sha256 != rel["profile_manifest_sha256"]:
        raise SystemExit("profile_manifest.csv does not match RELEASE_MANIFEST.json (sha256). Re-download the package.")
    out = {}
    for row in csv.DictReader(open(man_path, encoding="utf-8")):
        if row["setting"] != setting:
            continue
        path = os.path.join(pkg, row["profile_path"])
        raw = open(path, "rb").read()
        if _sha1_bytes(raw) != row["profile_sha1"]:
            raise SystemExit(f"Profile file hash mismatch: {row['profile_path']}")
        p = json.loads(raw.decode("utf-8"))
        text = p["profile_text"]
        if _sha1_bytes(text.encode("utf-8")) != row["profile_text_sha1"] or p.get("profile_text_sha1") != row["profile_text_sha1"]:
            raise SystemExit(f"profile_text hash mismatch: {row['profile_path']}")
        if p["sample_id"] != row["sample_id"] or p["setting"] != setting or p["cutoff"] != row["cutoff"]:
            raise SystemExit(f"Profile id/setting/cutoff mismatch: {row['profile_path']}")
        sent = derive_text(text, mode)
        out[row["sample_id"]] = dict(text=sent, sent_text_sha1=_sha1_bytes(sent.encode("utf-8")),
                                     example_days=[int(x["elapsed_days"]) for x in p.get("retrieved_cases") or []],
                                     profile_sha1=row["profile_sha1"], profile_text_sha1=row["profile_text_sha1"],
                                     card_sha1=row["card_sha1"], retrieved_k=int(row["retrieved_k"]), cutoff=row["cutoff"],
                                     token_count=int(row["token_count"]))
    if not out:
        raise SystemExit(f"No profiles for setting {setting} in {man_path}")
    info = dict(release_id=rel["release_id"], profile_manifest_sha256=man_sha256,
                profile_block_sha1=rel.get("prompt_sha1"), profile_setting=setting, profile_mode=mode, n_profiles=len(out))
    return out, info


def check_case(prof, rec):
    """The profile must exist and be cut at the same A1 cutoff as the case."""
    if prof is None:
        return "no profile for this case"
    if prof["cutoff"] != rec["cutoff"]:
        return f"profile cutoff {prof['cutoff']} != case cutoff {rec['cutoff']}"
    return None


def fields(prof, info):
    """What every output row / cache record keeps about the profile."""
    extra = {} if info["profile_mode"] == "full" else dict(profile_mode=info["profile_mode"],
                                                           sent_text_sha1=prof["sent_text_sha1"])
    return dict(**extra, profile_release=info["release_id"], profile_setting=info["profile_setting"],
                profile_manifest_sha256=info["profile_manifest_sha256"], profile_sha1=prof["profile_sha1"],
                profile_text_sha1=prof["profile_text_sha1"], card_sha1=prof["card_sha1"],
                retrieved_k=prof["retrieved_k"])
