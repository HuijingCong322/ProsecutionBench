"""Read-only integrity and review validation. Standard library only; no API calls."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--review", type=Path, help="The human-exported profile_review_C_done.csv")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = rows(root / "profile_manifest.csv")
    expected_review = rows(root / "profile_review_C.csv")
    errors = []
    by_key = {}
    prompt_hash = sha1((root / "prompts/profile_block.txt").read_bytes())
    for row in manifest:
        key = (row["sample_id"], row["setting"])
        if key in by_key:
            errors.append(f"Duplicate profile {key}")
        by_key[key] = row
        path = root / row["profile_path"]
        if not path.is_file():
            errors.append(f"Missing {path}")
            continue
        data = path.read_bytes()
        profile = json.loads(data)
        if sha1(data) != row["profile_sha1"]:
            errors.append(f"Profile file changed: {key}")
        if sha1(profile["profile_text"].encode()) != row["profile_text_sha1"]:
            errors.append(f"Profile text changed: {key}")
        if profile["profile_block_sha1"] != prompt_hash:
            errors.append(f"Prompt template changed: {key}")
        if len(profile["profile_text"].encode()) > profile["max_profile_tokens"]:
            errors.append(f"Conservative UTF-8 byte bound exceeded: {key}")
        if profile["retrieved_k"] != len(profile["retrieved_cases"]):
            errors.append(f"Incorrect retrieved_k: {key}")
        families = [item["family_root"] for item in profile["retrieved_cases"]]
        if len(families) != len(set(families)):
            errors.append(f"Repeated retrieved family: {key}")
        for item in profile["retrieved_cases"]:
            if not all(day < profile["cutoff"] for day in item["source_dates"]):
                errors.append(f"Late source date: {key}/{item['episode_id']}")
    review_keys = {(r["sample_id"], r["setting"]) for r in expected_review}
    if len(manifest) != 300 or len(review_keys) != 30:
        errors.append("Expected 300 profiles and the 30 fixed review rows")
    if errors:
        print(json.dumps({"integrity": "FAIL", "errors": errors}, indent=2))
        return 1
    result = {"integrity": "PASS", "profiles": len(manifest), "fixed_review_rows": 30,
              "human_review": "not supplied", "team_frozen": False}
    if args.review:
        review = rows(args.review)
        actual = {(r["sample_id"], r["setting"]) for r in review}
        if actual != review_keys or len(review) != 30:
            errors.append("Review must contain exactly the original 30 unique rows")
        fields = ["dates_ok", "families_ok", "identity_ok", "summary_faithful",
                  "rank_relevant", "statistics_status_ok"]
        unresolved = []
        limited = []
        for r in review:
            key = (r["sample_id"], r["setting"])
            source = by_key.get(key, {})
            for name in ["profile_path", "profile_sha1", "cutoff"]:
                if r.get(name) != source.get(name):
                    errors.append(f"Review is for a different file: {key}/{name}")
            if not r.get("reviewer", "").strip():
                errors.append(f"Missing human reviewer: {key}")
            for name in fields:
                if r.get(name) not in {"yes", "qualified", "no", "unknown"}:
                    errors.append(f"Incomplete review: {key}/{name}")
            if r.get("verdict") not in {"pass", "pass_with_limits", "needs_fix", "unknown"}:
                errors.append(f"Incomplete verdict: {key}")
            non_yes = any(r.get(name) != "yes" for name in fields)
            if non_yes and not r.get("notes", "").strip():
                errors.append(f"Non-yes judgments need notes: {key}")
            if r.get("verdict") == "pass" and non_yes:
                errors.append(f"Use pass_with_limits or an unresolved verdict: {key}")
            if any(r.get(name) in {"no", "unknown"} for name in fields):
                if r.get("verdict") not in {"needs_fix", "unknown"}:
                    errors.append(f"Unresolved field cannot have a passing verdict: {key}")
            if r.get("verdict") in {"needs_fix", "unknown"}:
                unresolved.append("/".join(key))
            elif r.get("verdict") == "pass_with_limits":
                limited.append("/".join(key))
        result.update(human_review="FAIL" if errors else "complete",
                      review_sha256=hashlib.sha256(args.review.read_bytes()).hexdigest(),
                      unresolved_rows=unresolved, qualified_rows=limited,
                      ready_for_team_decision=not errors and not unresolved)
        if errors:
            result["errors"] = errors
        result["note"] = "Validation never freezes files or substitutes for human review and team adoption."
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if errors else (2 if result.get("unresolved_rows") else 0)


if __name__ == "__main__":
    sys.exit(main())
