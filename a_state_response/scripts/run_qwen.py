"""Qwen3.6-27B runs for A (week-3 extra model), gold subset only, same inputs as the GPT-5-mini runs.

Team Qwen setting (C's README / qwen_config.json, shared 2026-10-13):
  model          Qwen3.6-27B, non-FP8; Azure catalog qwen--qwen3.6-27b, registry version 4
  deployment     Global Managed Compute, 1 model instance, 1 x H100 80GB
  thinking       provider default (no explicit switch)
  not sent       reasoning_effort, temperature, top_p, response_format (JSON is requested by the prompt only)
  max_tokens     8192; one retry at 16384 when the output is cut by the length limit
  timeout        600 s; automatic transport retries 0
Inputs are the frozen GPT-run inputs: inputs/state_inputs.jsonl (gold: 10 apps x O1/A1) and
inputs/response_inputs.jsonl (gold: 10 apps; record + the frozen GPT-5-mini predicted O1 state). Prompts are the
same frozen files (prompts/state_extraction.txt, prompts/applicant_response.txt), built with the same user_message().

Config (environment variables, never written to disk):
  QWEN_AZURE_ENDPOINT   e.g. https://<resource>.services.ai.azure.com/openai/v1/
  QWEN_AZURE_API_KEY
  QWEN_DEPLOYMENT       default qwen--qwen36-27b
Usage:
  python3 A/scripts/run_qwen.py --task ping                 # one tiny call: checks endpoint and returned model
  python3 A/scripts/run_qwen.py --task state                # 20 calls
  python3 A/scripts/run_qwen.py --task response             # 10 calls
  python3 A/scripts/run_qwen.py --task state --resume-failed   # explicitly re-run cached api_failed records only
Outputs (A/outputs/qwen36_27b/): state_raw/, response_raw/ (one JSON per call, cache: a cached call is never
re-run; api_failed records are re-run only with --resume-failed), state_predictions.jsonl and
applicant_response.jsonl (same row format as the GPT files), and A/logs/qwen_usage_log.jsonl (every attempt).
Output post-processing (same rule as C's runner): text up to an explicit </think> is removed, then one surrounding
```json fence; the remaining text must parse as JSON, otherwise parse_ok = false (no repair, no re-ask)."""
import argparse, hashlib, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

A = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(A / "scripts"))
OUT = A / "outputs" / "qwen36_27b"
LOG = A / "logs" / "qwen_usage_log.jsonl"
BUDGETS = (8192, 16384)
LOCK = threading.Lock()
STOP = threading.Event()   # set on a configuration error: no further requests are sent
EXPECTED_MODEL = "qwen3.6-27b"   # returned model must contain this (C/B report qwen--qwen3.6-27b)
CONFIG = {"model": "Qwen3.6-27B (non-FP8)", "catalog_model": "qwen--qwen3.6-27b", "registry_version": "4",
          "deployment_type": "GlobalManagedCompute", "instances": 1, "accelerator": "1 x H100 80GB",
          "thinking": "provider_default", "sampling": "omitted (provider default)", "reasoning_effort": "omitted",
          "response_format": "omitted (JSON requested by prompt only)", "max_tokens": list(BUDGETS),
          "timeout_seconds": 600, "transport_retries": 0}
TASKS = {  # task -> (input file, prompt file, raw dir, prediction file, required keys)
    "state": ("state_inputs.jsonl", "state_extraction.txt", "state_raw", "state_predictions.jsonl",
              ("entered_claims", "proposed_claims", "rejections")),
    "response": ("response_inputs.jsonl", "applicant_response.txt", "response_raw", "applicant_response.jsonl",
                 ("strategies", "edits", "resulting_proposed_claims", "arguments")),
}


def client():
    from openai import OpenAI
    ep, key = os.environ.get("QWEN_AZURE_ENDPOINT"), os.environ.get("QWEN_AZURE_API_KEY")
    if not ep or not key:
        sys.exit("Set QWEN_AZURE_ENDPOINT and QWEN_AZURE_API_KEY first (see the docstring).")
    return OpenAI(base_url=ep, api_key=key, timeout=CONFIG["timeout_seconds"], max_retries=0)


def deployment():
    return os.environ.get("QWEN_DEPLOYMENT", "qwen--qwen36-27b")


def final_text(content):
    """Remove an explicit thinking block and one JSON code fence; no other repair."""
    text, changes = (content or "").strip(), []
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip(); changes.append("removed_prefix_through_think_end")
    m = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S | re.I)
    if m:
        text = m.group(1).strip(); changes.append("removed_json_code_fence")
    return text, changes


def user_message(task, r):
    if task == "state":
        from run_state import user_message as um
    else:
        from run_response import user_message as um
    return um(r)


def log(rec):
    LOG.parent.mkdir(exist_ok=True)
    with LOCK, open(LOG, "a") as f:
        f.write(json.dumps({k: v for k, v in rec.items() if k not in ("content", "raw_content")}) + "\n")


