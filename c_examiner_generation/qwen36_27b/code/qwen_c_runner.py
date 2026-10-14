"""Independent Qwen examiner-generation experiment using the frozen C inputs.

Generation uses Qwen; judging uses the existing GPT-5-mini protocol. No operation
writes to the original GPT experiment. API keys are read only from environment.
"""
from __future__ import annotations
import copy
import csv
import hashlib
import html
import importlib.metadata
import json
import os
import random
import re
import shutil
import statistics
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "qwen_c_v1"
GENERATOR = "Qwen3.6-27B"
JUDGE = "gpt-5-mini-2025-08-07"
SETTING = "state_with_history"
RUNTIME_REQUIREMENTS = "\n".join([
    "openai==2.54.0", "nltk==3.9.2", "rouge-score==0.1.2", "tiktoken==0.12.0",
    "tokenizers==0.23.3", "huggingface-hub==2.2.0", ""
])

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def read_jsonl(path):
    if not Path(path).exists(): return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

def write_json(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def write_jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)

def append_jsonl(path, row):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")

def copy_immutable(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file(): raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(source.read_bytes()) != sha(destination.read_bytes()):
            raise ValueError(f"Snapshot changed: {destination.name}. Keep this run unchanged.")
    else: shutil.copy2(source, destination)

def initialize(base, root, qcfg, jcfg):
    base, root = Path(base).resolve(), Path(root).resolve()
    if root == base or root.is_relative_to(base): raise ValueError("Use a separate sibling Qwen folder.")
    protocol = json.loads((base / "config/frozen_protocol.json").read_text())
    for key, rel in [("generation_prompt_hash", "prompts/examiner_generation.txt"),
                     ("judge_prompt_hash", "prompts/generation_judge.txt")]:
        if sha((base / rel).read_bytes()) != protocol[key]: raise ValueError(f"Original frozen prompt changed: {rel}")
    expected = json.loads((base / "inputs/prepared_file_hashes.json").read_text())
    for rel in ["inputs/generation_core.jsonl", "inputs/generation_dev.jsonl", "gold/generation_targets.jsonl"]:
        h = expected[rel]
        if sha((base / rel).read_bytes()) != h: raise ValueError(f"Original prepared file changed: {rel}")
    for rel in ["inputs/generation_core.jsonl", "gold/generation_targets.jsonl",
                "prompts/examiner_generation.txt", "prompts/generation_judge.txt", "requirements.txt"]:
        copy_immutable(base / rel, root / rel)
    for name in ["common.py", "run_experiments.py", "score_generation.py"]:
        copy_immutable(base / "code" / name, root / "code/legacy" / name)
    copy_immutable(base / "config/frozen_protocol.json", root / "config/gpt_protocol_snapshot.json")
    original_dev = read_jsonl(base / "inputs/generation_dev.jsonl")
    states = {r["sample_id"]: r for r in read_jsonl(base / "outputs/C/dev_states.jsonl")}
    dev = []
    for row in original_dev:
        row = copy.deepcopy(row)
        if row.get("state") is None:
            state = states.get(row["sample_id"])
            if not state: raise ValueError("Missing original GPT dev state. Finish the old dev stage first.")
            row["state"], row["state_provenance"] = state["state"], state["provenance"]
        dev.append(row)
    target = root / "inputs/generation_dev.jsonl"
    if target.exists() and read_jsonl(target) != dev: raise ValueError("Dev state snapshot changed.")
    if not target.exists(): write_jsonl(target, dev)
    for source, dest in [("examiner_generation_core_state_with_history.jsonl", "gpt_generation_core.jsonl"),
                         ("judge_core_state_with_history.jsonl", "gpt_judge_core.jsonl")]:
        copy_immutable(base / "outputs/C" / source, root / "baseline" / dest)
    for name, cfg in [("qwen_config.json", qcfg), ("azure_config.json", jcfg)]:
        path = root / "config" / name
        if path.exists() and json.loads(path.read_text()) != cfg:
            if (root / "config/frozen_protocol.json").exists() or (root / "outputs/C/examiner_generation_core_state_with_history.jsonl").exists():
                raise ValueError(f"Frozen configuration changed: {name}. Use a separately labelled new folder.")
            write_json(path, cfg) # Endpoint corrections before freezing are allowed.
        if not path.exists(): write_json(path, cfg)
    for folder in ["outputs/C", "logs/C", "metrics/C", "results", "handoff"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    snapshot = {str(p.relative_to(root)): sha(p.read_bytes()) for folder in ["inputs", "gold", "prompts", "baseline", "code/legacy"]
                for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    previous = root / "config/source_snapshot_hashes.json"
    if previous.exists() and json.loads(previous.read_text()) != snapshot: raise ValueError("Source snapshot changed.")
    if not previous.exists(): write_json(previous, snapshot)
    runtime_requirements = root / "runtime_requirements.txt"
    if runtime_requirements.exists() and runtime_requirements.read_text() != RUNTIME_REQUIREMENTS:
        raise ValueError("Runtime requirements changed; keep the labelled experiment unchanged.")
    if not runtime_requirements.exists(): runtime_requirements.write_text(RUNTIME_REQUIREMENTS, encoding="utf-8")
    print("Independent Qwen folder:", root)
    print("Core: 50; original three GPT dev states reused; original GPT files unchanged.")
    return root

def helpers():
    import common, run_experiments, score_generation
    return common, run_experiments, score_generation

def load_rows(root, split):
    if split not in ("dev", "core"): raise ValueError("Only dev and the fixed 50-case core are supported.")
    return read_jsonl(Path(root) / "inputs" / f"generation_{split}.jsonl")

def model_ok(name):
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return key in {"qwenqwen3627b", "qwen3627b"}

def canonical_ground(value):
    if type(value) == int: value = str(value)
    if not isinstance(value, str): return value
    text = re.sub(r"^(?:pre[ -]?aia|aia)\s+", "", value.strip().lower())
    text = re.sub(r"^35\s*u\.?\s*s\.?\s*c\.?\s*", "", text)
    text = re.sub(r"^(?:§{1,2}\s*|section\s+|sec\.\s*)", "", text)
    key = re.sub(r"[\s().,_-]", "", text)
    aliases = {k:k for k in ["101", "102", "103", "112a", "112b", "dp", "objection", "other"]}
    aliases.update({"102" + k: "102" for k in list("abcdefg") + ["a1", "a2", "b1", "b2", "b1a", "b1b", "b1c", "b2a", "b2b", "b2c"]})
    aliases.update({"103" + k: "103" for k in "abc"})
    aliases.update({"112" + k: "112a" for k in ["firstparagraph", "1stparagraph", "paragraph1", "paragraphone"]})
    aliases.update({"112" + k: "112b" for k in ["secondparagraph", "2ndparagraph", "paragraph2", "paragraphtwo"]})
    aliases.update({k:"dp" for k in ["doublepatenting", "statutorydoublepatenting", "nonstatutorydoublepatenting", "obviousnesstypedoublepatenting", "otdp"]})
    return aliases.get(key, value)

def normalize_surface(candidate):
    obj = copy.deepcopy(candidate); changes = []
    if not isinstance(obj, dict): return obj, changes
    def setv(d, key, new, path):
        old = d.get(key)
        if old != new or type(old) != type(new): changes.append({"path":path, "old":old, "new":new}); d[key] = new
    action = obj.get("next_action_type")
    if isinstance(action, str):
        new = {"ctnf":"CTNF", "ctfr":"CTFR", "noa":"NOA", "other":"other"}.get(action.strip().lower())
        if new is not None: setv(obj, "next_action_type", new, "next_action_type")
    if isinstance(obj.get("claim_ground_evidence"), list):
        for i, unit in enumerate(obj["claim_ground_evidence"]):
            if not isinstance(unit, dict): continue
            if "ground" in unit: setv(unit, "ground", canonical_ground(unit["ground"]), f"claim_ground_evidence[{i}].ground")
            for field, allowed in [("status", ("maintained", "withdrawn", "new", "unresolved")),
                                   ("evidence_status", ("record_supported", "insufficient_evidence"))]:
                value = unit.get(field)
                if isinstance(value, str) and value.strip().lower() in allowed:
                    setv(unit, field, value.strip().lower(), f"claim_ground_evidence[{i}].{field}")
    return obj, changes

def final_text(content):
    """Remove only an explicit reasoning envelope. Never extract JSON from reasoning."""
    text = (content or "").strip(); changes = []
    if text.startswith("<think>"):
        end = text.find("</think>")
        if end < 0: return "", ["unclosed_thinking_block"]
        text = text[end + len("</think>"):].strip(); changes.append("removed_explicit_thinking_envelope")
    elif not text.startswith(("{", "```")) and text.count("</think>") == 1:
        text = text.split("</think>", 1)[1].strip(); changes.append("removed_prefix_through_explicit_thinking_end")
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S | re.I)
    if fenced: text = fenced.group(1).strip(); changes.append("removed_json_code_fence")
    return text, changes

class QwenRunner:
    def __init__(self, root, client=None):
        self.root = Path(root); self.cfg = json.loads((self.root / "config/qwen_config.json").read_text())
        self._client = client
    def client(self):
        if self._client is None:
            from openai import OpenAI
            key = os.environ.get("QWEN_AZURE_API_KEY")
            if not key: raise RuntimeError("Set QWEN_AZURE_API_KEY privately before running.")
            self._client = OpenAI(base_url=self.cfg["base_url"], api_key=key,
                                  timeout=self.cfg["timeout_seconds"], max_retries=0)
        return self._client
    def call(self, task, sid, prompt, user, input_hash, validator, retry_api_failures=False):
        fp = sha(canonical({"task":task, "prompt":prompt, "user":user, "config":self.cfg,
                            "implementation_sha256":sha(Path(__file__).read_bytes())}))
        cache = self.root / "outputs/C/cache/qwen" / f"{sid}_{fp[:24]}.json"
        if cache.exists():
            cached = json.loads(cache.read_text()); cached["cache_reused"] = True
            if cached.get("status") != "api_failed" or not retry_api_failures:
                return cached # Failed paid outputs are retained; resume does not silently regenerate them.
        common, _, _ = helpers()
        messages = [{"role":"system", "content":prompt}, {"role":"user", "content":user}]
        for budget in (self.cfg["initial_max_tokens"], self.cfg["retry_max_tokens"]):
            started = time.time()
            base = {"sample_id":sid, "task":task, "input_hash":input_hash, "model_input_hash":sha(user),
                    "prompt_hash":sha(prompt), "request_hash":fp, "generator_label":GENERATOR,
                    "deployment":self.cfg["deployment"], "max_tokens":budget,
                    "timestamp_utc":datetime.now(timezone.utc).isoformat(), "protocol_version":VERSION,
                    "sampling":"omitted_provider_default", "thinking":"provider_default", "estimated_cost_usd":None}
            try:
                response = self.client().chat.completions.create(model=self.cfg["deployment"],
                    messages=messages, max_tokens=budget)
            except Exception as exc:
                code = getattr(exc, "status_code", None)
                result = {**base, "status":"api_failed", "http_status":code, "error_type":type(exc).__name__,
                          "billing":"unknown_when_no_usage_returned", "seconds":round(time.time()-started, 2)}
                append_jsonl(self.root / "logs/C/qwen_usage_log.jsonl", result); write_json(cache, result)
                # Wrong endpoint, unsupported fields and authentication must be fixed, not repeated 50 times.
                if code in (400, 401, 403, 404): raise RuntimeError(f"Qwen HTTP {code}; inspect endpoint, key and deployment configuration. No automatic retries.") from None
                return result
            raw = response.model_dump(); choice = response.choices[0] if response.choices else None
            content = (choice.message.content or "") if choice else ""
            finish = choice.finish_reason if choice else "missing_choice"
            answer, wrappers = final_text(content)
            try: parsed = json.loads(answer)
            except (ValueError, TypeError): parsed = None
            initial_errors = validator(parsed, sid)
            candidate, edits = normalize_surface(parsed)
            errors = validator(candidate, sid)
            state = "success" if finish == "stop" and not errors else ("truncated" if finish == "length" else "invalid_output")
            actual = getattr(response, "model", "")
            if not model_ok(actual): state = "model_version_mismatch"; errors = errors + ["unexpected_actual_model"]
            if (self.root / "config/frozen_protocol.json").exists():
                expected = json.loads((self.root / "config/frozen_protocol.json").read_text())["generator_actual_model"]
                if actual != expected: state = "model_version_mismatch"; errors = errors + ["actual_model_changed_after_freeze"]
            usage = raw.get("usage") or {}
            result = {**base, "status":state, "model":actual, "finish_reason":finish, "raw_response":raw,
                      "content":content, "final_answer_text":answer, "parsed":candidate, "original_parsed":parsed,
                      "validation_errors":errors, "original_validation_errors":initial_errors,
                      "wrapper_handling":wrappers, "surface_normalization_changes":edits,
                      "prompt_tokens":usage.get("prompt_tokens"), "completion_tokens":usage.get("completion_tokens"),
                      "seconds":round(time.time()-started, 2), "billing":"managed_compute_hourly; reconcile Azure bill"}
            append_jsonl(self.root / "logs/C/qwen_usage_log.jsonl",
                         {k:v for k,v in result.items() if k not in ("raw_response", "content", "parsed", "final_answer_text")})
            write_json(cache.with_name(cache.stem + f"_attempt_{budget}.json"), result); write_json(cache, result)
            if state == "model_version_mismatch": raise RuntimeError(f"Unexpected Qwen model identity: {actual}. Stop and check the deployment.")
            if finish != "length" or budget == self.cfg["retry_max_tokens"]: return result
            print(f"{sid}: length at {budget}; one retry at {self.cfg['retry_max_tokens']}", flush=True)
        return result

def check_snapshot(root):
    root = Path(root)
    for rel, h in json.loads((root / "config/source_snapshot_hashes.json").read_text()).items():
        if sha((root / rel).read_bytes()) != h: raise ValueError(f"Snapshot was modified: {rel}")

def runtime_versions():
    out = {}
    for name in ["openai", "nltk", "rouge-score", "tiktoken", "tokenizers", "huggingface-hub"]:
        try: out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: out[name] = None
    return out

def preflight(root):
    """Integrity and Qwen-tokenizer counts; no model API requests."""
    root = Path(root); check_snapshot(root)
    _, experiments, _ = helpers()
    from tokenizers import Tokenizer
    from huggingface_hub import hf_hub_download
    saved = root / "config/qwen_tokenizer.json"
    pinned_revision = json.loads(saved.read_text())["revision"] if saved.exists() else None
    token_path = Path(hf_hub_download("Qwen/Qwen3.6-27B", "tokenizer.json", revision=pinned_revision))
    tokenizer = Tokenizer.from_file(str(token_path))
    revision = token_path.parent.name
    tokenizer_info = {"model":"Qwen/Qwen3.6-27B", "revision":revision,
                      "tokenizer_sha256":sha(token_path.read_bytes()), "counting":"tokenizer content count plus 512 template-overhead reserve"}
    if saved.exists() and json.loads(saved.read_text()) != tokenizer_info: raise ValueError("Tokenizer snapshot changed; use its saved revision.")
    if not saved.exists(): write_json(saved, tokenizer_info)
    cfg = json.loads((root / "config/qwen_config.json").read_text())
    prompt = (root / "prompts/examiner_generation.txt").read_text()
    refs = {r["sample_id"]:r for r in read_jsonl(root / "gold/generation_targets.jsonl")}
    core = load_rows(root, "core"); dev = load_rows(root, "dev")
    if len(core) != 50 or len({r["sample_id"] for r in core}) != 50 or len(dev) != 3: raise ValueError("Expected fixed core50/dev3.")
    if {r["sample_id"] for r in core} & {r["sample_id"] for r in dev}: raise ValueError("Dev/core overlap.")
    counts = []
    for row in core + dev:
        if row.get("state") is None: raise ValueError("Missing fixed state")
        if any(d["date"] > row["cutoff"] for d in row["documents"]): raise ValueError("Post-cutoff document")
        if refs[row["sample_id"]]["target_doc_id"] in {d["doc_id"] for d in row["documents"]}: raise ValueError("O2 leaked into input")
        user = experiments.generation_user(row, SETTING)
        count = len(tokenizer.encode(prompt).ids) + len(tokenizer.encode(user).ids) + 512
        if count + cfg["retry_max_tokens"] + 2048 >= cfg["context_window_tokens"]:
            raise ValueError(f"Qwen context reserve exceeded: {row['sample_id']}. Do not crop history silently.")
        counts.append({"sample_id":row["sample_id"], "tokens_with_reserve":count})
    report = {"core_n":50, "dev_n":3, "integrity":"passed", "post_cutoff_docs":0, "target_docs_in_input":0,
              "max_qwen_input_tokens_with_reserve":max(r["tokens_with_reserve"] for r in counts),
              "tokenizer":tokenizer_info, "counts":counts, "runtime_versions":runtime_versions(),
              "qwen_cost":"No token-price estimate: dedicated H100 deployment is billed by elapsed accelerator time."}
    write_json(root / "results/preflight.json", report)
    print({k:v for k,v in report.items() if k not in ("counts", "runtime_versions")}); return report

def ping(root, runner=None):
    root = Path(root); runner = runner or QwenRunner(root)
    result = runner.call("qwen_connection", "connection", "Return a JSON object.",
                         'Return exactly {"ok": true}.', "connection_test",
                         lambda x,s: [] if isinstance(x, dict) and x.get("ok") is True else ["connection_not_json"], retry_api_failures=True)
    print("Qwen connection:", result["status"], "actual_model:", result.get("model"), "finish:", result.get("finish_reason"))
    if result["status"] != "success": raise RuntimeError("Connection test failed. Inspect final_answer_text and validation_errors; do not start core.")
    return result

def assert_frozen(root):
    root = Path(root); check_snapshot(root)
    frozen = json.loads((root / "config/frozen_protocol.json").read_text())
    for key, path in [("generation_prompt_hash", "prompts/examiner_generation.txt"),
                      ("judge_prompt_hash", "prompts/generation_judge.txt"),
                      ("implementation_hash", "code/qwen_c_runner.py")]:
        if sha((root / path).read_bytes()) != frozen[key]: raise ValueError(f"Frozen file changed: {path}")
    for key, path in [("generator_configuration", "config/qwen_config.json"),
                      ("judge_configuration", "config/azure_config.json")]:
        if json.loads((root / path).read_text()) != frozen[key]: raise ValueError(f"Frozen configuration changed: {path}")
    if json.loads((root / "config/qwen_tokenizer.json").read_text()) != frozen["tokenizer"]:
        raise ValueError("Frozen tokenizer metadata changed.")
    return frozen

def generate(root, split="core", runner=None, retry_api_failures=False):
    root = Path(root); runner = runner or QwenRunner(root); common, experiments, _ = helpers()
    check_snapshot(root)
    if split == "core": assert_frozen(root)
    prompt = (root / "prompts/examiner_generation.txt").read_text(); rows = load_rows(root, split)
    path = root / "outputs/C" / f"examiner_generation_{split}_{SETTING}.jsonl"
    merged = {r["sample_id"]:r for r in read_jsonl(path)}
    for i, row in enumerate(rows, 1):
        user = experiments.generation_user(row, SETTING)
        result = runner.call("qwen_generation_" + split, row["sample_id"], prompt, user, row["input_hash"], common.generation_validator,
                             retry_api_failures=retry_api_failures)
        result.update(app_id=row["app_id"], cutoff=row["cutoff"], split=split, input_setting=SETTING,
                      state_provenance=row["state_provenance"], missing_doc_ids=row["missing_doc_ids"],
                      run_id=f"C_Qwen36_27B_{split}_{sha(prompt)[:10]}_provider_default_8192r16384")
        if result["status"] == "success": result["citation_audit"] = experiments.citation_audit(result["parsed"], row)
        merged[row["sample_id"]] = result; write_jsonl(path, merged.values())
        print(f"[{i}/{len(rows)}] {row['sample_id']} {result['status']} cached={result.get('cache_reused',False)}", flush=True)
    return list(merged.values())

def judge(root, split="core", dev_one=False):
    root = Path(root); common, experiments, _ = helpers()
    if split == "core": assert_frozen(root)
    runner = common.AzureRunner(root)
    if runner.cfg["expected_model"] != JUDGE: raise ValueError("The fixed judge must remain GPT-5-mini.")
    candidates = read_jsonl(root / "outputs/C" / f"examiner_generation_{split}_{SETTING}.jsonl")
    if dev_one:
        valid = [r for r in candidates if r["status"] == "success"]
        if not valid: raise ValueError("No valid Qwen dev candidate available for a judge check.")
        first = next(i for i,r in enumerate(candidates) if r["status"] == "success")
        return experiments.judge(root, split=split, limit=first + 1, runner=runner)
    return experiments.judge(root, split=split, runner=runner)

def freeze(root, reviewed=False):
    root = Path(root)
    if not reviewed: raise ValueError("Read three dev outputs and one GPT judge, then set DEV_REVIEWED=True.")
    if (root / "config/frozen_protocol.json").exists():
        print("Already frozen; verified unchanged."); return assert_frozen(root)
    if (root / "outputs/C/examiner_generation_core_state_with_history.jsonl").exists(): raise ValueError("Core already exists; do not refreeze.")
    check_snapshot(root)
    if not (root / "results/preflight.json").exists(): raise ValueError("Run the tokenizer/integrity preflight first.")
    _, experiments, _ = helpers()
    dev = read_jsonl(root / "outputs/C/examiner_generation_dev_state_with_history.jsonl")
    expected = {r["sample_id"] for r in load_rows(root, "dev")}
    if {r["sample_id"] for r in dev} != expected: raise ValueError("Complete all three dev attempts first.")
    source_protocol = json.loads((root / "config/gpt_protocol_snapshot.json").read_text())
    dev_inputs = {r["sample_id"]:r for r in load_rows(root, "dev")}
    for r in dev:
        if r.get("prompt_hash") != source_protocol["generation_prompt_hash"] or r.get("input_hash") != dev_inputs[r["sample_id"]]["input_hash"]:
            raise ValueError("Dev outputs do not match the current frozen source.")
    if any(r.get("status") in ("api_failed", "model_version_mismatch") for r in dev): raise ValueError("Resolve deployment/API problems before freezing.")
    valid = [r for r in dev if r["status"] == "success"]
    if not valid: raise ValueError("At least one schema-valid dev output is required. Stop if the interface cannot produce the required output.")
    judges = read_jsonl(root / "outputs/C/judge_dev_state_with_history.jsonl")
    if not any(j["status"] == "success" and j.get("model") == JUDGE and j.get("prompt_hash") == source_protocol["judge_prompt_hash"]
               and j.get("candidate_request_hash") in {r["request_hash"] for r in valid} for j in judges):
        raise ValueError("Complete one matching GPT dev judge first.")
    actuals = {r.get("model") for r in dev}
    if len(actuals) != 1 or not model_ok(next(iter(actuals))): raise ValueError("Inconsistent Qwen identity in dev.")
    p = json.loads((root / "config/gpt_protocol_snapshot.json").read_text())
    result = {"generation_prompt_hash":p["generation_prompt_hash"], "judge_prompt_hash":p["judge_prompt_hash"],
              "generator_actual_model":next(iter(actuals)), "generator_label":GENERATOR, "judge_model":JUDGE,
              "generator_configuration":json.loads((root / "config/qwen_config.json").read_text()),
              "judge_configuration":json.loads((root / "config/azure_config.json").read_text()),
              "implementation_hash":sha((root / "code/qwen_c_runner.py").read_bytes()),
              "dev_status_counts":dict(Counter(r["status"] for r in dev)), "dev_ids":sorted(expected),
              "parser_policy":"final answer only; explicit think envelope/code fence removal; surface_format_v1 aliases; original schema unchanged",
              "state_provider":"fixed_previously_generated_GPT5mini_states", "input_setting":SETTING,
              "data_version":"v1.2", "runtime_versions":runtime_versions(),
              "tokenizer":json.loads((root / "config/qwen_tokenizer.json").read_text())}
    write_json(root / "config/frozen_protocol.json", result); print(json.dumps(result, ensure_ascii=False, indent=2)); return result

def judge_valid(j, p, row, frozen, ref):
    _, experiments, _ = helpers()
    payload = {"sample_id":row["sample_id"], "cutoff":row["cutoff"], "record":row["documents"], "predicted_A1_state":row["state"],
               "candidate":p["parsed"], "mechanical_citation_audit":p.get("citation_audit"),
               "actual_O2":{"doc_id":ref["target_doc_id"], "code":ref["target_code"], "date":ref["target_date"], "text":ref["target_text"]}}
    return bool(j and j.get("status") == "success" and j.get("model") == JUDGE
                and j.get("candidate_request_hash") == p.get("request_hash")
                and j.get("prompt_hash") == frozen["judge_prompt_hash"] and j.get("input_hash") == row["input_hash"]
                and j.get("model_input_hash") == sha(canonical(payload)))

def score(root):
    root = Path(root); frozen = assert_frozen(root); common, experiments, scoring = helpers()
    inputs = load_rows(root, "core"); refs = {r["sample_id"]:r for r in read_jsonl(root / "gold/generation_targets.jsonl")}
    predictions = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C/examiner_generation_core_state_with_history.jsonl")}
    judges = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C/judge_core_state_with_history.jsonl")}
    baseline = {r["sample_id"]:r for r in read_jsonl(root / "baseline/gpt_generation_core.jsonl")}
    basejudges = {r["sample_id"]:r for r in read_jsonl(root / "baseline/gpt_judge_core.jsonl")}
    old = json.loads((root / "config/gpt_protocol_snapshot.json").read_text())
    values = {k:[] for k in ["R-L", "MET.", "Judge"]}; failures = {k:[] for k in values}
    paired = {k:[] for k in values}; pairs = {k:[] for k in values}; rows = []; schema_states = Counter()
    raw_strict_n = normalized_n = 0
    for r in inputs:
        sid = r["sample_id"]; p = predictions.get(sid); j = judges.get(sid); b = baseline.get(sid); bj = basejudges.get(sid); g = refs[sid]
        usable = bool(p and p.get("status") == "success" and p.get("prompt_hash") == frozen["generation_prompt_hash"]
                      and p.get("model") == frozen["generator_actual_model"] and p.get("input_hash") == r["input_hash"]
                      and p.get("model_input_hash") == sha(experiments.generation_user(r, SETTING)))
        if usable and common.generation_validator(p["parsed"], sid): raise ValueError("Success record fails frozen schema")
        state = p.get("status", "not_run") if p else "not_run"; schema_states[state] += 1
        if usable:
            raw_strict_n += not bool(p.get("original_validation_errors")); normalized_n += bool(p.get("surface_normalization_changes"))
        baseusable = bool(b and b.get("status") == "success" and b.get("model") == JUDGE
                          and b.get("input_hash") == r["input_hash"] and b.get("prompt_hash") == old["generation_prompt_hash"]
                          and b.get("model_input_hash") == sha(experiments.generation_user(r, SETTING)))
        item = {"sample_id":sid, "status":state, "input_hash":r["input_hash"], "generator":GENERATOR, "judge_model":JUDGE,
                "target_doc_id":g["target_doc_id"], "qwen_rougeL":None, "qwen_meteor":None, "qwen_judge":None,
                "gpt_rougeL":None, "gpt_meteor":None, "gpt_judge":None}
        for metric, function, qcol, bcol in [("R-L", scoring.rouge_l, "qwen_rougeL", "gpt_rougeL"),
                                           ("MET.", scoring.meteor, "qwen_meteor", "gpt_meteor")]:
            qvalue = bvalue = None
            if usable:
                try: qvalue = function(g["target_text"], p["parsed"]["office_action"]); values[metric].append(qvalue)
                except Exception as exc: failures[metric].append("metric_error_" + type(exc).__name__)
            else: failures[metric].append(state if state != "success" else "provenance_mismatch")
            if baseusable: bvalue = function(g["target_text"], b["parsed"]["office_action"])
            item[qcol], item[bcol] = qvalue, bvalue
            if qvalue is not None and bvalue is not None:
                paired[metric].append(qvalue - bvalue); pairs[metric].append(sid)
        if usable and judge_valid(j, p, r, frozen, g): item["qwen_judge"] = j["parsed"]["overall"]; values["Judge"].append(item["qwen_judge"])
        else: failures["Judge"].append("generation_invalid" if not usable else j.get("status", "judge_missing") if j else "judge_missing")
        if baseusable and judge_valid(bj, b, r, old, g): item["gpt_judge"] = bj["parsed"]["overall"]
        if item["qwen_judge"] is not None and item["gpt_judge"] is not None:
            paired["Judge"].append(item["qwen_judge"] - item["gpt_judge"]); pairs["Judge"].append(sid)
        if usable: item.update(citation_audit=p.get("citation_audit"), next_action_type=p["parsed"]["next_action_type"])
        rows.append(item); print(f"[{len(rows)}/50] scoring {sid} {state}", flush=True)
    summary = {k:scoring.summarize(values[k], 50, failures[k]) for k in values}
    pair_summary = {k:{**scoring.summarize(paired[k], 50, ["pair_unavailable"] * (50-len(paired[k]))),
                      "paired_sample_ids":pairs[k], "difference":"Qwen minus GPT on the same scored cases"} for k in values}
    report = {"model":GENERATOR, "actual_model":frozen["generator_actual_model"], "judge_model":JUDGE,
              "sample_set":"gen_core", "input_setting":SETTING, "full_text_primary":summary,
              "status_counts":dict(schema_states), "strict_final_json_schema_valid_n":raw_strict_n,
              "surface_normalized_valid_n":normalized_n, "paired_comparison":pair_summary,
              "generator_settings":"provider-default thinking/sampling; max_tokens 8192 with one 16384 length retry; JSON prompt only",
              "notes":["Means are over successfully scored cases; coverage and all failures retained.",
                       "All generators use fixed GPT-derived state and identical cutoff-visible base inputs.",
                       "Same GPT-5-mini judge is used for both generators; possible self-preference and student-review limits remain.",
                       "GPT baseline statuses are retained; no schema failures reassigned to zero or rerun.",
                       "No claim that Qwen provider defaults equal GPT low reasoning effort."]}
    path = root / "metrics/C/qwen_generation_metrics_core.json"; write_json(path, report)
    scoring.write_csv(root / "metrics/C/qwen_generation_scores_core.csv", rows)
    runid = f"C_Qwen36_27B_core_{frozen['generation_prompt_hash'][:10]}_provider_default_8192r16384"
    submitted = [{"owner":"C", "table3_column":k, "model":GENERATOR, "input_setting":SETTING, "sample_set":"gen_core",
                  "value":s["value"], "eligible_n":50, "scored_n":s["scored_n"], "failed_n":s["failed_n"],
                  "excluded_reason":json.dumps(s["failure_reasons"]), "split_detail":"data_v1 v1.2; fixed same 50 core cases; GPT-derived state",
                  "prompt_version":f"generation:{frozen['generation_prompt_hash']}; judge:{frozen['judge_prompt_hash']}",
                  "run_id":runid, "source_file":"metrics/C/qwen_generation_metrics_core.json",
                  "notes":"Qwen provider-default thinking/sampling; JSON prompt only; 8192/one16384 retry; judge GPT-5-mini low; coverage reported; student review pending"}
                 for k,s in summary.items()]
    scoring.write_csv(root / "results/C_metrics_Qwen36_27B.csv", submitted, scoring.TEMPLATE_COLUMNS)
    print("Qwen results:", summary); print("Paired comparison:", {k:(v["value"],v["scored_n"]) for k,v in pair_summary.items()})
    return report

def usage_summary(root):
    root = Path(root)
    out = {}
    for label, name in [("Qwen", "qwen_usage_log.jsonl"), ("GPT_judge", "usage_log.jsonl")]:
        log = read_jsonl(root / "logs/C" / name)
        responses = [r for r in log if r.get("prompt_tokens") is not None]
        out[label] = {"logged_responses":len(responses), "api_error_records":sum(r.get("status") in ("api_error", "api_failed") for r in log),
                      "input_tokens":sum(r.get("prompt_tokens",0) or 0 for r in responses),
                      "output_tokens":sum(r.get("completion_tokens",0) or 0 for r in responses),
                      "by_task":dict(Counter(r.get("task") for r in responses)),
                      "estimated_cost_usd":None if label == "Qwen" else sum(r.get("estimated_cost_usd",0) or 0 for r in responses),
                      "billing":"Qwen: hourly accelerator deployment charges, not token charges; check Azure" if label == "Qwen" else "Logged estimate only; reconcile Azure"}
    out["qwen_deployment"] = json.loads((root / "config/qwen_config.json").read_text())
    write_json(root / "results/qwen_usage_summary.json", out); print(json.dumps(out, ensure_ascii=False, indent=2)); return out

STYLE = "body{font:16px/1.6 Arial,sans-serif;max-width:1150px;margin:30px auto;padding:0 22px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px}summary{cursor:pointer;font-weight:bold}article{border:1px solid #ddd;padding:20px;margin:22px 0}"
def page(title, body):
    return f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>{html.escape(title)}</title><style>{STYLE}</style><body><h1>{html.escape(title)}</h1>{body}</body></html>'
def details(label, text):
    return f"<details><summary>{html.escape(label)}</summary><pre>{html.escape(text)}</pre></details>"
def case_html(row, ref, candidate, j):
    obj = candidate.get("parsed") if isinstance(candidate.get("parsed"), dict) else {}
    body = f"<p>sample_id: {row['sample_id']} | cutoff: {row['cutoff']} | status: {candidate.get('status')}</p>"
    body += "<h2>真实 O2，仅用于评分</h2><pre>" + html.escape(ref["target_text"]) + "</pre>"
    body += "<h2>Qwen OA 正文</h2><pre>" + html.escape(obj.get("office_action") or candidate.get("final_answer_text") or "No usable answer") + "</pre>"
    body += details("结构化输出及校验错误", json.dumps({"parsed":obj, "errors":candidate.get("validation_errors")}, ensure_ascii=False, indent=2))
    for d in row["documents"]: body += details(f"{d['doc_id']} | {d['doc_code']} | {d['date']} | {d['source']}", d["text"])
    body += details("固定 GPT-derived state", json.dumps(row["state"], ensure_ascii=False, indent=2))
    body += details("复核后再展开 GPT judge", json.dumps(j, ensure_ascii=False, indent=2))
    return page("Qwen OA review " + row["sample_id"], body)

def reading_pack(root, split="dev"):
    root = Path(root)
    refs = {r["sample_id"]:r for r in read_jsonl(root / "gold/generation_targets.jsonl")}
    candidates = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C" / f"examiner_generation_{split}_{SETTING}.jsonl")}
    judges = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C" / f"judge_{split}_{SETTING}.jsonl")}
    dest = root / "results" / (split + "_reading"); dest.mkdir(exist_ok=True)
    links = []
    for row in load_rows(root, split):
        sid = row["sample_id"]
        if sid not in candidates: continue
        name = sid + ".html"
        (dest / name).write_text(case_html(row, refs[sid], candidates[sid], judges.get(sid)), encoding="utf-8")
        links.append(f"<li><a href='{name}'>{sid}</a></li>")
    (dest / "index.html").write_text(page("Qwen " + split + " 完整阅读材料", "<ul>" + "".join(links) + "</ul>"), encoding="utf-8")
    result = root / "handoff" / ("Qwen_" + split + "_reading.zip")
    zip_directory(dest, result); return result

def zip_directory(source, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(Path(source).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts: archive.write(p, p.relative_to(source))

def handoffs(root):
    root = Path(root); _, experiments, scoring = helpers(); frozen = assert_frozen(root)
    rows = load_rows(root, "core"); by = {r["sample_id"]:r for r in rows}
    refs = {r["sample_id"]:r for r in read_jsonl(root / "gold/generation_targets.jsonl")}
    candidates = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C/examiner_generation_core_state_with_history.jsonl")}
    judges = {r["sample_id"]:r for r in read_jsonl(root / "outputs/C/judge_core_state_with_history.jsonl")}
    if set(candidates) != set(by): raise ValueError("All fixed core cases need output records before handoff.")
    b = root / "handoff/Qwen_B_baseline"; b.mkdir(parents=True, exist_ok=True)
    write_jsonl(b / "base_inputs_core.jsonl", [{**r, "exact_generation_user":experiments.generation_user(r, SETTING)} for r in rows])
    for rel in ["prompts/examiner_generation.txt", "config/qwen_config.json", "config/frozen_protocol.json",
                "outputs/C/examiner_generation_core_state_with_history.jsonl"]:
        shutil.copy2(root / rel, b / Path(rel).name)
    for name in ["common.py", "run_experiments.py", "score_generation.py"]:
        (b / "code").mkdir(exist_ok=True); shutil.copy2(root / "code/legacy" / name, b / "code" / name)
    shutil.copy2(root / "code/qwen_c_runner.py", b / "code/qwen_c_runner.py")
    (b / "README.md").write_text("# Qwen no-profile generation baseline for B\n\nUse the same actual Qwen checkpoint, base prompt, GPT-derived state, cutoff-visible documents and provider-default thinking/sampling. API: max_tokens 8192, one length retry 16384, no explicit temperature/reasoning_effort/response_format. Add only the profile to exact_generation_user. Preserve all 50 IDs and failures; compare the same jointly scored paired subset. The GPT baseline is a separate model run. For full-text ROUGE-L import rouge_l from code/score_generation.py and pass full O2 plus the office_action string. Do not call the legacy score() entry point, which checks GPT generator identity. No target O2 is included here.\n", encoding="utf-8")
    zip_directory(b, root / "handoff/C_Qwen_to_B_baseline.zip")
    ids = sorted(by); random.Random(20261012).shuffle(ids); ids = ids[:5]
    d = root / "handoff/Qwen_D_review"; d.mkdir(parents=True, exist_ok=True); forms = []; failures = []
    columns = ["sample_id", "generated_oa_file", "actual_o2_doc_id", "D_disposition_1to5", "D_grounds_1to5", "D_evidence_1to5", "D_reasoning_1to5", "D_overall_1to5", "notes"]
    for sid in ids:
        p = candidates[sid]; j = judges.get(sid)
        (d / (sid + ".html")).write_text(case_html(by[sid], refs[sid], p, j), encoding="utf-8")
        forms.append({"sample_id":sid, "generated_oa_file":sid + ".html", "actual_o2_doc_id":refs[sid]["target_doc_id"]})
        if p["status"] != "success": failures.append({"sample_id":sid, "status":p["status"], "validation_errors":p.get("validation_errors")})
    if not (d / "oa_review_Qwen_D_done.csv").exists(): scoring.write_csv(d / "oa_review_Qwen_D.csv", forms, columns)
    write_json(d / "review_manifest.json", {"sample_ids":ids, "seed":20261012, "failure_cases":failures,
               "successful_generation_cases_n":5-len(failures), "failed_generation_cases_n":len(failures)})
    shutil.copy2(root / "prompts/generation_judge.txt", d / "rubric.txt")
    (d / "index.html").write_text(page("Qwen 固定五件，可选补充复核", "<p>这不是已经完成的 GPT 复核。先独立阅读，不能沿用 GPT 的评分。无法评分的维度人工填 unknown；保留失败案例。</p><ul>" + "".join(f"<li><a href='{sid}.html'>{sid}</a></li>" for sid in ids) + "</ul>"), encoding="utf-8")
    zip_directory(d, root / "handoff/C_Qwen_to_D_5_OA_review.zip")
    # Two cases for optional narrative analysis, without fabricated student conclusions.
    with (root / "metrics/C/qwen_generation_scores_core.csv").open(encoding="utf-8-sig") as score_file:
        score_rows = list(csv.DictReader(score_file))
    valid = [r for r in score_rows if r.get("qwen_judge")]
    example_dir = root / "results/example_context"; example_dir.mkdir(exist_ok=True)
    lines = ["# Qwen generation examples", "", "Selected by judge scores for analysis; not human endorsements.", ""]
    if valid:
        ordered = sorted(valid, key=lambda r:(float(r["qwen_judge"]), float(r.get("qwen_rougeL") or 0), r["sample_id"]))
        for label, r in [("Lower judge score", ordered[0]), ("Higher judge score", ordered[-1])]:
            sid = r["sample_id"]; name = sid + ".html"
            (example_dir / name).write_text(case_html(by[sid], refs[sid], candidates[sid], judges.get(sid)), encoding="utf-8")
            lines += [f"## {label}", f"- sample_id: {sid}", f"- ROUGE-L: {r['qwen_rougeL']}; METEOR: {r['qwen_meteor']}; Judge: {r['qwen_judge']}",
                      f"- Sources: [case record](example_context/{name})", "- Checked explanation: pending", ""]
    example_file = root / "results/qwen_generation_examples.md"
    if not example_file.exists(): example_file.write_text("\n".join(lines), encoding="utf-8")
    zip_directory(example_dir, root / "handoff/Qwen_example_reading.zip")
    print("B baseline, optional D review and two-case reading materials prepared; human labels remain blank.")

def package(root):
    root = Path(root); frozen = assert_frozen(root)
    required = ["metrics/C/qwen_generation_metrics_core.json", "metrics/C/qwen_generation_scores_core.csv", "results/C_metrics_Qwen36_27B.csv"]
    if any(not (root / p).exists() for p in required): raise ValueError("Score the experiment before packaging.")
    expected_ids = {r["sample_id"] for r in load_rows(root, "core")}
    actual_ids = {r["sample_id"] for r in read_jsonl(root / "outputs/C/examiner_generation_core_state_with_history.jsonl")}
    if expected_ids != actual_ids: raise ValueError("Complete all fixed 50 attempt records before final packaging.")
    metrics = json.loads((root / required[0]).read_text()); usage_summary(root)
    example = root / "results/qwen_generation_examples.md"
    write_json(root / "results/task_status_Qwen_C.json", {
        "core_attempts_recorded":sum(metrics["status_counts"].values()), "status_counts":metrics["status_counts"],
        "automated_scoring":"completed", "Qwen_student_OA_review":"not_performed_optional",
        "example_analysis":"pending" if not example.exists() or "Checked explanation: pending" in example.read_text() else "provided; provenance follows the author",
        "A_review":"already completed in the original GPT task; not rerun or relabelled here"})
    lines = ["# Qwen3.6-27B Examiner Generation", "", "Fixed 50-case gen_core; same GPT-derived state and frozen generation prompt as the GPT baseline.", "",
             "Generator: Qwen3.6-27B, Azure Global Managed Compute, provider-default thinking/sampling, max_tokens 8192 / one length retry 16384, JSON prompt only.",
             "Judge: GPT-5-mini-2025-08-07, low, 8192 / one length retry 16384, same frozen rubric.", "", "| Metric | Value | Scored / eligible |", "|---|---:|---:|"]
    for name, m in metrics["full_text_primary"].items(): lines.append(f"| {name} | {m['value']} | {m['scored_n']}/50 |")
    lines += ["", "Means are over scored cases. See metrics/C for failure counts, schema checks and paired Qwen-minus-GPT comparisons on the same valid cases.",
              "No claim that Qwen defaults equal GPT low. All model text and failures are preserved. GPT self-preference and missing independent prior-art evidence remain evaluation limitations.",
              "Qwen compute is billed by GPU time, not the GPT token rate; billing reconciliation is pending unless actual costs are supplied.",
              "A's prior support/edit review is not repeated for this model. Qwen OA student review is a separate optional review and must not be marked completed using GPT ratings.",
              "The original GPT experiment is unchanged. Stored keys are not part of this archive."]
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = root.parent / "C_Qwen36_Week3_Submission.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in ["code", "config", "prompts", "inputs", "gold", "baseline", "metrics", "results", "handoff", "outputs/C"]:
            for p in (root / folder).rglob("*"):
                if p.is_file() and "cache" not in p.parts and "__pycache__" not in p.parts and not p.name.endswith(".zip"):
                    archive.write(p, Path("C_Qwen36_Week3") / p.relative_to(root))
        for name in ["README.md", "requirements.txt", "runtime_requirements.txt"]: archive.write(root / name, Path("C_Qwen36_Week3") / name)
    print("Saved:", output); return output
