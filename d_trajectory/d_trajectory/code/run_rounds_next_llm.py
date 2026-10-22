"""LLM runs for Remaining Rounds + Time to Next Action (one call per case answers both).

Same cases, inputs, cutoff, state files, model settings, caching and failure rules as run_trajectory_llm.py
(it reuses that file's client, call and Qwen code). Only the prompt and the answer format are new:
    prompts/rounds_next_forecast.txt
    answer: {"p_further_actions": {"0","1","2","3","4+"}, "further_actions": int, "days_to_next_action": int, "rationale"}

Examples (same environment variables / Colab Secrets as before; keys never go in files):
    python run_rounds_next_llm.py --root D_trajectory --data data_v1_share --split core --mock           # offline test
    python run_rounds_next_llm.py --provider qwen --root D_trajectory --data data_v1_share --ping
    python run_rounds_next_llm.py --provider qwen --root D_trajectory --data data_v1_share --split dev \
        --state D_trajectory/inputs/state_predictions_dev_C.jsonl --state-version C_dev_gpt5mini
    python run_rounds_next_llm.py --provider qwen ... --split core                                       # history only
    python run_rounds_next_llm.py --provider qwen ... --split core --state D_trajectory/inputs/state_predictions_A.jsonl --state-version A_v1
    python run_rounds_next_llm.py ... (no --provider)  -> GPT-5-mini, reasoning_effort low (Azure secrets, or only
        OPENAI_API_KEY set -> OpenAI's own API; recorded as provider "openai_api")

Frozen answer rules (fixed before scoring):
 1. p_further_actions must have the 5 keys 0,1,2,3,4+ (a key "4" is read as "4+") with numbers. -> else structural failure
 2. Values clipped to [0,1]; if they do not sum to 1 they are divided by their sum.          -> repairs clipped / renormalized
    (all zero -> structural failure)
 3. further_actions must be a number >= 0; it is rounded to a whole number.                  -> repair rounded
 4. days_to_next_action must be a number >= 0; rounded; values below 1 become 1.             -> repairs rounded / clipped
 5. A structural failure is retried once with the same prompt, then listed as failed (never filled with defaults).
Scored point predictions: further_actions as stated (primary), median of p_further_actions (sensitivity);
days_to_next_action as stated (risk for the C-index = minus the days).
"""
import argparse, concurrent.futures as cf, hashlib, json, math, os, random, re, sys, time
import run_trajectory_llm as rtl

KEYS = ["0", "1", "2", "3", "4+"]
PROMPT_FILE = "rounds_next_forecast.txt"


def load_prompt(root):
    txt = open(os.path.join(root, "prompts", PROMPT_FILE), encoding="utf-8").read()
    system = txt.split("### SYSTEM", 1)[1].split("### USER", 1)[0].strip()
    user = txt.split("### USER", 1)[1].strip()
    return system, user, hashlib.sha1(txt.encode()).hexdigest()[:12]


def _num(v, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} is not a number")
    if not math.isfinite(x):
        raise ValueError(f"{name} is not finite")
    return x


def validate(obj):
    repairs = []
    p = obj.get("p_further_actions")
    if not isinstance(p, dict):
        raise ValueError("p_further_actions must be an object")
    p = {("4+" if str(k).strip() in ("4", "4+", ">=4", "4 or more") else str(k).strip()): v for k, v in p.items()}
    if any(k not in p for k in KEYS):
        raise ValueError("p_further_actions needs keys 0,1,2,3,4+")
    pv = [_num(p[k], f"p[{k}]") for k in KEYS]
    if any(x < 0 or x > 1 for x in pv):
        repairs.append("clipped"); pv = [min(max(x, 0.0), 1.0) for x in pv]
    s = sum(pv)
    if s <= 0:
        raise ValueError("p_further_actions sums to 0")
    if abs(s - 1) > 1e-6:
        repairs.append("renormalized"); pv = [x / s for x in pv]
    n = _num(obj.get("further_actions"), "further_actions")
    if n < 0:
        raise ValueError("further_actions < 0")
    if n != round(n):
        repairs.append("rounded")
    n = int(round(n))
    d = _num(obj.get("days_to_next_action"), "days_to_next_action")
    if d < 0:
        raise ValueError("days_to_next_action < 0")
    if d != round(d):
        repairs.append("rounded")
    d = int(round(d))
    if d < 1:
        repairs.append("clipped"); d = 1
    cum, med = 0.0, 4
    for i, x in enumerate(pv):
        cum += x
        if cum >= 0.5:
            med = i; break
    return pv, n, med, d, sorted(set(repairs))


