"""Run GPT-5-mini (or another Azure OpenAI deployment) on the trajectory forecasting task.

One call per case returns F_allowance(m) and F_abandonment(m) for months 1..24. Outputs are cached, so re-running
only calls the API for cases that are new or whose prompt, inputs or parameters changed.

Credentials come from environment variables (or Colab Secrets in the notebook); never put them in files:
    AZURE_OPENAI_ENDPOINT   e.g. https://<resource>.openai.azure.com
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_DEPLOYMENT your deployment name, e.g. gpt-5-mini

Examples
    # 1. connection test (one tiny call)
    python run_trajectory_llm.py --root D_trajectory --data data_v1_share --ping
    # 2. the 3 dev cases (not scored) to check parsing and cost
    python run_trajectory_llm.py --root D_trajectory --data data_v1_share --split dev
    # 3. the 100 test_core cases
    python run_trajectory_llm.py --root D_trajectory --data data_v1_share --split core
    # optional: add A's predicted A1 state (jsonl with sample_id + state)
    python run_trajectory_llm.py ... --state path/to/state_predictions.jsonl --state-version A_v1
    # offline test with a fake model (no API, no cost)
    python run_trajectory_llm.py --root D_trajectory --data data_v1_share --split core --mock
"""
import argparse, concurrent.futures as cf, hashlib, json, os, random, re, sys, time
from traj_common import GRID_MONTHS, validate_curves

PARAMS = dict(max_completion_tokens="8192->16384->32768 on cut-off", reasoning_effort="low")
# Team decision 2026-10-10: reasoning_effort "low" (not "minimal") for all tasks. The plan's 4096-token limit counts
# reasoning tokens, so it is raised to 8192 to avoid cut-off answers; you only pay for tokens actually used.
# USD per 1M tokens, used only for the cost estimate in the log. Check your Azure price sheet and override.
PRICE_IN, PRICE_OUT = 0.25, 2.00


def load_prompt(root):
    txt = open(os.path.join(root, "prompts", "trajectory_forecast.txt"), encoding="utf-8").read()
    system = txt.split("### SYSTEM", 1)[1].split("### USER", 1)[0].strip()
    user = txt.split("### USER", 1)[1].strip()
    return system, user, hashlib.sha1(txt.encode()).hexdigest()[:12]


def build_messages(rec, data_root, system, user_tpl, state):
    parts = []
    for d in rec["documents"]:
        with open(os.path.join(data_root, d["text_path"]), encoding="utf-8", errors="replace") as f:
            body = f.read().strip()
        parts.append(f"[{d['doc_id']} | {d['doc_code']} | {d['date']} | {d['role']} | {d['source']}]\n{body}")
    state_txt = json.dumps(state, ensure_ascii=False) if state is not None else "not provided"
    fill = {"{cutoff_date}": rec["cutoff"], "{filing_date}": rec["filing_date"], "{art_unit}": rec["art_unit"],
            "{o1_code}": rec["o1"]["code"], "{o1_date}": rec["o1"]["mail_date"], "{state}": state_txt,
            "{history}": "\n\n".join(parts)}
    user = user_tpl
    for k, v in fill.items():
        user = user.replace(k, v)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(content):
    """JSON object -> (F_allowance, F_abandonment, rationale). Accepts a ```json fenced block."""
    if content is None:
        raise ValueError("empty response")
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError("no JSON object in response")
    obj = json.loads(m.group(0))
    return obj.get("F_allowance"), obj.get("F_abandonment"), obj.get("rationale", "")


# ------------------------------------------------------------------ clients
class MockClient:
    """Offline stand-in with the same interface. Returns plausible curves, and a broken answer for ~5% of
    first attempts so the retry path gets exercised."""
    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.chat = self
        self.completions = self

    def create(self, model, messages, **kw):
        n_tokens = sum(len(m["content"]) for m in messages) // 4
        r = self.rng
        if r.random() < 0.05:
            content = '{"F_allowance": [0.1, 0.2], "F_abandonment": "oops"}'
        else:
            pa, pb = r.uniform(0.4, 0.85), r.uniform(0.05, 0.3)
            k = r.uniform(0.08, 0.3)
            fa = [round(pa * (1 - pow(2.718, -k * m)), 4) for m in GRID_MONTHS]
            fb = [0.0 if m < 7 else round(pb * (1 - pow(2.718, -0.15 * (m - 6))), 4) for m in GRID_MONTHS]
            content = json.dumps({"F_allowance": fa, "F_abandonment": fb, "rationale": "mock"})
        msg = type("M", (), {"content": content})
        choice = type("C", (), {"message": msg, "finish_reason": "stop"})
        usage = type("U", (), {"prompt_tokens": n_tokens, "completion_tokens": 600,
                               "prompt_tokens_details": None, "completion_tokens_details": None})
        return type("R", (), {"choices": [choice], "usage": usage, "model": "mock"})


