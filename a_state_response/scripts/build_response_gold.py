"""Applicant Response gold for the 10 gold_subset apps (A, week 3).
Strategy: start from the automatic label (data_v1 labels.response_strategy, derived from the A1 document
codes and the A1 claim listing) and apply human decisions from gold/response_strategy_review_done.xlsx when present.
Claim edits (week-3 update plan: "Edit gold = the human-reviewed data_v0 claims_markup"): the A1 claim listing in
  data_v0/apps/<app>/claims_markup/<stem>.txt, whose <ins>/<del> markup was checked against the page images
  (data_v0/markup_review_decisions.csv). amend = claim labelled Currently Amended: pre = text with <del> kept and
  <ins> removed, post = text with <ins> kept and <del> removed; add = claim labelled New (post = its text);
  cancel = canceled in the human-reviewed state gold A1 listing but not already canceled before (state_gold.jsonl).
  The amend/add claim sets from the markup are checked against the state gold and must agree.
Week-3 plan labels (section 3, step 2): amendment / argument / cancellation / other, mapped deterministically from
the 9 fine-grained labels by MAP4 below; no_edit = the reply changes no claim. Both label sets are written.
Outputs: gold/response_strategy_gold.csv, gold/claim_edits_gold.jsonl, gold/response_strategy_review.xlsx (to review)."""
import csv, json, glob, re
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment
A = Path(__file__).resolve().parent.parent; S = A.parent / "data_v1_share"; G = A / "gold"
LABELS = ["amend_claims", "add_claims", "cancel_claims", "argue", "amend_specification", "amend_drawings",
          "interview", "terminal_disclaimer", "declaration_affidavit"]
MAP4 = {"amend_claims": "amendment", "add_claims": "amendment", "amend_specification": "amendment", "amend_drawings": "amendment",
        "argue": "argument", "cancel_claims": "cancellation",
        "interview": "other", "terminal_disclaimer": "other", "declaration_affidavit": "other"}
def to4(labels): return ";".join(sorted({MAP4[l] for l in labels if l in MAP4}))
gold = {(g["app_id"], g["stage"]): g for g in map(json.loads, open(G / "state_gold.jsonl"))}
apps = sorted({k[0] for k in gold})
import sys; sys.path.insert(0, str(A / "scripts")); import markup_edits as M
edits, rows = [], []
for app in apps:
    e = json.loads((S / "examples" / f"{app}.json").read_text())
    g = gold[(app, "A1_cutoff")]
    pre = {c["claim_id"]: c for c in g["entered_claims"]}
    ed, src = [], "no A1 claim listing"
    fs = [f for f in sorted((A.parent / "data_v0" / "apps" / app / "claims_markup").glob("*.txt"))
          if not f.name.endswith((".pages.txt", ".raw.txt"))]
    if fs:
        mk = M.parse(fs[0].read_text()); src = f"data_v0/apps/{app}/claims_markup/{fs[0].name}"
        for n in sorted(mk):
            st, ptxt, qtxt, _ = mk[n]
            if st == "currently_amended": ed.append({"claim_id": n, "action": "amend", "pre_text": ptxt, "post_text": qtxt})
            elif st == "new": ed.append({"claim_id": n, "action": "add", "pre_text": "", "post_text": qtxt})
    sg_am = sorted(c["claim_id"] for c in g["proposed_claims"] if c["status"] == "currently_amended")
    sg_new = sorted(c["claim_id"] for c in g["proposed_claims"] if c["status"] == "new")
    assert sg_am == sorted(x["claim_id"] for x in ed if x["action"] == "amend") and sg_new == sorted(x["claim_id"] for x in ed if x["action"] == "add"), app
    for c in g["proposed_claims"]:
        p = pre.get(c["claim_id"])
        if c["status"] == "canceled" and (not p or p["status"] != "canceled"):
            ed.append({"claim_id": c["claim_id"], "action": "cancel", "pre_text": "", "post_text": ""})
    edits.append({"app_id": app, "a1_cutoff": g["cutoff"], "has_claim_listing": bool(g["proposed_claims"]),
                  "source": src + " (human-reviewed markup); cancellations from state_gold.jsonl", "edits": ed})
    acts = {x["action"] for x in ed}
    rows.append({"app_id": app, "auto": ";".join(sorted(e["labels"]["response_strategy"])), "a1_codes": " ".join(e["a1"]["codes"]),
                 "edits_from_state_gold": ", ".join(f"{a}:{sum(x['action']==a for x in ed)}" for a in ("amend", "add", "cancel") if a in acts),
                 "consistent": "yes" if all((("amend_claims" in e["labels"]["response_strategy"]) == ("amend" in acts),
                                             ("add_claims" in e["labels"]["response_strategy"]) == ("add" in acts),
                                             ("cancel_claims" in e["labels"]["response_strategy"]) == ("cancel" in acts))) else "NO"})
with open(G / "claim_edits_gold.jsonl", "w") as f:
    for x in edits: f.write(json.dumps(x, ensure_ascii=False) + "\n")
# human decisions
done = G / "response_strategy_review_v2_done.xlsx"   # reviewer decisions: column I (ok/fix), J (corrected labels)
dec = {}
if done.exists():
    for x in list(load_workbook(done)["strategy"].iter_rows(values_only=True))[1:]:
        if x[0]: dec[str(x[0])] = (str(x[8] or "").strip().lower(), str(x[9] or "").strip())
with open(G / "response_strategy_gold.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["app_id", "strategies", "strategies_fine", "no_edit", "source", "auto_fine"])
    noedit = {x["app_id"]: not x["edits"] for x in edits}
    for r in rows:
        d, fixv = dec.get(r["app_id"], ("", ""))
        fine, src = (fixv, "human fix (response_strategy_review_v2_done.xlsx)") if d == "fix" else \
                    (r["auto"], "human ok (response_strategy_review_v2_done.xlsx)") if d == "ok" else (r["auto"], "auto (unreviewed)")
        w.writerow([r["app_id"], to4(fine.split(";")), fine, noedit[r["app_id"]], src, r["auto"]])
wb = Workbook(); ws = wb.active; ws.title = "strategy"
ws.append(["app_id", "自动标签 (auto)", "A1 提交的文件类型", "从 state gold 算出的 claim 改动", "自动标签与改动一致?", "建议", "判断 ok/fix", "fix 时写正确标签（分号分隔）"])
for r in rows: ws.append([r["app_id"], r["auto"], r["a1_codes"], r["edits_from_state_gold"], r["consistent"], "", "", ""])
for col, wd in zip("ABCDEFGH", [10, 45, 35, 28, 10, 50, 10, 45]): ws.column_dimensions[col].width = wd
for row in ws.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
if not (G / "~$response_strategy_review.xlsx").exists() and not (G / "response_strategy_review.xlsx").exists():
    wb.save(G / "response_strategy_review.xlsx")      # never overwrite a sheet that may hold reviewer input
print("edits per app:", {x["app_id"]: len(x["edits"]) for x in edits})
for r in rows: print(r)
