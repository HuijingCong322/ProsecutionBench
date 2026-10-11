"""Run Applicant Response generation with your own Azure OpenAI deployment (A, week 3).
Config (environment variables, never written to disk): AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_DEPLOYMENT.
Usage:
  python3 A/scripts/run_response.py --group dev                  # 3 dev apps (smoke test)
  python3 A/scripts/run_response.py --group gold                 # 10 gold apps
  python3 A/scripts/run_response.py --group test_core --workers 4  # 90 apps, supplementary Strat
Same settings as state tracking: gpt-5-mini, reasoning_effort low, max_completion_tokens 8192 -> 16384 -> 32768
on length cut-offs, JSON output, no temperature. Cache: A/outputs/response_raw/<sample>_<prompt_hash>_<input_hash>.json
(a call is skipped when the file exists). Predictions: A/outputs/applicant_response.jsonl (rebuilt from the cache)."""
import argparse, hashlib, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
A = Path(__file__).resolve().parent.parent
PROMPT = (A / "prompts" / "applicant_response.txt").read_text()
PROMPT_HASH = hashlib.sha1(PROMPT.encode()).hexdigest()[:10]
EFFORT = "low"
PRICE = {"in": 0.25, "cached_in": 0.025, "out": 2.00}
RAW = A / "outputs" / "response_raw"
LOCK = threading.Lock()

def client():
    from openai import OpenAI
    ep, key = os.environ.get("AZURE_OPENAI_ENDPOINT"), os.environ.get("AZURE_OPENAI_API_KEY")
    if not ep or not key or not os.environ.get("AZURE_DEPLOYMENT"):
        sys.exit("Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and AZURE_DEPLOYMENT first (source ~/.zshrc).")
    return OpenAI(base_url=ep, api_key=key, timeout=300, max_retries=2)

def user_message(r):
    return (f"Application {r['app_id']}. Office action to answer: {r['o1_doc_id']} ({r['o1_code']}), mailed {r['cutoff']}.\n"
            "\nDOCUMENTS (oldest first):\n\n" + r["input_text"])

def call(cl, r, max_tokens):
    t0 = time.time()
    resp = cl.chat.completions.create(model=os.environ["AZURE_DEPLOYMENT"],
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": user_message(r)}],
        max_completion_tokens=max_tokens, reasoning_effort=EFFORT, response_format={"type": "json_object"})
    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    cost = ((u.prompt_tokens - cached) * PRICE["in"] + cached * PRICE["cached_in"] + u.completion_tokens * PRICE["out"]) / 1e6
    return {"content": resp.choices[0].message.content, "finish_reason": resp.choices[0].finish_reason, "model": resp.model,
            "prompt_tokens": u.prompt_tokens, "cached_tokens": cached, "completion_tokens": u.completion_tokens,
            "est_cost_usd": round(cost, 5), "seconds": round(time.time() - t0, 1), "max_completion_tokens": max_tokens}

def one(cl, r, i, n):
    f = RAW / f"{r['sample_id']}_{PROMPT_HASH}_{r['input_hash']}.json"
    if f.exists() and json.loads(f.read_text()).get("finish_reason") != "length":
        return 0.0
    res = None
    for max_tokens in (8192, 16384, 32768):
        for attempt in range(12):
            try:
                res = call(cl, r, max_tokens); break
            except Exception as e:
                code = getattr(e, "status_code", None); msg = str(e)
                if code in (400, 401, 403, 404) and "still being initialized" not in msg:
                    print(f"[{i}/{n}] {r['sample_id']} HTTP {code}: {msg[:200]}", flush=True); return 0.0
                print(f"  {r['sample_id']} retry {attempt + 1}: {msg[:120]}", flush=True)
                time.sleep(min(60, 10 * (attempt + 1)))
        if res is None or res["finish_reason"] != "length": break
    if res is None:
        print(f"[{i}/{n}] {r['sample_id']} FAILED", flush=True); return 0.0
    rec = {k: r[k] for k in ("sample_id", "app_id", "group", "cutoff", "input_hash")} | {"prompt_hash": PROMPT_HASH, **res}
    f.write_text(json.dumps(rec, indent=1))
    with LOCK:
        with open(A / "logs" / "usage_log.jsonl", "a") as lf:
            lf.write(json.dumps({"task": "response", "effort": EFFORT, **{k: v for k, v in rec.items() if k != "content"},
                                 "time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    print(f"[{i}/{n}] {r['sample_id']} {res['finish_reason']} in={res['prompt_tokens']} out={res['completion_tokens']} "
          f"{res['seconds']}s ${res['est_cost_usd']:.4f}", flush=True)
    return res["est_cost_usd"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["dev", "gold", "test_core"])
    ap.add_argument("--ids", nargs="*"); ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(A / "inputs" / "response_inputs.jsonl")]
    grp = {a.group} if a.group else None
    rows = [r for r in rows if (not grp or r["group"] in grp) and (not a.ids or r["app_id"] in a.ids)]
    RAW.mkdir(parents=True, exist_ok=True); (A / "logs").mkdir(exist_ok=True)
    todo = [r for r in rows if not (RAW / f"{r['sample_id']}_{PROMPT_HASH}_{r['input_hash']}.json").exists()]
    print(f"{len(rows)} samples, {len(todo)} to run, prompt {PROMPT_HASH}, workers {a.workers}", flush=True)
    total = 0.0
    if todo:
        cl = client()
        with ThreadPoolExecutor(a.workers) as ex:
            total = sum(ex.map(lambda t: one(cl, t[1], t[0], len(todo)), enumerate(todo, 1)))
    current = {(x["sample_id"], x["input_hash"]) for x in map(json.loads, open(A / "inputs" / "response_inputs.jsonl"))}
    out = []
    for f in sorted(RAW.glob(f"*_{PROMPT_HASH}_*.json")):
        rec = json.loads(f.read_text())
        if (rec["sample_id"], rec["input_hash"]) not in current: continue
        try:
            resp = json.loads(rec["content"]); ok = all(k in resp for k in ("strategies", "edits", "resulting_proposed_claims", "arguments"))
        except Exception:
            resp, ok = None, False
        out.append({k: rec[k] for k in ("sample_id", "app_id", "group", "cutoff", "input_hash", "prompt_hash", "model", "finish_reason")}
                   | {"parse_ok": ok, "response": resp})
    with open(A / "outputs" / "applicant_response.jsonl", "w") as fo:
        for o in out: fo.write(json.dumps(o) + "\n")
    print(f"this run est. cost ${total:.3f}; predictions {len(out)} (parse failures {sum(not o['parse_ok'] for o in out)})")

if __name__ == "__main__":
    main()
