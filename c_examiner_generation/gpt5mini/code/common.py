"""Shared, traceable Azure calls. Never stores an API key."""
from __future__ import annotations
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha256(value):
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def write_jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)

def append_jsonl(path, row):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def normalize_endpoint(endpoint):
    parts = urlsplit(endpoint.strip())
    if parts.scheme != "https" or not parts.netloc or parts.query:
        raise ValueError("Use an HTTPS Azure endpoint without query parameters.")
    return f"https://{parts.netloc}/openai/v1/"

def load_config(root=ROOT):
    cfg = json.loads((Path(root)/"config/azure_config.json").read_text())
    # These are the latest team-agreed settings. No task-specific silent override.
    if (cfg["reasoning_effort"], cfg["max_completion_tokens"], cfg["truncation_retry_tokens"]) != ("low",8192,16384):
        raise ValueError("Settings differ from the agreed low / 8192 / one 16384 retry. Obtain a team decision first.")
    if "temperature" in cfg or "max_tokens" in cfg:
        raise ValueError("Do not set temperature or max_tokens for this GPT-5-mini run.")
    cfg["base_url"] = normalize_endpoint(os.environ.get("AZURE_OPENAI_ENDPOINT",cfg["base_url"]))
    cfg["deployment"] = os.environ.get("AZURE_OPENAI_DEPLOYMENT", cfg["deployment"])
    return cfg

def estimate_cost(cfg, prompt_tokens, completion_tokens, cached_tokens=0):
    return ((prompt_tokens-cached_tokens)*cfg["input_price_per_million_usd"]
            + cached_tokens*cfg["cached_input_price_per_million_usd"]
            + completion_tokens*cfg["output_price_per_million_usd"])/1_000_000

def count_tokens(messages):
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    return sum(len(enc.encode(x["content"]))+8 for x in messages)+16

def request_fingerprint(task, prompt, user, cfg):
    return sha256(canonical({"task":task,"prompt":prompt,"user":user,
        "expected_model":cfg["expected_model"],"deployment":cfg["deployment"],
        "base_url":cfg["base_url"],"reasoning_effort":cfg["reasoning_effort"],
        "max_completion_tokens":cfg["max_completion_tokens"],
        "truncation_retry_tokens":cfg["truncation_retry_tokens"],
        "response_format":{"type":"json_object"}}))

class ConfigurationError(RuntimeError):
    pass

class BudgetStop(RuntimeError):
    pass

