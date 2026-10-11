"""Score predicted states against gold snapshots (A, week-3 pilot).
Usage: python3 A/scripts/score_state.py [--gold A/gold/state_gold.jsonl] [--pred A/outputs/state_predictions.jsonl]
Claim (claim-version accuracy): over every gold claim record (entered and proposed lists, keyed by list
  and claim_id), the share whose predicted record in the same list has the same claim_id, version_id
  and status, and normalized text similarity >= 0.90 (token-level SequenceMatcher ratio; lowercase,
  punctuation removed). Canceled claims compare status only. Component accuracies are reported too.
Rej (rejection-status macro-F1): (claim_id, ground, status) tuples; F1 per status class (precision and
  recall over tuples with that gold/predicted status), macro-averaged over the fixed classes that occur
  in gold. (claim, ground) micro-F1 ignoring status is reported as a diagnostic.
Aggregation (fixed before scoring): records are pooled within each stage (O1_cutoff, A1_cutoff); 'all'
  pools both stages. Missing or unparsable predictions count as empty states (all gold records wrong).
Writes A/state_metrics.json and A/outputs/state_scores_per_record.csv."""
import argparse, csv, json, re
from difflib import SequenceMatcher
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--gold", default=str(A / "gold" / "state_gold.jsonl"))
ap.add_argument("--pred", default=str(A / "outputs" / "state_predictions.jsonl"))
ap.add_argument("--include-objections", action="store_true",
                help="count claim objections as rejection records (default: Rej covers rejections only; "
                     "objections are not rejections under 35 U.S.C. and are scored separately as a diagnostic)")
a = ap.parse_args()
ARGS_INCLUDE_OBJ = a.include_objections
from collections import defaultdict as _dd
OBJ = _dd(lambda: (set(), set()))   # (gold, pred) objection (claim, ground) pairs per snapshot
STATUSES = ["outstanding", "withdrawn", "overcome", "moot", "unknown"]


def norm(t):
    return re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split()


def sim(x, y):
    x, y = norm(x), norm(y)
    if not x and not y:
        return 1.0
    return SequenceMatcher(None, x, y, autojunk=False).ratio()


gold = {(g["app_id"], g["stage"]): g for g in map(json.loads, open(a.gold))}
pred = {}
for p in map(json.loads, open(a.pred)):
    if p.get("parse_ok"):
        pred[(p["app_id"], p["stage"])] = p["state"]

rows, rej = [], {}
for key, g in gold.items():
    p = pred.get(key) or {"entered_claims": [], "proposed_claims": [], "rejections": []}
    for lst in ("entered_claims", "proposed_claims"):
        pm = {}
        for c in p.get(lst) or []:
            try:
                pm.setdefault(int(c.get("claim_id")), c)
            except (TypeError, ValueError):
                pass
        for c in g[lst]:
            q = pm.get(int(c["claim_id"]))
            found = q is not None
            ver = found and str(q.get("version_id")) == str(c["version_id"])
            st = found and q.get("status") == c["status"]
            s = sim(c["text"], q.get("text")) if found else 0.0
            txt = c["status"] == "canceled" or s >= 0.90
            rows.append({"app_id": key[0], "stage": key[1], "list": lst, "claim_id": c["claim_id"],
                         "found": found, "version_ok": ver, "status_ok": st, "text_sim": round(s, 3),
                         "text_ok": found and txt, "correct": bool(found and ver and st and txt)})
    gt, pt = set(), set()
    for src, dst in ((g["rejections"], gt), (p.get("rejections") or [], pt)):
        for r in src:
            try:
                t = (int(r.get("claim_id")), str(r.get("ground")), str(r.get("status")))
            except (TypeError, ValueError):
                continue
            if t[1] == "objection" and not ARGS_INCLUDE_OBJ:
                OBJ[key][0 if dst is gt else 1].add(t[:2])
                continue
            dst.add(t)
    rej[key] = (gt, pt)


def claim_metrics(rs):
    n = len(rs)
    f = lambda k: round(sum(r[k] for r in rs) / n, 4) if n else None
    return {"n_records": n, "claim_version_accuracy": f("correct"), "id_found": f("found"),
            "version_acc": f("version_ok"), "status_acc": f("status_ok"), "text_acc": f("text_ok")}


def rej_metrics(keys):
    G = {(k, t) for k in keys for t in rej[k][0]}
    P = {(k, t) for k in keys for t in rej[k][1]}
    per = {}
    for s in STATUSES:
        g = {x for x in G if x[1][2] == s}
        p = {x for x in P if x[1][2] == s}
        if not g:
            continue
        tp = len(g & p)
        pr = tp / len(p) if p else 0.0
        rc = tp / len(g)
        per[s] = {"gold": len(g), "pred": len(p), "f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0}
    g2 = {(k, t[:2]) for k, t in G}
    p2 = {(k, t[:2]) for k, t in P}
    tp = len(g2 & p2)
    pr, rc = (tp / len(p2) if p2 else 0.0), (tp / len(g2) if g2 else 0.0)
    return {"n_gold_tuples": len(G), "rejection_status_macro_f1":
            round(sum(v["f1"] for v in per.values()) / len(per), 4) if per else None,
            "per_status": per, "claim_ground_micro_f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0}


out = {"gold_snapshots": len(gold), "predicted_snapshots": sum(k in pred for k in gold),
       "missing_or_unparsable": [f"{k[0]}:{k[1]}" for k in gold if k not in pred]}
for stage in ("O1_cutoff", "A1_cutoff", "all"):
    ks = [k for k in gold if stage == "all" or k[1] == stage]
    og = {(k, t) for k in ks for t in OBJ[k][0]}; op = {(k, t) for k in ks for t in OBJ[k][1]}
    tp = len(og & op)
    out[stage] = {"n_snapshots": len(ks), **claim_metrics([r for r in rows if stage == "all" or r["stage"] == stage]),
                  **rej_metrics(ks),
                  "objections_excluded": not ARGS_INCLUDE_OBJ,
                  "objection_diag": {"gold": len(og), "pred": len(op), "recall": round(tp / len(og), 3) if og else None,
                                     "precision": round(tp / len(op), 3) if op else None}}
(A / "state_metrics.json").write_text(json.dumps(out, indent=1))
with open(A / "outputs" / "state_scores_per_record.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(json.dumps({s: {k: out[s][k] for k in ("n_snapshots", "claim_version_accuracy", "rejection_status_macro_f1")}
                  for s in ("O1_cutoff", "A1_cutoff", "all")}, indent=1))
