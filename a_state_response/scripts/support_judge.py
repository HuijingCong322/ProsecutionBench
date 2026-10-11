"""Supp judge (A, week 3; replaces the 53-unit manual first pass, see A/README.md).
For every argument unit of the 10 gold replies (A/outputs/applicant_response.jsonl):
  support_doc_id = insufficient_evidence          -> unknown (no call)
  support_span not found verbatim in the record   -> not_supported (no call; mechanical rule)
  otherwise -> GPT-5-mini judge with prompts/support_judge.txt (reasoning_effort low, JSON), given the assertion,
               the span and +-3000 characters of the cited document around the span.
Output: gold/argument_support_judge.jsonl (cache by unit + prompt hash). Same Azure env vars as run_state.py."""
import hashlib, json, os, re, sys, time
from pathlib import Path
A = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(A / "scripts"))
PROMPT = (A / "prompts" / "support_judge.txt").read_text(); PH = hashlib.sha1(PROMPT.encode()).hexdigest()[:10]
inputs = {r["app_id"]: r for r in map(json.loads, open(A / "inputs" / "response_inputs.jsonl"))}
def norm(t): return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split())
def blocks(app):
    d = {}
    for b in re.split(r"\n(?==== DOC )", inputs[app]["input_text"]):
        m = re.match(r"=== DOC (\S+) \| (\S+) \|", b)
        if m: d[m.group(1)] = (m.group(2), b)
    return d
def window(text, span, w=3000):
    q = norm(span).split()[:8]; t = text
    # locate approximately: find first 8 normalized tokens in a normalized copy, map back by ratio
    nt = norm(t); i = nt.find(" ".join(q))
    if i < 0: return t[:2 * w]
    pos = int(i / max(1, len(nt)) * len(t))
    return t[max(0, pos - w): pos + w]
units = []
for p in map(json.loads, open(A / "outputs" / "applicant_response.jsonl")):
    if p["group"] != "gold" or not p["parse_ok"]: continue
    d = blocks(p["app_id"])
    for k, u in enumerate(p["response"].get("arguments") or []):
        did = re.sub(r"^\s*DOC\s+", "", str(u.get("support_doc_id", ""))).strip(); span = u.get("support_span", "")
        q = norm(span); unk = did.lower() in ("", "insufficient_evidence")
        found = None if unk else next((x for x in ([did] if did in d else []) + list(d) if len(q.split()) >= 3 and q in norm(d[x][1])), None)
        units.append({"app_id": p["app_id"], "unit": k + 1, "unit_id": f"{p['app_id']}_u{k+1}", "claim_ids": u.get("claim_ids"),
                      "rejection": u.get("rejection"), "assertion": u.get("assertion", ""), "support_doc_id": did,
                      "support_span": span, "found_in": found, "doc_type": d[found][0] if found else "",
                      "context": window(d[found][1], span) if found else ""})
out = A / "gold" / "argument_support_judge.jsonl"
cache = {}
if out.exists():
    for x in map(json.loads, open(out)): cache[(x["unit_id"], x.get("prompt_hash"))] = x
cl = None; res = []
for u in units:
    base = {k: u[k] for k in ("unit_id", "app_id", "unit", "claim_ids", "rejection", "assertion", "support_doc_id", "support_span", "found_in")}
    if u["support_doc_id"].lower() in ("", "insufficient_evidence"):
        res.append(base | {"label": "unknown", "source": "rule: insufficient_evidence", "reason": ""}); continue
    if not u["found_in"]:
        res.append(base | {"label": "not_supported", "source": "rule: span not found verbatim in the record", "reason": ""}); continue
    if (u["unit_id"], PH) in cache:
        res.append(cache[(u["unit_id"], PH)]); continue
    if cl is None:
        from run_state import client; cl = client()
    msg = (f"Argument unit (answers rejection '{u['rejection']}' of claims {u['claim_ids']}):\n{u['assertion']}\n\n"
           f"Cited document: {u['support_doc_id']} (found in {u['found_in']}, type {u['doc_type']})\n"
           f"support_span: {u['support_span']}\n\nText of the document around the span:\n{u['context']}")
    for attempt in range(6):
        try:
            r = cl.chat.completions.create(model=os.environ["AZURE_DEPLOYMENT"], messages=[{"role": "system", "content": PROMPT},
                 {"role": "user", "content": msg}], max_completion_tokens=4096, reasoning_effort="low", response_format={"type": "json_object"})
            j = json.loads(r.choices[0].message.content); break
        except Exception as e:
            print("retry", u["unit_id"], str(e)[:120]); time.sleep(10 * (attempt + 1)); j = None
    lab = (j or {}).get("label", "unknown")
    res.append(base | {"label": lab if lab in ("supported", "not_supported", "unknown") else "unknown", "source": "llm judge",
                       "reason": (j or {}).get("reason", ""), "prompt_hash": PH, "model": os.environ.get("AZURE_DEPLOYMENT")})
    print(u["unit_id"], res[-1]["label"], flush=True)
with open(out, "w") as f:
    for x in res: f.write(json.dumps(x, ensure_ascii=False) + "\n")
from collections import Counter
print("units", len(res), Counter((x["source"].split(":")[0], x["label"]) for x in res))