def parse(content):
    text, notes = (rtl.final_text(content) if rtl.PROVIDER == "qwen" else ((content or "").strip(), []))
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON object in response")
    obj = json.loads(m.group(0))
    return obj, notes


class Mock(rtl.MockClient):
    def create(self, model, messages, **kw):
        r = self.rng
        if r.random() < 0.05:
            content = '{"p_further_actions": {"0": 0.5}, "further_actions": "x"}'
        else:
            raw = [r.random() for _ in KEYS]
            content = json.dumps({"p_further_actions": dict(zip(KEYS, [x / sum(raw) for x in raw])),
                                  "further_actions": r.choice([0, 1, 1, 2]), "days_to_next_action": r.randint(20, 200),
                                  "rationale": "mock"})
        msg = type("M", (), {"content": content})
        choice = type("C", (), {"message": msg, "finish_reason": "stop"})
        usage = type("U", (), {"prompt_tokens": sum(len(m["content"]) for m in messages) // 4, "completion_tokens": 400})
        return type("R", (), {"choices": [choice], "usage": usage, "model": "mock"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="core", choices=["dev", "core", "test300"])
    ap.add_argument("--state", default=None)
    ap.add_argument("--state-version", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--provider", default="azure", choices=["azure", "qwen"])
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    rtl.PROVIDER = a.provider
    # which service actually answers: Azure OpenAI, OpenAI's own API (same GPT-5-mini model), or the Qwen deployment
    route = a.provider
    if a.provider == "azure" and os.environ.get("OPENAI_API_KEY") and not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        route = "openai_api"

    if a.mock:
        client, model = Mock(), "mock-model"
    else:
        client, model = rtl.make_client(False)
    if a.ping:  # same connection test as the trajectory runner
        sys.argv = [sys.argv[0], "--root", a.root, "--data", a.data, "--provider", a.provider, "--ping"]
        return rtl.main()

    system, user_tpl, prompt_hash = load_prompt(a.root)
    fname = {"dev": "trajectory_inputs_dev.jsonl", "core": "trajectory_inputs.jsonl",
             "test300": "trajectory_inputs_test300.jsonl"}[a.split]
    recs = [json.loads(x) for x in open(os.path.join(a.root, "inputs", fname))]
    if a.limit:
        recs = recs[: a.limit]
    states = {}
    if a.state:
        for x in open(a.state):
            o = json.loads(x)
            states.setdefault(str(o.get("sample_id", o.get("app_id"))).split("_")[0], []).append(o)
    setting = "state_with_history" if a.state else "history_only"
    model_label = "Qwen3.6-27B" if a.provider == "qwen" else model
    if a.provider == "qwen" and not a.tag:
        a.tag = "qwen3.6-27b"
    tag = (a.tag or model).replace("/", "_") + ("_mock" if a.mock and "mock" not in (a.tag or model) else "")
    if a.state:
        tag += "_state"
    cache_dir = os.path.join(a.root, "outputs", "D", "raw", "rounds_next_" + tag)
    log_dir = os.path.join(a.root, "logs", "D")
    os.makedirs(cache_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    usage_log = os.path.join(log_dir, "usage_log.jsonl")
    P = rtl.params()

    def log(**kw):
        with open(usage_log, "a") as lf:
            lf.write(json.dumps(dict(time=time.strftime("%Y-%m-%dT%H:%M:%S"), task="rounds_next", model=model, tag=tag,
                                     prompt_hash=prompt_hash, **kw)) + "\n")

    def run_one(rec):
        sid = rec["sample_id"]
        match = [o for o in states.get(sid, []) if o.get("cutoff") in (None, rec["cutoff"])]
        state = match[0].get("state", match[0]) if len(match) == 1 else None
        base = dict(method=f"llm_{setting}", model=model_label, deployment=model, input_setting=setting)
        if a.state and state is None:
            return dict(sample_id=sid, status="failed", error="no unique A1-cutoff state for this case", repairs=[], **base)
        msgs = rtl.build_messages(rec, a.data, system, user_tpl, state)
        key = hashlib.sha1(json.dumps([model, P, prompt_hash, rec["input_hash"], a.state_version,
                                       json.dumps(state, sort_keys=True)]).encode()).hexdigest()[:16]
        cpath = os.path.join(cache_dir, f"{sid}.json")
        if os.path.exists(cpath):
            c = json.load(open(cpath))
            keep_failed = a.provider == "qwen" and not a.retry_failed and str(c.get("error", "")).startswith("api:")
            if c.get("cache_key") == key and (c.get("status") == "ok" or keep_failed):
                c["from_cache"] = True
                return c
        attempts, out, err = [], None, None
        for attempt in range(2):
            try:
                r = rtl.call(client, model, msgs)
            except rtl.QwenStop:
                raise
            except Exception as e:  # noqa
                if a.provider != "qwen":
                    raise
                err = f"api: {type(e).__name__}: {str(e)[:200]}"
                log(sample_id=sid, attempt=attempt, input_hash=rec["input_hash"], status="api_failed", error=err)
                break
            attempts.append(r)
            log(sample_id=sid, attempt=attempt, input_hash=rec["input_hash"], **{k: v for k, v in r.items() if k != "content"})
            try:
                obj, wrap = parse(r["content"])
                pv, n, med, d, repairs = validate(obj)
                out = dict(sample_id=sid, status="ok", p_rounds=pv, rounds_pred=n, rounds_pred_dist_median=med,
                           next_days_pred=d, next_risk=-float(d), repairs=repairs, rationale=obj.get("rationale", ""),
                           wrapper_handling=wrap)
                break
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                err = str(e)
        if out is None:
            out = dict(sample_id=sid, status="failed", error=err, repairs=[])
        out.update(base, state_version=a.state_version, prompt_hash=prompt_hash, input_hash=rec["input_hash"],
                   cache_key=key, params=P, provider=route,
                   api_models=sorted({str(x.get("api_model")) for x in attempts}),
                   seconds=round(sum(x.get("seconds") or 0 for x in attempts), 1), n_attempts=len(attempts),
                   raw_responses=[x["content"] for x in attempts], finish_reasons=[x["finish_reason"] for x in attempts],
                   prompt_tokens=sum((x["prompt_tokens"] or 0) for x in attempts),
                   completion_tokens=sum((x["completion_tokens"] or 0) for x in attempts))
        json.dump(out, open(cpath, "w"), indent=1)
        out["from_cache"] = False
        return out

    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_one, r): r["sample_id"] for r in recs}
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                results.append(f.result())
            except rtl.QwenStop as e:
                print("STOPPED:", e)
                pool.shutdown(wait=False, cancel_futures=True)
                return 2
            except Exception as e:  # noqa
                results.append(dict(sample_id=futs[f], status="failed", error=f"api: {e}", repairs=[],
                                    method=f"llm_{setting}", model=model_label, deployment=model, input_setting=setting))
            if i % 10 == 0 or i == len(recs):
                print(f"  {i}/{len(recs)} done", flush=True)
    order = {r["sample_id"]: i for i, r in enumerate(recs)}
    results.sort(key=lambda r: order[r["sample_id"]])
    suffix = {"dev": "_dev", "core": "", "test300": "_test300"}[a.split]
    sub = "dev" if a.split == "dev" else ""
    out_path = os.path.join(a.root, "outputs", "D", sub, f"rounds_next_predictions_{tag}{suffix}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k not in ("raw_responses", "from_cache")}) + "\n")
    ok = sum(r["status"] == "ok" for r in results)
    new = [r for r in results if not r.get("from_cache")]
    pin = sum(r.get("prompt_tokens") or 0 for r in new); pout = sum(r.get("completion_tokens") or 0 for r in new)
    if a.provider == "qwen":
        cost = None
        print(f"{tag} [{a.split}] ok {ok}/{len(results)}  from cache {len(results) - len(new)}  tokens in {pin:,} out {pout:,}  "
              f"model time {sum(r.get('seconds') or 0 for r in new) / 60:.0f} min (billed per GPU hour)")
    else:
        cost = pin / 1e6 * rtl.PRICE_IN + pout / 1e6 * rtl.PRICE_OUT
        print(f"{tag} [{a.split}] ok {ok}/{len(results)}  from cache {len(results) - len(new)}  tokens in {pin:,} out {pout:,}  est. ${cost:.2f}")
    for r in results:
        if r["status"] != "ok":
            print("   failed:", r["sample_id"], "-", str(r.get("error"))[:150])
    print("wrote", out_path)
    with open(os.path.join(a.root, "outputs", "D", "model_manifest.jsonl"), "a") as mf:
        mf.write(json.dumps(dict(time=time.strftime("%Y-%m-%dT%H:%M:%S"), task="rounds_next", tag=tag, model=model_label,
                                 deployment=model, split=a.split, input_setting=setting, state_version=a.state_version,
                                 prompt_hash=prompt_hash, params=P, provider=route, n=len(results), ok=ok,
                                 tokens_in=pin, tokens_out=pout, est_cost_usd=None if cost is None else round(cost, 4),
                                 output=os.path.relpath(out_path, a.root))) + "\n")


if __name__ == "__main__":
    sys.exit(main())
