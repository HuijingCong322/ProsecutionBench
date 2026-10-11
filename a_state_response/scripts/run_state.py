"""Run state extraction with your own Azure OpenAI deployment (A, week-3 pilot).
Config (environment variables, never written to disk):
  AZURE_OPENAI_ENDPOINT  e.g. https://<resource>.openai.azure.com/openai/v1/
  AZURE_OPENAI_API_KEY
  AZURE_DEPLOYMENT       your GPT-5-mini deployment name
Usage:
  python3 A/scripts/run_state.py --group dev                 # 3 dev apps x 2 stages
  python3 A/scripts/run_state.py --group gold                # 10 gold apps x 2 stages
  python3 A/scripts/run_state.py --group test_core           # 90 remaining test_core apps (A1 cutoff)
  python3 A/scripts/run_state.py --ids 13151341 --stage A1_cutoff
In Colab: set the three variables with os.environ (key via getpass) and run the same command with '!'.
Outputs (A/outputs/): state_raw/<sample>_<stage>_<prompt_hash>_<input_hash>.json (cache: a call is
skipped when this file exists), state_predictions.jsonl (rebuilt from the cache, one row per
sample+stage), and A/logs/usage_log.jsonl (tokens, finish_reason, estimated cost).
Starts with max_completion_tokens=8192; a response cut by the length limit is retried once at 16384."""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

A = Path(__file__).resolve().parent.parent
PROMPT = (A / "prompts" / "state_extraction.txt").read_text()
PROMPT_HASH = hashlib.sha1(PROMPT.encode()).hexdigest()[:10]
EFFORT = "low"   # frozen 2026-10-09: p3 prompt + low reasoning (best on dev+tune, see A/README.md)
OUTDIR = A / "outputs"
# prompt variants compared on the dev+tune cases: name -> (prompt file, reasoning effort)
VARIANTS = {"p1_min": ("variants/p1.txt", "minimal"), "p1_low": ("variants/p1.txt", "low"),
            "p2_min": ("variants/p2.txt", "minimal"), "p2_low": ("variants/p2.txt", "low"),
            "p3_low": ("variants/p3.txt", "low")}
PRICE = {"in": 0.25, "cached_in": 0.025, "out": 2.00}   # USD per 1M tokens, GPT-5-mini; check your Azure price


def client():
    from openai import OpenAI
    ep, key = os.environ.get("AZURE_OPENAI_ENDPOINT"), os.environ.get("AZURE_OPENAI_API_KEY")
    if not ep or not key or not os.environ.get("AZURE_DEPLOYMENT"):
        sys.exit("Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and AZURE_DEPLOYMENT first.")
    return OpenAI(base_url=ep, api_key=key, timeout=300, max_retries=2)   # a stalled connection fails after 5 min and is retried


def user_message(r):
    head = (f"Application {r['app_id']}. Stage: {r['stage']}. Cutoff: {r['cutoff']}.\n"
            f"Most recent Office action on the merits before the cutoff: {r['o1_doc_id']} ({r['o1_code']}).\n")
    if r["stage"] == "A1_cutoff":
        head += f"Applicant reply filed on the cutoff date (A1): {', '.join(r['a1_doc_ids'])}.\n"
    return head + "\nDOCUMENTS (oldest first):\n\n" + r["input_text"]