def make_client(mock):
    if mock:
        return MockClient(), "mock-model"
    from openai import OpenAI
    if os.environ.get("OPENAI_API_KEY") and not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        # fallback: OpenAI's own API (same GPT-5-mini model) when Azure is not available
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"]), os.environ.get("AZURE_OPENAI_DEPLOYMENT") or "gpt-5-mini"
    from urllib.parse import urlparse
    u = urlparse(os.environ["AZURE_OPENAI_ENDPOINT"].strip())  # accept any URL copied from the portal; keep only the host
    base = f"{u.scheme or 'https'}://{u.netloc or u.path.split('/')[0]}/openai/v1/"
    return OpenAI(base_url=base, api_key=os.environ["AZURE_OPENAI_API_KEY"]), os.environ["AZURE_OPENAI_DEPLOYMENT"]


LENGTH_BUDGETS = [8192, 16384, 32768]  # team rule (A's model_manifest): retry at a larger limit if the answer is cut off


def _call_once(client, model, messages, max_tokens):
    last_err = None
    for attempt in range(4):  # transport retries (rate limit / 5xx)
        try:
            resp = client.chat.completions.create(model=model, messages=messages,
                                                  response_format={"type": "json_object"},
                                                  max_completion_tokens=max_tokens,
                                                  reasoning_effort=PARAMS["reasoning_effort"])
            return resp, attempt
        except Exception as e:  # noqa
            last_err = e
            msg = str(e)
            if "mock" in model or any(c in msg for c in ("401", "403", "404", "DeploymentNotFound")):
                raise  # wrong key / endpoint / deployment: retrying will not help
            time.sleep(min(60, 5 * 2 ** attempt))
    raise RuntimeError(f"API failed after retries: {last_err}")


