"""Score Applicant Response outputs (A, week 3).
Usage: python3 A/scripts/score_response.py
Strat (macro-F1, week-3 plan): multi-label over the fixed labels amendment / argument / cancellation / other;
  per-label F1 over the 10 gold apps, macro-averaged over the labels that occur in the gold labels
  (gold/response_strategy_gold.csv). Supplementary: the 90 other test_core apps against the automatic labels.
Edit (limitation-level F1, gold only): every claim is split into limitations at ';' ':' and 'wherein'/'whereby'.
  Reference units come from gold/claim_edits_gold.jsonl (pre -> post claim text): an amended claim yields
  (+, claim, limitation) for limitations of post with no match in pre and (-, claim, limitation) for the
  reverse; an added claim yields + units for all its limitations; a canceled claim yields one (cancel, claim)
  unit. Two limitations are the same inside a claim (pre vs post) when their tokens are identical (SAME = 1.0),
  and a predicted unit matches a reference unit when token-level similarity >= MATCH (0.6). Predicted units are computed the same way from the
  same pre text to the model's new_text (the markup pre text for claims amended in the real reply, otherwise the
  state-gold text of the claim under examination). Greedy one-to-one matching; F1 pooled over all units.
Edit is also reported separately for apps with edits and apps whose real reply has no edit (no_edit): for a
  no_edit app the prediction is correct when it proposes no edit (empty-set rule; such apps add no units to F1).
Supp (week-3 plan): argument units are the model's 'arguments' entries. A unit with support_doc_id
  'insufficient_evidence' is unknown (not verifiable). For the other units the reviewer judges in
  gold/argument_support_review_done.xlsx whether the cited span exists, supports the assertion and concerns the
  right claim version: supported / not_supported / unknown. Supp = supported / verifiable units; total units,
  unknown and coverage (= units with a citation / total) are reported. 'span_found' (the span occurs verbatim,
  ignoring case, whitespace and punctuation, in the cited document) is computed automatically to help the reviewer.
Writes A/response_metrics.json."""
import csv, json, re
from difflib import SequenceMatcher
from pathlib import Path
from openpyxl import load_workbook
A = Path(__file__).resolve().parent.parent; S = A.parent / "data_v1_share"; G = A / "gold"
SAME, MATCH = 1.0, 0.6
LABELS = ["amendment", "argument", "cancellation", "other"]
pred = {p["app_id"]: p for p in map(json.loads, open(A / "outputs" / "applicant_response.jsonl"))}
inputs = {r["app_id"]: r for r in map(json.loads, open(A / "inputs" / "response_inputs.jsonl"))}

def tok(t): return re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split()
def sim(a, b): return SequenceMatcher(None, tok(a), tok(b), autojunk=False).ratio()
def macro_f1(ref, hyp):
    per = {}
    for L in LABELS:
        g = {k for k, v in ref.items() if L in v}
        if not g: continue
        p = {k for k, v in hyp.items() if L in v}
        tp = len(g & p); pr = tp / len(p) if p else 0.0; rc = tp / len(g)
        per[L] = round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0
    return round(sum(per.values()) / len(per), 4) if per else None, per

def strategies(app):
    p = pred.get(app)
    return set(p["response"].get("strategies") or []) if p and p["parse_ok"] else set()

# ---- Strat
gsrc = list(csv.DictReader(open(G / "response_strategy_gold.csv")))
gold_strat = {r["app_id"]: set(filter(None, r["strategies"].split(";"))) for r in gsrc}
NOEDIT = {r["app_id"] for r in gsrc if r["no_edit"] == "True"}
MAP4 = {"amend_claims": "amendment", "add_claims": "amendment", "amend_specification": "amendment", "amend_drawings": "amendment",
        "argue": "argument", "cancel_claims": "cancellation", "interview": "other", "terminal_disclaimer": "other",
        "declaration_affidavit": "other"}
auto4 = {r["app_id"]: {MAP4[l] for l in r["strategy"].split(";") if l in MAP4}
         for r in csv.DictReader(open(S / "labels.csv")) if r["test_core"] == "True" and r["gold_subset"] != "True"}
tc = {a for a, p in pred.items() if p["group"] == "test_core"}
if tc:
    m, per = macro_f1({a: auto4[a] for a in tc}, {a: strategies(a) & set(LABELS) for a in tc})
    supp_tc = {"strat_test_core_supplementary": {"n": len(tc), "of": len(auto4), "macro_f1": m, "per_label": per,
               "note": "automatic labels (data_v1 labels.csv 'strategy', mapped to 4 labels); input setting record_only (no predicted O1 state)"}}