def call(cl, r, max_tokens):
    t0 = time.time()
    resp = cl.chat.completions.create(
        model=os.environ["AZURE_DEPLOYMENT"],
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": user_message(r)}],
        max_completion_tokens=max_tokens, reasoning_effort=EFFORT,
        response_format={"type": "json_object"})
    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    cost = ((u.prompt_tokens - cached) * PRICE["in"] + cached * PRICE["cached_in"]
            + u.completion_tokens * PRICE["out"]) / 1e6
    return {"content": resp.choices[0].message.content, "finish_reason": resp.choices[0].finish_reason,
            "model": resp.model, "prompt_tokens": u.prompt_tokens, "cached_tokens": cached,
            "completion_tokens": u.completion_tokens, "est_cost_usd": round(cost, 5),
            "seconds": round(time.time() - t0, 1), "max_completion_tokens": max_tokens}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["dev", "gold", "test_core"])
    ap.add_argument("--stage", choices=["O1_cutoff", "A1_cutoff"])
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--group2", help="second group to include, e.g. --group dev --group2 tune")
    ap.add_argument("--variant", choices=sorted(VARIANTS), help="prompt-comparison run (outputs/variants/<name>/)")
    a = ap.parse_args()
    global PROMPT, PROMPT_HASH, EFFORT, OUTDIR
    if a.variant:
        pf, EFFORT = VARIANTS[a.variant]
        PROMPT = (A / "prompts" / pf).read_text()
        PROMPT_HASH = hashlib.sha1((PROMPT + EFFORT).encode()).hexdigest()[:10]
        OUTDIR = A / "outputs" / "variants" / a.variant
    rows = [json.loads(l) for l in open(A / "inputs" / "state_inputs.jsonl")]
    groups = {g for g in (a.group, a.group2) if g}
    rows = [r for r in rows if (not groups or r["group"] in groups) and (not a.stage or r["stage"] == a.stage)
            and (not a.ids or r["app_id"] in a.ids)]
    raw = OUTDIR / "state_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (A / "logs").mkdir(exist_ok=True)
    cl = None
    total = 0.0
    for i, r in enumerate(rows, 1):
        f = raw / f"{r['sample_id']}_{r['stage']}_{PROMPT_HASH}_{r['input_hash']}.json"
        if f.exists() and json.loads(f.read_text()).get("finish_reason") != "length":
            continue                       # cached; a cut-off (length) result is re-run with a larger limit
        cl = cl or client()
        res = None
        for max_tokens in (8192, 16384, 32768):
            for attempt in range(12):
                try:
                    res = call(cl, r, max_tokens)
                    break
                except Exception as e:
                    code = getattr(e, "status_code", None)
                    msg = str(e)
                    if code == 403 and "still being initialized" in msg:   # new subscription: transient
                        print(f"  Azure quota still initializing; waiting 60 s (try {attempt + 1}/12)", flush=True)
                        time.sleep(60)
                        continue
                    if code in (400, 401, 403, 404):         # configuration problem: stop, do not retry
                        sys.exit(f"Stopped: HTTP {code}: {msg[:300]}")
                    print(f"  retry {attempt + 1}: {msg[:160]}", flush=True)   # rate limit / transient
                    time.sleep(min(60, 10 * (attempt + 1)))
            if res is None or res["finish_reason"] != "length":
                break
            print(f"  output hit the length limit at {max_tokens}; retrying with a larger limit", flush=True)
        if res is None:
            print(f"[{i}/{len(rows)}] {r['sample_id']} {r['stage']} FAILED", flush=True)
            continue
        rec = {k: r[k] for k in ("sample_id", "app_id", "stage", "group", "cutoff", "input_hash")}
        rec.update({"prompt_hash": PROMPT_HASH, **res})
        f.write_text(json.dumps(rec, indent=1))
        log = {k: v for k, v in rec.items() if k != "content"}
        with open(A / "logs" / "usage_log.jsonl", "a") as lf:
            lf.write(json.dumps({"task": "state", "variant": a.variant or "main", "effort": EFFORT, **log, "time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        total += res["est_cost_usd"]
        print(f"[{i}/{len(rows)}] {r['sample_id']} {r['stage']} {res['finish_reason']} "
              f"in={res['prompt_tokens']} out={res['completion_tokens']} ${res['est_cost_usd']:.4f}", flush=True)
    # rebuild predictions from the cache (current prompt only)
    out = []
    current = {(x["sample_id"], x["stage"], x["input_hash"]) for x in map(json.loads, open(A / "inputs" / "state_inputs.jsonl"))}
    for f in sorted(raw.glob(f"*_{PROMPT_HASH}_*.json")):
        rec = json.loads(f.read_text())
        if (rec["sample_id"], rec["stage"], rec["input_hash"]) not in current:
            continue                       # result for an older version of the input (kept in the cache, not used)
        try:
            state = json.loads(rec["content"])
            ok = all(k in state for k in ("entered_claims", "proposed_claims", "rejections"))
        except Exception:
            state, ok = None, False
        out.append({k: rec[k] for k in ("sample_id", "app_id", "stage", "group", "cutoff", "input_hash",
                                        "prompt_hash", "model", "finish_reason")}
                   | {"parse_ok": ok, "state": state})
    with open(OUTDIR / "state_predictions.jsonl", "w") as fo:
        for o in out:
            fo.write(json.dumps(o) + "\n")
    print(f"this run est. cost ${total:.3f}; predictions: {len(out)} "
          f"(parse failures: {sum(not o['parse_ok'] for o in out)}) -> {OUTDIR / 'state_predictions.jsonl'}")


if __name__ == "__main__":
    main()
