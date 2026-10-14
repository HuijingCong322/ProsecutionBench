"""Generate OAs or evaluate them. O2 is never read by the generation path."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from common import ROOT, AzureRunner, canonical, sha256, read_jsonl, write_jsonl, write_json, generation_validator, judge_validator

def generation_user(row,input_setting="state_with_history"):
    payload={k:row[k] for k in ("sample_id","app_id","cutoff","o1","a1","missing_doc_ids","documents")}
    if input_setting=="state_with_history":payload["predicted_A1_state"]=row["state"]
    elif input_setting!="history_only":raise ValueError("Unknown input setting")
    return "Predict the next examiner communication after the observed A1 response.\n"+canonical(payload)

def state_user(row):
    return (f"Application {row['app_id']}. Stage: A1_cutoff. Cutoff: {row['cutoff']}.\n"
      f"Most recent Office action on the merits before the cutoff: {row['o1']['doc_id']} ({row['o1']['code']}).\n"
      f"Applicant reply filed on the cutoff date (A1): {', '.join(row['a1']['doc_ids'])}.\n"
      "\nDOCUMENTS (oldest first):\n\n"+row["dev_state_input_text"])

def state_validator(obj,sample_id):
    return [] if isinstance(obj,dict) and all(isinstance(obj.get(k),list) for k in ("entered_claims","proposed_claims","rejections")) else ["invalid_dev_state"]

def load_rows(root,split):
    path=Path(root)/"inputs"/f"generation_{split}.jsonl"
    if not path.exists():raise ValueError(f"Missing prepared inputs: {path.name}. The optional extension needs A's additional matching states.")
    rows=read_jsonl(path)
    if split=="extension":
        rows=read_jsonl(Path(root)/"inputs/generation_core.jsonl")+rows
        if len(rows)!=100:
            raise ValueError(f"The 100-case extension is not ready: only {len(rows)} matching A states available. Get the missing A1 states and rebuild; core remains runnable.")
    return rows

def attach_dev_states(rows,runner,root):
    prompt=(Path(root)/"prompts/dev_state_A_frozen.txt").read_text()
    completed=[]
    for row in rows:
        if row["state"] is None:
            result=runner.call("dev_state",row["sample_id"],prompt,state_user(row),row["dev_state_input_hash"],state_validator)
            if result["status"]!="success":raise RuntimeError(f"Development state failed: {row['sample_id']}; inspect outputs/C/cache/dev_state.")
            row=dict(row,state=result["parsed"],state_provenance={"source":"C dev-only extraction with A's frozen prompt",
                "state_hash":sha256(canonical(result["parsed"])),"model":result["model"],"prompt_hash":result["prompt_hash"]})
        completed.append(row)
    write_jsonl(Path(root)/"outputs/C/dev_states.jsonl",[{"sample_id":r["sample_id"],"state":r["state"],"provenance":r["state_provenance"]} for r in completed])
    return completed

def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+",(text or "").lower()))

def citation_audit(candidate,row):
    docs={d["doc_id"]:d["text"] for d in row["documents"]}
    known=set()
    for field in ("entered_claims","proposed_claims"):
        known.update(c.get("claim_id") for c in (row.get("state") or {}).get(field,[]))
    flags=[];total=found=0
    for unit in candidate.get("claim_ground_evidence",[]):
        for cid in unit.get("claim_ids",[]):
            if known and cid not in known:flags.append(f"claim_id_not_in_A_state:{cid}")
        for ev in unit.get("evidence",[]):
            total+=1
            if not isinstance(ev,dict):flags.append("invalid_evidence_object");continue
            did,q=ev.get("doc_id"),norm(ev.get("support_span"))
            if did not in docs:flags.append(f"doc_id_not_in_input:{did}")
            elif len(q.split())<3 or q not in norm(docs[did]):flags.append(f"quote_not_found_in_named_doc:{did}")
            else:found+=1
    for unit in candidate.get("applicant_argument_responses",[]):
        if not isinstance(unit,dict):flags.append("invalid_argument_response");continue
        did=unit.get("support_doc_id")
        if did not in (None,"","insufficient_evidence"):
            total+=1;q=norm(unit.get("support_span"))
            if did not in docs:flags.append(f"argument_doc_not_in_input:{did}")
            elif len(q.split())<3 or q not in norm(docs[did]):flags.append(f"argument_quote_not_found:{did}")
            else:found+=1
    return {"quoted_units":total,"span_found_in_named_doc":found,"flags":flags,
            "note":"Mechanical location check only; does not establish argument support. These quality errors remain in the scoring denominator."}

def generate(root=ROOT,split="core",input_setting="state_with_history",limit=None,runner=None):
    root=Path(root);runner=runner or AzureRunner(root)
    rows=load_rows(root,split)
    if limit:rows=rows[:limit]
    if split=="dev" and input_setting=="state_with_history":rows=attach_dev_states(rows,runner,root)
    prompt=(root/"prompts/examiner_generation.txt").read_text()
    if split!="dev":
        frozen=json.loads((root/"config/frozen_protocol.json").read_text()) if (root/"config/frozen_protocol.json").exists() else None
        if not frozen or frozen["generation_prompt_hash"]!=sha256(prompt):raise ValueError("Run the dev checks, then freeze the prompt before running core. A changed test prompt needs a separate labelled run.")
        if frozen["settings"]["model"]!=runner.cfg["expected_model"]:raise ValueError("Model version changed after freezing. Align it with the team before continuing.")
    output=root/"outputs/C"/f"examiner_generation_{split}_{input_setting}.jsonl"
    merged={r["sample_id"]:r for r in read_jsonl(output)}
    for i,row in enumerate(rows,1):
        user=generation_user(row,input_setting)
        result=runner.call("generation_"+input_setting,row["sample_id"],prompt,user,row["input_hash"],generation_validator)
        result.update({"app_id":row["app_id"],"cutoff":row["cutoff"],"split":split,"input_setting":input_setting,
                       "state_provenance":row["state_provenance"],"missing_doc_ids":row["missing_doc_ids"],
                       "run_id":f"C_{split}_{input_setting}_{sha256(prompt)[:10]}_low8192r16384"})
        if result["status"]=="success":result["citation_audit"]=citation_audit(result["parsed"],row)
        merged[row["sample_id"]]=result
        write_jsonl(output,merged.values())
        print(f"[{i}/{len(rows)}] {row['sample_id']} {result['status']} cached={result.get('cache_reused',False)} logged_est_usd={runner.spent:.3f}",flush=True)
    print("Saved",output)
    return list(merged.values())

def judge(root=ROOT,split="core",input_setting="state_with_history",limit=None,runner=None):
    root=Path(root);runner=runner or AzureRunner(root)
    rows={r["sample_id"]:r for r in load_rows(root,split)}
    if split=="dev":
        for state in read_jsonl(root/"outputs/C/dev_states.jsonl"):
            rows[state["sample_id"]]["state"]=state["state"]
    # Gold is loaded only in this evaluation function.
    gold={r["sample_id"]:r for r in read_jsonl(root/"gold/generation_targets.jsonl")}
    candidates=read_jsonl(root/"outputs/C"/f"examiner_generation_{split}_{input_setting}.jsonl")
    if limit:candidates=candidates[:limit]
    prompt=(root/"prompts/generation_judge.txt").read_text()
    if split!="dev":
        frozen=json.loads((root/"config/frozen_protocol.json").read_text())
        if frozen["judge_prompt_hash"]!=sha256(prompt):raise ValueError("Judge rubric differs from the frozen protocol")
    out=root/"outputs/C"/f"judge_{split}_{input_setting}.jsonl"
    merged={r["sample_id"]:r for r in read_jsonl(out)}
    for i,c in enumerate(candidates,1):
        sid=c["sample_id"]
        if c["status"]!="success":
            merged[sid]={"sample_id":sid,"status":"generation_failed","generation_status":c["status"]}
            write_jsonl(out,merged.values());continue
        row=rows[sid];g=gold[sid]
        payload={"sample_id":sid,"cutoff":row["cutoff"],"record":row["documents"],"predicted_A1_state":row["state"],
                 "candidate":c["parsed"],"mechanical_citation_audit":c.get("citation_audit"),
                 "actual_O2":{"doc_id":g["target_doc_id"],"code":g["target_code"],"date":g["target_date"],"text":g["target_text"]}}
        user=canonical(payload)
        result=runner.call("judge_"+input_setting,sid,prompt,user,row["input_hash"],judge_validator)
        result.update({"candidate_request_hash":c["request_hash"],"candidate_model":c.get("model"),
                       "input_setting":input_setting,"split":split,"run_id":c["run_id"]+"_judge"})
        merged[sid]=result;write_jsonl(out,merged.values())
        print(f"[{i}/{len(candidates)}] judge {sid} {result['status']} logged_est_usd={runner.spent:.3f}",flush=True)
    return list(merged.values())

def freeze(root=ROOT):
    root=Path(root)
    from common import load_config
    cfg=load_config(root)
    results=read_jsonl(root/"outputs/C/examiner_generation_dev_state_with_history.jsonl")
    generation_hash=sha256((root/"prompts/examiner_generation.txt").read_text())
    judge_hash=sha256((root/"prompts/generation_judge.txt").read_text())
    valid=[r for r in results if r['status']=='success' and r.get('prompt_hash')==generation_hash and r.get('model')==cfg['expected_model']]
    required={r['sample_id'] for r in read_jsonl(root/"inputs/generation_dev.jsonl")}
    if len(required)!=3 or {r['sample_id'] for r in valid}!=required:
        raise ValueError("All three dev generations must finish successfully before freezing. Inspect dev outputs first.")
    candidate_hashes={r['request_hash'] for r in valid}
    dev_judges=read_jsonl(root/"outputs/C/judge_dev_state_with_history.jsonl")
    if not any(j.get('status')=='success' and j.get('prompt_hash')==judge_hash and j.get('model')==cfg['expected_model'] and j.get('candidate_request_hash') in candidate_hashes for j in dev_judges):
        raise ValueError("Complete at least one valid dev judge with the current rubric and candidate before freezing.")
    if any(root.glob("outputs/C/examiner_generation_core_*.jsonl")):
        raise ValueError("Core has already started. Do not refreeze settings or tune on test outputs.")
    value={"generation_prompt_hash":generation_hash,
           "judge_prompt_hash":judge_hash,
           "settings":{"model":cfg["expected_model"],"reasoning_effort":"low","max_completion_tokens":8192,
                       "truncation_retry_tokens":16384,"temperature":"not_set"},
           "primary_score_view":"full","substantive_score_view":"diagnostic",
           "dev_ids":[r["sample_id"] for r in results],"data_version":"v1.2"}
    write_json(root/"config/frozen_protocol.json",value);print(json.dumps(value,indent=2))

def ping(root=ROOT):
    runner=AzureRunner(root)
    def check(x,s):return [] if isinstance(x,dict) and x.get("ok")==True else ["bad_ping"]
    r=runner.call("connection_test","ping","Return exactly a JSON object with key ok and boolean true.","Connection test. Return JSON.","connection_test",check)
    if r["status"]!="success":raise RuntimeError("Connection test did not return a complete valid result")
    print("Connection OK. actual model:",r["model"],"settings: low, 8192 with one retry at 16384; no temperature.")

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("task",choices=["ping","generate","judge","freeze"])
    ap.add_argument("--root",default=str(ROOT));ap.add_argument("--split",choices=["dev","core","extension"],default="core")
    ap.add_argument("--input-setting",choices=["state_with_history","history_only"],default="state_with_history");ap.add_argument("--limit",type=int)
    a=ap.parse_args()
    if a.task=="ping":ping(a.root)
    elif a.task=="freeze":freeze(a.root)
    else:globals()[a.task](a.root,a.split,a.input_setting,a.limit)