def call_once(cl, task, r, prompt, ph):
    """One logical call: 8192, and one retry at 16384 if the output is cut by the length limit."""
    msgs = [{"role": "system", "content": prompt}, {"role": "user", "content": user_message(task, r)}]
    rec = None
    for budget in BUDGETS:
        t0 = time.time()
        base = {"task": task, "sample_id": r["sample_id"], "app_id": r["app_id"], "stage": r.get("stage"),
                "group": r["group"], "cutoff": r["cutoff"], "input_hash": r["input_hash"], "prompt_hash": ph,
                "deployment": deployment(), "max_tokens": budget,
                "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            resp = cl.chat.completions.create(model=deployment(), messages=msgs, max_tokens=budget)
        except Exception as e:
            code = getattr(e, "status_code", None)
            rec = base | {"status": "api_failed", "http_status": code, "error_type": type(e).__name__,
                          "error": str(e)[:300], "seconds": round(time.time() - t0, 1)}
            log(rec)
            if code in (400, 401, 403, 404):   # configuration problem: stop, never repeat it 20 times
                STOP.set()
                print(f"Stopped: HTTP {code}: {str(e)[:300]}\nCheck QWEN_AZURE_ENDPOINT, key and QWEN_DEPLOYMENT.", flush=True)
            return rec
        ch = resp.choices[0] if resp.choices else None
        content = (ch.message.content or "") if ch else ""
        finish = ch.finish_reason if ch else "missing_choice"
        u = resp.usage
        text, changes = final_text(content)
        rec = base | {"status": "length" if finish == "length" else "ok", "finish_reason": finish,
                      "model": getattr(resp, "model", ""), "prompt_tokens": getattr(u, "prompt_tokens", None),
                      "completion_tokens": getattr(u, "completion_tokens", None),
                      "seconds": round(time.time() - t0, 1), "postprocess": changes,
                      "raw_content": content, "content": text}
        if EXPECTED_MODEL not in (rec["model"] or "").lower():
            rec["status"] = "model_mismatch"
        log(rec)
        if finish != "length" or rec["status"] == "model_mismatch" or budget == BUDGETS[-1]:
            break
        print(f"  {r['sample_id']} cut at {budget} tokens; one retry at {BUDGETS[-1]}", flush=True)
    return rec


def rebuild(task):
    inp, _, rawdir, predfile, keys = TASKS[task]
    prompt = (A / "prompts" / TASKS[task][1]).read_text(); ph = hashlib.sha1(prompt.encode()).hexdigest()[:10]
    current = {x["sample_id"] + "|" + str(x.get("stage")) + "|" + x["input_hash"]
               for x in map(json.loads, open(A / "inputs" / inp)) if x["group"] == "gold"}
    out = []
    for f in sorted((OUT / rawdir).glob(f"*_{ph}_*.json")):
        rec = json.loads(f.read_text())
        if rec["sample_id"] + "|" + str(rec.get("stage")) + "|" + rec["input_hash"] not in current:
            continue
        try:
            obj = json.loads(rec.get("content") or "")
            ok = isinstance(obj, dict) and all(k in obj for k in keys)
        except Exception:
            obj, ok = None, False
        row = {k: rec.get(k) for k in ("sample_id", "app_id", "stage", "group", "cutoff", "input_hash",
                                       "prompt_hash", "model", "finish_reason", "status")}
        if task == "response":
            row.pop("stage")
        row["parse_ok"] = ok and rec.get("status") == "ok"
        if rec.get("status") == "ok" and not ok:
            row["status"] = "invalid_output"     # answered, but not the required JSON object
        row["state" if task == "state" else "response"] = obj if row["parse_ok"] else None
        out.append(row)
    with open(OUT / predfile, "w") as fo:
        for o in out:
            fo.write(json.dumps(o) + "\n")
    bad = [o["sample_id"] + (f" {o['stage']}" if o.get("stage") else "") + f" ({o['status']})"
           for o in out if not o["parse_ok"]]
    print(f"{task}: {len(out)}/{len(current)} predictions in {OUT / predfile}; not usable: {bad or 'none'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=["ping", "state", "response"])
    ap.add_argument("--resume-failed", action="store_true", help="re-run cached api_failed records (explicit)")
    ap.add_argument("--workers", type=int, default=10, help="parallel requests (the H100 template serves up to 256 sequences)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_config.json").write_text(json.dumps(CONFIG | {"deployment": deployment()}, indent=1))
    if a.task == "ping":
        r = client().chat.completions.create(model=deployment(), max_tokens=2048,
                                             messages=[{"role": "user", "content": "Reply with the single word OK."}])
        print("returned model:", r.model, "| finish:", r.choices[0].finish_reason,
              "| answer:", final_text(r.choices[0].message.content)[0][:80])
        print("model check:", "OK" if EXPECTED_MODEL in (r.model or "").lower() else "MISMATCH - stop and tell Claude")
        return
    inp, pf, rawdir, _, _ = TASKS[a.task]
    prompt = (A / "prompts" / pf).read_text(); ph = hashlib.sha1(prompt.encode()).hexdigest()[:10]
    rows = [r for r in map(json.loads, open(A / "inputs" / inp)) if r["group"] == "gold"]
    raw = OUT / rawdir; raw.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in rows:
        f = raw / f"{r['sample_id']}_{r.get('stage', 'reply')}_{ph}_{r['input_hash']}.json"
        if f.exists() and not (json.loads(f.read_text()).get("status") == "api_failed" and a.resume_failed):
            continue
        todo.append((r, f))
    print(f"{a.task}: {len(rows)} gold inputs, {len(todo)} to run, prompt {ph}, workers {a.workers}", flush=True)
    if todo:
        cl = client()
        done = [0]
        def work(item):
            r, f = item
            if STOP.is_set():
                return
            rec = call_once(cl, a.task, r, prompt, ph)
            if rec.get("http_status") in (400, 401, 403, 404):
                return            # configuration error: logged, not cached, so the fixed rerun sends this sample again
            f.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
            with LOCK:
                done[0] += 1
                print(f"[{done[0]}/{len(todo)}] {r['sample_id']} {r.get('stage', '')} {rec['status']} "
                      f"in={rec.get('prompt_tokens')} out={rec.get('completion_tokens')} {rec.get('seconds')}s "
                      f"model={rec.get('model', '')}", flush=True)
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(work, todo))
        if STOP.is_set():
            sys.exit("Stopped on a configuration error; nothing else was sent. Fix the setting and run the same command again.")
    rebuild(a.task)


if __name__ == "__main__":
    main()
