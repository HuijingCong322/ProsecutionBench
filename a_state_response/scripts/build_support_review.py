"""Argument-support review sheet for the 10 gold apps (A first pass; C second pass on >= 5 replies).
One row per argument unit of A/outputs/applicant_response.jsonl (group gold). span_found is automatic: the
support_span occurs verbatim (case, whitespace, punctuation ignored) in the cited input document, or in another one.
Reviewer fills judgment = supported / not_supported / unknown (week-3 plan, section 3 step 6).
Output: gold/argument_support_review.xlsx (never overwrites an existing file) and argument_support_review.csv."""
import csv, json, re
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
A = Path(__file__).resolve().parent.parent; G = A / "gold"; S = A.parent / "data_v1_share"
inputs = {r["app_id"]: r for r in map(json.loads, open(A / "inputs" / "response_inputs.jsonl"))}
def norm(t): return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split())
def docs(app):
    d = {}
    for blk in re.split(r"\n(?==== DOC )", inputs[app]["input_text"]):
        m = re.match(r"=== DOC (\S+) \| (\S+) \| (\S+)", blk)
        if m: d[m.group(1)] = (m.group(2), m.group(3), norm(blk))
    return d
def locate(app, did, span):
    """line number of the first line of `span` in the text file of doc `did` (normalized match), or None"""
    e = json.loads((S / "examples" / f"{app}.json").read_text())
    x = next((i for i in e["inputs"] if i["doc_id"] == did), None)
    if not x or not x["text_path"] or x["text_path"].endswith(".json"): return None
    lines = (S / x["text_path"]).read_text().splitlines(); q = norm(span).split()
    if len(q) < 3: return None
    head = " ".join(q[:6])
    for i in range(len(lines)):
        if head in norm(" ".join(lines[i:i + 6])): return i + 1
    return None
def textpath(app, did):
    e = json.loads((S / "examples" / f"{app}.json").read_text())
    x = next((i for i in e["inputs"] if i["doc_id"] == did), None)
    return f"file:///Users/fionay/examinerbench/data_v1_share/{x['text_path']}" if x and x["text_path"] else ""
rows = []
for p in map(json.loads, open(A / "outputs" / "applicant_response.jsonl")):
    if p["group"] != "gold" or not p["parse_ok"]: continue
    d = docs(p["app_id"])
    for k, u in enumerate(p["response"].get("arguments") or []):
        did = re.sub(r"^\s*DOC\s+", "", str(u.get("support_doc_id", ""))).strip()
        q = norm(u.get("support_span", ""))
        unk = did.lower() in ("", "insufficient_evidence")
        where = "" if unk or len(q.split()) < 3 else ("cited doc" if did in d and q in d[did][2] else
                 next((f"other doc {o}" for o, v in d.items() if q in v[2]), "NOT FOUND"))
        found_doc = did if where == "cited doc" else (where.split(" ")[-1] if where.startswith("other doc") else did)
        ln = locate(p["app_id"], found_doc, u.get("support_span", "")) if where and where != "NOT FOUND" else None
        if ln: where += f"，第 {ln} 行附近"
        rows.append({"app_id": p["app_id"], "unit": k + 1, "claim_ids": ", ".join(map(str, u.get("claim_ids") or [])),
                     "rejection": u.get("rejection", ""), "assertion": u.get("assertion", ""),
                     "support_doc_id": did, "doc_type": d.get(did, ("", ""))[0], "support_span": u.get("support_span", ""),
                     "span_found": "insufficient_evidence" if unk else where, "link": "" if unk else textpath(p["app_id"], found_doc)})
with open(A / "argument_support_review.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]) + ["judgment", "reason"]); w.writeheader(); w.writerows(rows)
out = G / "argument_support_review.xlsx"
if not (G / "~$argument_support_review.xlsx").exists() and not (G / "argument_support_review_done.xlsx").exists():
    wb = Workbook(); ws = wb.active; ws.title = "units"
    hdr = ["#", "app_id", "论点编号", "针对的 claims", "针对的驳回", "论点（模型写的）", "引用文件", "文件类型", "引用原文（模型声称）",
           "原文是否找得到（自动）", "打开文件", "judgment (supported / not_supported / unknown)", "理由（简短）"]
    ws.append(hdr)
    for c in ws[1]: c.font = Font(bold=True)
    for i, r in enumerate(rows, 1):
        ws.append([i, r["app_id"], r["unit"], r["claim_ids"], r["rejection"], r["assertion"], r["support_doc_id"], r["doc_type"],
                   r["support_span"], r["span_found"], "", "", ""])
        if r["link"]:
            c = ws.cell(ws.max_row, 11); c.value = "文本"; c.hyperlink = r["link"]; c.font = Font(color="0563C1", underline="single")
        if r["span_found"] in ("NOT FOUND", "insufficient_evidence"):
            for c in ws[ws.max_row][:10]: c.fill = PatternFill("solid", fgColor="FDE2E1")
    for col, wd in zip("ABCDEFGHIJKLM", [4, 10, 6, 10, 8, 60, 18, 8, 60, 14, 6, 14, 30]): ws.column_dimensions[col].width = wd
    for row in ws.iter_rows():
        for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "F2"
    g = wb.create_sheet("说明")
    for t in ["每行是模型答复里的一条论点（argument unit）。判断这条论点有没有被它引用的原文支持。",
              "supported：引用原文确实在那份文件里（看'原文是否找得到'），而且这段原文能支撑这条论点，且针对的是当时有效的那版 claim。",
              "not_supported：原文找不到；或原文和论点说的不是一回事；或只是引用审查员对对比文件的转述来证明对比文件'没有公开'某特征（计划第 4 页：不能把 prior-art 标题、引用编号或审查员的转述当作已核实的技术支持）。",
              "unknown：模型写了 insufficient_evidence（粉色行），或者你无法判断。",
              "'原文是否找得到'：cited doc = 在它引用的文件里逐字找到；other doc = 在别的文件里找到；NOT FOUND = 哪都找不到（粉色，多半 not_supported）。"]:
        g.append([t])
    g.column_dimensions["A"].width = 150
    wb.save(out)
from collections import Counter
print(len(rows), "units", Counter(r["span_found"].split(" ")[0] for r in rows))