def call(client, model, messages):
    t0 = time.time()
    p_tok = c_tok = 0
    for budget in LENGTH_BUDGETS:
        resp, tr = _call_once(client, model, messages, budget)
        u = resp.usage
        p_tok += getattr(u, "prompt_tokens", 0) or 0
        c_tok += getattr(u, "completion_tokens", 0) or 0
        fr = resp.choices[0].finish_reason
        if fr != "length":
            break
    return dict(content=resp.choices[0].message.content, finish_reason=fr, prompt_tokens=p_tok,
                completion_tokens=c_tok, api_model=getattr(resp, "model", None), seconds=round(time.time() - t0, 1),
                transport_retries=tr, max_completion_tokens_used=budget)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="D_trajectory folder")
    ap.add_argument("--data", required=True, help="data_v1_share folder")
    ap.add_argument("--split", default="core", choices=["dev", "core", "test300"])
    ap.add_argument("--state", default=None, help="jsonl with sample_id + state from A (optional)")
    ap.add_argument("--state-version", default=None)
    ap.add_argument("--tag", default=None, help="name used in the output file, default = deployment name")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--ping", action="store_true")
    a = ap.parse_args()

    client, model = make_client(a.mock)
    if a.ping:
        r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": 'Reply with this json object: {"ok": true}'}],
                                           response_format={"type": "json_object"}, max_completion_tokens=2048,
                                           reasoning_effort=PARAMS["reasoning_effort"])
        print("connection ok:", r.choices[0].message.content, "| model:", getattr(r, "model", None))
        return

    system, user_tpl, prompt_hash = load_prompt(a.root)
    fname = {"dev": "trajectory_inputs_dev.jsonl", "core": "trajectory_inputs.jsonl",
             "test300": "trajectory_inputs_test300.jsonl"}[a.split]
    recs = [json.loads(x) for x in open(os.path.join(a.root, "inputs", fname))]
    if a.limit:
        recs = recs[: a.limit]
    states = {}
    if a.state:
        # A's file may hold states at both the O1 and the A1 cutoff; keep the one whose cutoff is the A1 cutoff.
        for x in open(a.state):
            o = json.loads(x)
            states.setdefault(str(o.get("sample_id", o.get("app_id"))).split("_")[0], []).append(o)
    setting = "state_with_history" if a.state else "history_only"
    tag = (a.tag or model).replace("/", "_") + ("_mock" if a.mock and "mock" not in (a.tag or model) else "")
    if a.state:
        tag += "_state"
    cache_dir = os.path.join(a.root, "outputs", "D", "raw", tag)
    log_dir = os.path.join(a.root, "logs", "D")
    os.makedirs(cache_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    usage_log = os.path.join(log_dir, "usage_log.jsonl")

    def run_one(rec):
        sid = rec["sample_id"]
        cands = states.get(sid, [])
        match = [o for o in cands if o.get("cutoff") in (None, rec["cutoff"])]
        state = (match[0].get("state", match[0]) if len(match) == 1 else None)
        if a.state and state is None:
            return dict(sample_id=sid, status="failed", error="no unique A1-cutoff state for this case", repairs=[],
                        method=f"llm_{setting}", model=model, input_setting=setting)
        msgs = build_messages(rec, a.data, system, user_tpl, state)
        key = hashlib.sha1(json.dumps([model, PARAMS, prompt_hash, rec["input_hash"], a.state_version,
                                       json.dumps(state, sort_keys=True)]).encode()).hexdigest()[:16]
        cpath = os.path.join(cache_dir, f"{sid}.json")
        if os.path.exists(cpath):
            c = json.load(open(cpath))
            if c.get("cache_key") == key and c.get("status") == "ok":
                c["from_cache"] = True
                return c
        attempts = []
        out = None
        for attempt in range(2):  # content retry: same prompt, at most once (plan section 13)
            r = call(client, model, msgs)
            attempts.append(r)
            with open(usage_log, "a") as lf:
                lf.write(json.dumps(dict(time=time.strftime("%Y-%m-%dT%H:%M:%S"), task="trajectory", sample_id=sid,
                                         model=model, tag=tag, attempt=attempt, prompt_hash=prompt_hash,
                                         input_hash=rec["input_hash"], **{k: v for k, v in r.items() if k != "content"})) + "\n")
            try:
                fa, fb, why = parse(r["content"])
                A, B, S, repairs = validate_curves(fa, fb)
                out = dict(sample_id=sid, status="ok", F_allowance=A.tolist(), F_abandonment=B.tolist(), S=S.tolist(),
                           repairs=repairs, rationale=why)
                break
            except (ValueError, json.JSONDecodeError) as e:
                err = str(e)
        if out is None:
            out = dict(sample_id=sid, status="failed", error=err, repairs=[])
        out.update(method=f"llm_{setting}", model=model, input_setting=setting, state_version=a.state_version,
                   prompt_hash=prompt_hash, input_hash=rec["input_hash"], cache_key=key, params=PARAMS,
                   n_attempts=len(attempts), raw_responses=[x["content"] for x in attempts],
                   finish_reasons=[x["finish_reason"] for x in attempts],
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
            except Exception as e:  # noqa  API failure: keep the case on the failure list, never drop silently
                results.append(dict(sample_id=futs[f], status="failed", error=f"api: {e}", repairs=[],
                                    method=f"llm_{setting}", model=model, input_setting=setting))
            if i % 10 == 0 or i == len(recs):
                print(f"  {i}/{len(recs)} done", flush=True)
    order = {r["sample_id"]: i for i, r in enumerate(recs)}
    results.sort(key=lambda r: order[r["sample_id"]])
    suffix = {"dev": "_dev", "core": "", "test300": "_test300"}[a.split]
    sub = "dev" if a.split == "dev" else ""
    out_path = os.path.join(a.root, "outputs", "D", sub, f"trajectory_predictions_{tag}{suffix}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k not in ("raw_responses", "from_cache")}) + "\n")
    ok = sum(r["status"] == "ok" for r in results)
    new = [r for r in results if not r.get("from_cache")]
    pin = sum(r.get("prompt_tokens") or 0 for r in new)
    pout = sum(r.get("completion_tokens") or 0 for r in new)
    cost = pin / 1e6 * PRICE_IN + pout / 1e6 * PRICE_OUT
    print(f"{tag} [{a.split}] ok {ok}/{len(results)}  failed {len(results) - ok}  from cache {len(results) - len(new)}  "
          f"new API tokens in {pin:,} out {pout:,}  est. cost of this run ${cost:.2f} (at ${PRICE_IN}/${PRICE_OUT} per 1M)")
    print("wrote", out_path)
    with open(os.path.join(a.root, "outputs", "D", "model_manifest.jsonl"), "a") as mf:
        mf.write(json.dumps(dict(time=time.strftime("%Y-%m-%dT%H:%M:%S"), tag=tag, model=model, split=a.split,
                                 input_setting=setting, state_version=a.state_version, prompt_hash=prompt_hash,
                                 params=PARAMS, n=len(results), ok=ok, tokens_in=pin, tokens_out=pout,
                                 est_cost_usd=round(cost, 4), output=os.path.relpath(out_path, a.root))) + "\n")


if __name__ == "__main__":
    sys.exit(main())