class AzureRunner:
    def __init__(self, root=ROOT, client=None, token_counter=count_tokens):
        self.root = Path(root)
        self.cfg = load_config(root)
        self._client = client
        self.counter = token_counter
        self.log = self.root/"logs/C/usage_log.jsonl"
        self.spent = sum(r.get("estimated_cost_usd",0) or 0 for r in read_jsonl(self.log))

    def client(self):
        if self._client is None:
            from openai import OpenAI
            key = os.environ.get("AZURE_OPENAI_API_KEY")
            if not key:
                raise ConfigurationError("Set your Azure key using Colab Secrets or getpass. Do not paste it into a code file.")
            self._client = OpenAI(base_url=self.cfg["base_url"], api_key=key,
                                 timeout=self.cfg["timeout_seconds"], max_retries=0)
        return self._client

    def call(self, task, sample_id, prompt, user, input_hash, validator):
        fp = request_fingerprint(task,prompt,user,self.cfg)
        cache = self.root/"outputs/C/cache"/task/f"{sample_id}_{fp[:20]}.json"
        if cache.exists():
            result = json.loads(cache.read_text())
            if result.get("status") == "success" and result.get("model") == self.cfg["expected_model"]:
                result["cache_reused"] = True
                return result
        messages = [{"role":"system","content":prompt},{"role":"user","content":user}]
        tokens = self.counter(messages)
        if tokens + self.cfg["truncation_retry_tokens"] + 2048 > self.cfg["context_window_tokens"]:
            result = {"sample_id":sample_id,"task":task,"status":"context_overflow",
                      "input_hash":input_hash,"model_input_hash":sha256(user),
                      "prompt_hash":sha256(prompt),"request_hash":fp,"estimated_input_tokens":tokens}
            write_json(cache,result)
            return result
        result = None
        for max_tokens in (8192,16384):
            projected = estimate_cost(self.cfg,tokens,max_tokens)
            if self.spent+projected > self.cfg["session_budget_usd"]:
                raise BudgetStop(f"Estimated logged spend ${self.spent:.2f}; next call reserve ${projected:.2f} exceeds the configured session cap. Check Azure billing, then deliberately update the spending cap if appropriate.")
            resp = None
            for attempt in range(self.cfg["transport_retries"]+1):
                t0 = time.time()
                try:
                    resp = self.client().chat.completions.create(
                        model=self.cfg["deployment"], messages=messages,
                        reasoning_effort="low", max_completion_tokens=max_tokens,
                        response_format={"type":"json_object"})
                    break
                except Exception as exc:
                    code = getattr(exc,"status_code",None)
                    append_jsonl(self.log,{"time_utc":datetime.now(timezone.utc).isoformat(),
                        "task":task,"sample_id":sample_id,"request_hash":fp,
                        "prompt_hash":sha256(prompt),"input_hash":input_hash,
                        "model_input_hash":sha256(user),"max_completion_tokens":max_tokens,
                        "status":"api_error","http_status":code,"error_type":type(exc).__name__,
                        "transport_attempt":attempt,"estimated_cost_usd":None})
                    # Do not print error response bodies: they may contain private configuration.
                    if code in (400,401,403,404):
                        raise ConfigurationError(f"HTTP {code}. Check endpoint, deployment, key, region permissions, or context length. Configuration errors are not retried.") from None
                    retryable = code in (408,429,500,502,503,504) or code is None
                    if not retryable or attempt == self.cfg["transport_retries"]:
                        break
                    time.sleep(min(30,5*2**attempt))
            base = {"sample_id":sample_id,"task":task,"input_hash":input_hash,
                "model_input_hash":sha256(user),"prompt_hash":sha256(prompt),"request_hash":fp,
                "reasoning_effort":"low","deployment":self.cfg["deployment"],
                "max_completion_tokens":max_tokens,"timestamp_utc":datetime.now(timezone.utc).isoformat()}
            if resp is None:
                result = {**base,"status":"api_failed","error":"Transient API failure; see usage log"}
                break
            raw = resp.model_dump()
            choice = resp.choices[0] if resp.choices else None
            content = (choice.message.content or "") if choice else ""
            finish = choice.finish_reason if choice else "missing_choice"
            usage = raw.get("usage") or {}
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens",0) or 0
            pt,ct = usage.get("prompt_tokens",0),usage.get("completion_tokens",0)
            cost = estimate_cost(self.cfg,pt,ct,cached)
            self.spent += cost
            try:
                parsed = json.loads(content)
                errors = validator(parsed,sample_id)
            except (ValueError,TypeError):
                parsed,errors = None,["invalid_json"]
            status = "success" if finish=="stop" and not errors else ("truncated" if finish=="length" else "invalid_output")
            if resp.model != self.cfg["expected_model"]:
                status = "model_version_mismatch"
                errors = errors+["actual_model_does_not_match_config"]
            result = {**base,"status":status,"model":resp.model,"finish_reason":finish,
                      "raw_response":raw,"content":content,"parsed":parsed,"validation_errors":errors,
                      "prompt_tokens":pt,"completion_tokens":ct,"cached_tokens":cached,
                      "estimated_cost_usd":cost,"seconds":round(time.time()-t0,2),
                      "system_fingerprint":raw.get("system_fingerprint")}
            append_jsonl(self.log,{k:v for k,v in result.items() if k not in ("raw_response","content","parsed")})
            # Keep every paid attempt, including the first truncated output.
            write_json(cache.with_name(cache.stem+f"_attempt_{max_tokens}.json"),result)
            write_json(cache,result)
            if status == "model_version_mismatch":
                raise ConfigurationError("The response model version differs from expected_model. Report it to the team and label or align the setting before continuing.")
            if finish != "length" or max_tokens==16384:
                break
            print(f"  {sample_id}: cut off at 8192, one retry at 16384",flush=True)
        write_json(cache,result)
        return result