else:
    supp_tc = {}
pred = {a: p for a, p in pred.items() if p["group"] == "gold"}
out = {"n_predictions": len(pred), "parse_failures": [a for a, p in pred.items() if not p["parse_ok"]],
       "gold_label_sources": sorted({r["source"] for r in gsrc}), **supp_tc}
m, per = macro_f1(gold_strat, {a: strategies(a) & set(LABELS) for a in gold_strat})
out["strat"] = {"n": len(gold_strat), "macro_f1": m, "per_label": per,
                "per_app": {a: {"gold": sorted(gold_strat[a]), "pred": sorted(strategies(a))} for a in gold_strat}}

# ---- Edit
def clean(t):   # drop listing artefacts: "IN THE CLAIMS:", status labels, leading claim numbers
    t = re.sub(r"(?i)\bIN\s*T\s*H\s*E\s+CLAIMS\s*:?", "", t or "")
    t = re.sub(r"(?i)\(\s*(previously\s+presented|currently\s+amended|original|new|withdrawn|canceled|cancelled)\s*\)", "", t)
    return re.sub(r"^\s*(\d{1,3}\s*[.)]?\s*)+", "", t.strip())
def segs(text):
    return [s.strip() for s in re.split(r";|:|\bwherein\b|\bwhereby\b", clean(text), flags=re.I) if len(tok(s)) >= 3]
def units(cid, action, pre, post):
    if action == "cancel": return [("cancel", cid, "")]
    a, b = segs(pre) if action == "amend" else [], segs(post)
    plus = [("+", cid, s) for s in b if not any(sim(s, x) >= SAME for x in a)]
    minus = [("-", cid, s) for s in a if not any(sim(s, x) >= SAME for x in b)]
    return plus + minus
def match(ref, hyp):
    used, tp = set(), 0
    for h in hyp:
        best, bi = 0.0, None
        for i, r in enumerate(ref):
            if i in used or r[0] != h[0] or r[1] != h[1]: continue
            s = 1.0 if h[0] == "cancel" else sim(h[2], r[2])
            if s > best: best, bi = s, i
        if bi is not None and best >= MATCH: used.add(bi); tp += 1
    return tp
tp = nr = nh = 0; per_app = {}
gold_state = {g["app_id"]: g for g in map(json.loads, open(G / "state_gold.jsonl")) if g["stage"] == "A1_cutoff"}
for x in map(json.loads, open(G / "claim_edits_gold.jsonl")):
    app = x["app_id"]; pre = {c["claim_id"]: c["text"] for c in gold_state[app]["entered_claims"] if c["status"] != "canceled"}
    pre.update({e["claim_id"]: e["pre_text"] for e in x["edits"] if e["action"] == "amend"})   # same base text as the reference
    ref = [u for e in x["edits"] for u in units(e["claim_id"], e["action"], e["pre_text"], e["post_text"])]
    hyp = []
    p = pred.get(app)
    for e in ((p["response"].get("edits") or []) if p and p["parse_ok"] else []):
        try: cid = int(e.get("claim_id"))
        except (TypeError, ValueError): continue
        act = e.get("action")
        if act == "amend" and cid not in pre: act = "add"
        if act not in ("amend", "add", "cancel"): continue
        hyp += units(cid, act, pre.get(cid, ""), e.get("new_text", ""))
    t = match(ref, hyp); tp += t; nr += len(ref); nh += len(hyp)
    per_app[app] = {"ref_units": len(ref), "pred_units": len(hyp), "tp": t, "no_edit_gold": app in NOEDIT}
P = tp / nh if nh else 0.0; R = tp / nr if nr else 0.0
ne = [a for a in per_app if per_app[a]["no_edit_gold"]]
out["edit_no_edit_apps"] = {"n": len(ne), "correct_empty": sum(per_app[a]["pred_units"] == 0 for a in ne)}
out["edit_gold"] = {"precision": round(P, 4), "recall": round(R, 4), "f1": round(2 * P * R / (P + R), 4) if P + R else 0.0,
                    "ref_units": nr, "pred_units": nh, "per_app": per_app, "same": SAME, "match": MATCH}

