"""The "examiner history reference" block added to the LLM prompt (run profile_with_embedding, 2026-11-09).

Three kinds of block (--examiner-input), each for the case's own examiner or another examiner of the same art unit
(--examiner-setting own | mismatched). All three are prebuilt by build_examiner_blocks_emb.py into
inputs/examiner_blocks_emb_v1.jsonl (file sha1 frozen below):
    card     statistics only: the examiner's statistics card from all of the examiner's past applications before the
             cutoff (the team's frozen statistics text). No past-application examples.
    paths    the 3 past applications most similar to this case by B's BGE-M3 search: their dated events, cut at the
             cutoff, and their status on that date. No statistics.
    fulldoc  the same 3 past applications in full: abstract, claims and every document before the cutoff, then their
             dated events and status. No statistics.
Outputs {M}_state_profile_with_embedding_{card,paths,fulldoc}_{own,mismatched}.
Checks before any API call (any failure stops the run; there is no silent fallback to "no examiner block"): the
blocks file's sha1, each block's own sha1 and release id, and (in check_case) that the block's cutoff equals the case's.
"""
import hashlib, json, os

SETTINGS = ("own", "mismatched")
KINDS = ("card", "paths", "fulldoc")
RELEASE = "B_shared_BGE_M3_dense_v1_2026_11_05"
BLOCKS_FILE_SHA1 = "963c00122fe59b8799e8214634b8899900977558"


def _sha1(b):
    return hashlib.sha1(b).hexdigest()


def load(kind, setting, blocks_file):
    """Returns ({sample_id: block info}, run info)."""
    if kind not in KINDS or setting not in SETTINGS:
        raise SystemExit(f"--examiner-input must be one of {KINDS}, --examiner-setting one of {SETTINGS}")
    if not blocks_file or not os.path.exists(blocks_file) or _sha1(open(blocks_file, "rb").read()) != BLOCKS_FILE_SHA1:
        raise SystemExit(f"examiner_blocks_emb file missing or not the frozen version ({blocks_file})")
    out = {}
    for x in open(blocks_file, encoding="utf-8"):
        b = json.loads(x)
        if b["variant"] != setting:
            continue
        text = b[f"{kind}_text"]
        if _sha1(text.encode("utf-8")) != b[f"{kind}_sha1"] or b["release"] != RELEASE:
            raise SystemExit(f"block hash/release mismatch: {b['sample_id']} {setting} {kind}")
        past = [] if kind == "card" else b["top3"]
        out[b["sample_id"]] = dict(cutoff=b["cutoff"], text=text, block_sha1=b[f"{kind}_sha1"],
                                   app_ids=[a["app_id"] for a in past], similarities=[a["similarity"] for a in past])
    if not out:
        raise SystemExit(f"No blocks for setting {setting}")
    return out, dict(examiner_input=kind, release_id=RELEASE, profile_setting=setting,
                     blocks_file_sha1=BLOCKS_FILE_SHA1, n_cases=len(out))


def check_case(h, rec):
    """The block must exist and be cut at the same A1 cutoff as the case."""
    if h is None:
        return "no examiner block for this case"
    if h["cutoff"] != rec["cutoff"]:
        return f"examiner block cutoff {h['cutoff']} != case cutoff {rec['cutoff']}"
    return None


def fields(h, run):
    """What every output row / cache record keeps about the examiner block."""
    return dict(profile_release=run["release_id"], profile_setting=run["profile_setting"],
                examiner_input=run["examiner_input"], blocks_file_sha1=run["blocks_file_sha1"],
                block_sha1=h["block_sha1"], past_app_ids=h["app_ids"], n_past_apps=len(h["app_ids"]),
                similarities=h["similarities"])


def cache_parts(f, run):
    """Cache-key parts: any change to the block text gives a new key."""
    return [f["profile_release"], f["profile_setting"], f["examiner_input"], f["blocks_file_sha1"], f["block_sha1"]]


def suffix(run):
    """Output tag suffix: _profile_with_embedding_<card|paths|fulldoc>_<own|mismatched>."""
    return "_profile_with_embedding_" + run["examiner_input"] + "_" + run["profile_setting"]


def add_args(ap):
    ap.add_argument("--examiner-input", default=None, choices=list(KINDS),
                    help="adds the examiner block: card = statistics from the examiner's full history only; "
                         "paths = dated events of the 3 most similar past applications (B's BGE-M3 search); "
                         "fulldoc = the same 3 past applications in full")
    ap.add_argument("--examiner-setting", default="own", choices=list(SETTINGS),
                    help="own = this case's examiner; mismatched = another examiner of the same art unit (control)")
    ap.add_argument("--blocks-file", default=None, help="default: <root>/inputs/examiner_blocks_emb_v1.jsonl")
    ap.add_argument("--ids", default=None, help="comma-separated sample_ids (format check on a few cases)")
    ap.add_argument("--dump-prompts", default=None, help="folder: write the exact messages sent, one file per case")


def blocks_path(a):
    return a.blocks_file or os.path.join(a.root, "inputs", "examiner_blocks_emb_v1.jsonl")


def active(a):
    """True when the run adds an examiner block (and so uses the *_profile.txt prompt)."""
    return a.examiner_input is not None