def generation_validator(obj,sample_id):
    if not isinstance(obj,dict): return ["not_object"]
    errors=[]
    if obj.get("sample_id")!=sample_id: errors.append("wrong_sample_id")
    if obj.get("next_action_type") not in ("CTNF","CTFR","NOA","other"):errors.append("invalid_action_type")
    for key in ("claim_ground_evidence","applicant_argument_responses","limitations"):
        if not isinstance(obj.get(key),list):errors.append(f"missing_or_invalid_{key}")
    if isinstance(obj.get("limitations"),list) and any(not isinstance(x,str) for x in obj["limitations"]):errors.append("invalid_limitations")
    if not isinstance(obj.get("office_action"),str) or not obj["office_action"].strip():errors.append("empty_office_action")
    for unit in obj.get("claim_ground_evidence",[]) if isinstance(obj.get("claim_ground_evidence"),list) else []:
        if not isinstance(unit,dict) or not isinstance(unit.get("claim_ids"),list) or any(type(c)!=int for c in unit.get("claim_ids",[])):
            errors.append("invalid_ground_unit");continue
        if not isinstance(unit.get("evidence"),list):errors.append("invalid_evidence_list")
        if unit.get("ground") not in ("101","102","103","112a","112b","dp","objection","other"):errors.append("invalid_ground")
        if unit.get("status") not in ("maintained","withdrawn","new","unresolved"):errors.append("invalid_ground_status")
        if not isinstance(unit.get("rationale"),str):errors.append("invalid_rationale")
        if not isinstance(unit.get("claim_version_doc_ids"),list) or any(not isinstance(x,str) for x in unit.get("claim_version_doc_ids",[])):errors.append("invalid_claim_version_doc_ids")
        if unit.get("evidence_status") not in ("record_supported","insufficient_evidence"):errors.append("invalid_evidence_status")
        for ev in unit.get("evidence",[]) if isinstance(unit.get("evidence"),list) else []:
            if not isinstance(ev,dict) or any(not isinstance(ev.get(k),str) for k in ("doc_id","support_span","source_scope")):errors.append("invalid_evidence_object")
    for unit in obj.get("applicant_argument_responses",[]) if isinstance(obj.get("applicant_argument_responses"),list) else []:
        if not isinstance(unit,dict):errors.append("invalid_argument_response");continue
        if not isinstance(unit.get("claim_ids"),list) or any(type(c)!=int for c in unit.get("claim_ids",[])):errors.append("invalid_argument_claim_ids")
        if any(not isinstance(unit.get(k),str) for k in ("argument_summary","response","support_doc_id","support_span")):errors.append("invalid_argument_response_fields")
    return errors

def judge_validator(obj,sample_id):
    if not isinstance(obj,dict):return ["not_object"]
    errors=[]
    if obj.get("sample_id")!=sample_id:errors.append("wrong_sample_id")
    for k in ("disposition","grounds","reasoning","overall"):
        if type(obj.get(k))!=int or not 1<=obj[k]<=5:errors.append(f"invalid_{k}")
    ev=obj.get("evidence")
    if ev is not None and (type(ev)!=int or not 1<=ev<=5):errors.append("invalid_evidence")
    if obj.get("evidence_status") not in ("assessed","unknown"):errors.append("invalid_evidence_status")
    if ev is None and obj.get("evidence_status")!="unknown":errors.append("evidence_null_requires_unknown")
    if ev is not None and obj.get("evidence_status")!="assessed":errors.append("evidence_score_requires_assessed")
    if not isinstance(obj.get("overall_reason"),str):errors.append("missing_reason")
    return errors