# ---- Supp
def norm(t): return " ".join(tok(t))
docs = {}
def doc_texts(app):
    if app not in docs:
        d = {}
        for blk in re.split(r"\n(?==== DOC )", inputs[app]["input_text"]):
            m = re.match(r"=== DOC (\S+) \|", blk)
            if m: d[m.group(1)] = norm(blk)
        docs[app] = d
    return docs[app]
def grounded(app, ev):
    d = doc_texts(app); q = norm(ev.get("quote", ""))
    if len(q.split()) < 3: return False
    did = re.sub(r"^\s*DOC\s+", "", str(ev.get("doc_id", ""))).strip()
    return q in d.get(did, "") or any(q in t for t in d.values())
supp_rows = []
for app, p in pred.items():
    if not p["parse_ok"]: continue
    for k, u in enumerate(p["response"].get("arguments") or []):
        did = str(u.get("support_doc_id", "")).strip()
        unk = did.lower() in ("", "insufficient_evidence")
        supp_rows.append({"app_id": app, "unit": k, "unknown": unk,
                          "span_found": (not unk) and grounded(app, {"doc_id": did, "quote": u.get("support_span", "")})})
tot = len(supp_rows); unk = sum(r["unknown"] for r in supp_rows)
out["supp_auto"] = {"units": tot, "unknown": unk, "coverage": round((tot - unk) / tot, 4) if tot else None,
                    "span_found_rate": round(sum(r["span_found"] for r in supp_rows) / max(1, tot - unk), 4)}
jf = G / "argument_support_judge.jsonl"
if jf.exists():
    J = [json.loads(l) for l in open(jf)]
    cited = [x for x in J if x["source"] != "rule: insufficient_evidence"]
    dec = [x for x in cited if x["label"] in ("supported", "not_supported")]
    out["supp"] = {"units": len(J), "with_citation": len(cited), "coverage": round(len(cited) / len(J), 4) if J else None,
                   "verifiable": len(dec), "supported": sum(x["label"] == "supported" for x in dec),
                   "unknown": sum(x["label"] == "unknown" for x in J),
                   "supp": round(sum(x["label"] == "supported" for x in dec) / len(dec), 4) if dec else None,
                   "by_source": {k: sum(x["source"].startswith(k) for x in J) for k in ("rule: insufficient", "rule: span not found", "llm judge")},
                   "method": "span existence by rule; support by GPT-5-mini judge (prompts/support_judge.txt), uncalibrated unless gold/support_calibration_done.xlsx exists"}
    # calibration: the same 10 units (seed 20261010, one per gold app) labelled independently by A and by C
    def labels(f):
        rows = [r for r in list(load_workbook(f)["calibration"].iter_rows(values_only=True))[1:] if r[0]]
        return {r[1]: str(r[10] or "").strip().lower() for r in rows}
    jl = {x["unit_id"]: x["label"] for x in J}; ann = {}
    for who in ("A", "C"):
        f = G / f"support_calibration_{who}_done.xlsx"
        if f.exists(): ann[who] = {k: v for k, v in labels(f).items() if v in ("supported", "not_supported", "unknown")}
    def agree(a, b):
        ks = [k for k in a if k in b]
        return {"n": len(ks), "agreement": round(sum(a[k] == b[k] for k in ks) / len(ks), 4) if ks else None}
    if ann:
        out["supp_calibration"] = {f"{w}_vs_judge": agree(ann[w], jl) for w in ann}
        if len(ann) == 2: out["supp_calibration"]["A_vs_C"] = agree(ann["A"], ann["C"])
        out["supp"]["method"] = "span existence by rule; support by GPT-5-mini judge, calibrated on 10 units labelled by " + " and ".join(sorted(ann))
done = G / "argument_support_review_done.xlsx"
if done.exists():
    rows = list(load_workbook(done).active.iter_rows(values_only=True))
    h = [str(c or "") for c in rows[0]]; j = next(i for i, c in enumerate(h) if c.startswith("judgment"))
    vals = [str(r[j] or "").strip().lower() for r in rows[1:] if r[0]]
    ver = [v for v in vals if v in ("supported", "not_supported")]
    out["supp"] = {"units": len(vals), "verifiable": len(ver), "supported": sum(v == "supported" for v in ver),
                   "unknown": sum(v in ("unknown", "") for v in vals), "coverage": round(len(ver) / len(vals), 4) if vals else None,
                   "supp": round(sum(v == "supported" for v in ver) / len(ver), 4) if ver else None}
(A / "response_metrics.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk not in ("per_app",)}) for k, v in out.items()}, indent=1))
