"""Reference-based full-text scores and substantive diagnostics. No model calls."""
from __future__ import annotations
import argparse
import csv
import json
import random
import re
import statistics
from collections import Counter
from functools import lru_cache
from pathlib import Path
from common import ROOT, read_jsonl, write_json, sha256
from run_experiments import load_rows

TEMPLATE_COLUMNS=["owner","table3_column","model","input_setting","sample_set","value","eligible_n","scored_n",
                  "failed_n","excluded_reason","split_detail","prompt_version","run_id","source_file","notes"]

def tokens(text):
    return re.findall(r"[a-z0-9]+",text.lower())

def lcs_length(a,b):
    # Exact LCS via a bitset recurrence. It avoids a quadratic Python table for long OAs.
    positions={}
    for i,t in enumerate(b):positions[t]=positions.get(t,0)|(1<<i)
    state=0
    for t in a:
        x=positions.get(t,0)|state
        state=x&~(x-((state<<1)|1))
    return state.bit_count()

def rouge_l(reference,prediction):
    from nltk.stem import PorterStemmer
    stemmer=PorterStemmer()
    stem=lambda seq:[stemmer.stem(t) if len(t)>3 else t for t in seq]
    r,p=stem(tokens(reference)),stem(tokens(prediction))
    if not r or not p:return 0.0
    lcs=lcs_length(r,p)
    return 2*lcs/(len(r)+len(p))

class CachedWordNet:
    @lru_cache(maxsize=50000)
    def synsets(self,word):
        from nltk.corpus import wordnet
        return wordnet.synsets(word)

WN=CachedWordNet()

def meteor(reference,prediction):
    from nltk.translate.meteor_score import meteor_score
    return float(meteor_score([tokens(reference)],tokens(prediction),wordnet=WN,alpha=.9,beta=3.,gamma=.5))

def write_csv(path,rows,columns=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if columns is None:columns=list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore");w.writeheader();w.writerows(rows)

def bootstrap_interval(values,seed=20261012,n=3000):
    if not values:return None
    rng=random.Random(seed);m=len(values)
    means=sorted(sum(values[rng.randrange(m)] for _ in range(m))/m for _ in range(n))
    return [means[int(.025*n)],means[min(n-1,int(.975*n))]]

def summarize(values,eligible,fail_reasons):
    return {"value":statistics.mean(values) if values else None,"eligible_n":eligible,"scored_n":len(values),
            "failed_n":eligible-len(values),"failure_reasons":dict(Counter(fail_reasons)),
            "bootstrap_95_ci":bootstrap_interval(values)}

def score(root=ROOT,split="core",input_setting="state_with_history"):
    root=Path(root);inputs=load_rows(root,split)
    gold={g["sample_id"]:g for g in read_jsonl(root/"gold/generation_targets.jsonl")}
    predictions={p["sample_id"]:p for p in read_jsonl(root/"outputs/C"/f"examiner_generation_{split}_{input_setting}.jsonl")}
    judges={p["sample_id"]:p for p in read_jsonl(root/"outputs/C"/f"judge_{split}_{input_setting}.jsonl")}
    cfg=json.loads((root/"config/azure_config.json").read_text())
    frozen=json.loads((root/"config/frozen_protocol.json").read_text()) if (root/"config/frozen_protocol.json").exists() else {}
    rows=[];all_values={};reasons={};baseline_values={};delta_values=[]
    for variant in ("full","substantive"):
        for metric in ("R-L","MET."):
            all_values[variant,metric]=[];reasons[variant,metric]=[];baseline_values[variant,metric]=[]
    judged=[];judge_fail=[];evidence_unknown=0
    for i,row in enumerate(inputs,1):
        sid=row["sample_id"];g=gold[sid];p=predictions.get(sid);j=judges.get(sid)
        base={"sample_id":sid,"app_id":row["app_id"],"input_hash":row["input_hash"],
              "status":p.get("status") if p else "not_run","prompt_hash":p.get("prompt_hash","") if p else "",
              "model_input_hash":p.get("model_input_hash","") if p else "","target_doc_id":g["target_doc_id"]}
        candidate=None
        if p and p.get("status")=="success":
            if p.get("input_hash")!=row["input_hash"]:base["status"]="stale_input_hash"
            elif p.get("model")!=cfg["expected_model"]:base["status"]="model_version_mismatch"
            elif frozen and p.get("prompt_hash")!=frozen.get("generation_prompt_hash"):base["status"]="stale_prompt_hash"
            else:candidate=p["parsed"]["office_action"]
        o1=next(d["text"] for d in row["documents"] if d["doc_id"]==row["o1"]["doc_id"])
        g0_sub=g.get("o1_substantive") or o1
        for variant,ref,b0 in (("full",g["target_text"],o1),("substantive",g["target_substantive"],g0_sub)):
            for name,fun in (("R-L",rouge_l),("MET.",meteor)):
                column=("rougeL" if name=="R-L" else "meteor")+"_"+variant
                base[column]=None;base["G0_"+column]=None
                if not ref.strip():reasons[variant,name].append("missing_reference");continue
                try:
                    bscore=fun(ref,b0);baseline_values[variant,name].append(bscore);base["G0_"+column]=bscore
                except Exception as exc:base["G0_"+column+"_error"]=type(exc).__name__
                if candidate is None:reasons[variant,name].append(base["status"]);continue
                try:
                    value=fun(ref,candidate);base[column]=value;all_values[variant,name].append(value)
                    if variant=="full" and name=="R-L" and base["G0_"+column] is not None:delta_values.append(value-base["G0_"+column])
                except Exception as exc:
                    reasons[variant,name].append("metric_error_"+type(exc).__name__)
                    base[column+"_error"]=type(exc).__name__
        base["judge_overall"]=None;base["judge_evidence_status"]=""
        if candidate is not None and j and j.get("status")=="success" and j.get("model")==cfg["expected_model"] and j.get("candidate_request_hash")==p["request_hash"] and j.get("prompt_hash")==frozen.get("judge_prompt_hash",j.get("prompt_hash")):
            base["judge_overall"]=j["parsed"]["overall"];judged.append(base["judge_overall"])
            base["judge_evidence_status"]=j["parsed"]["evidence_status"]
            evidence_unknown+=j["parsed"]["evidence_status"]=="unknown"
        else:judge_fail.append("generation_invalid" if candidate is None else j.get("status","judge_missing") if j else "judge_not_run")
        if p and p.get("citation_audit"):
            base["citation_audit_flags"]=";".join(p["citation_audit"]["flags"])
            base["span_found_in_named_doc"]=p["citation_audit"]["span_found_in_named_doc"]
            base["quoted_units"]=p["citation_audit"]["quoted_units"]
        rows.append(base)
        print(f"[{i}/{len(inputs)}] metrics {sid} {base['status']}",flush=True)
    full={name:summarize(all_values["full",name],len(inputs),reasons["full",name]) for name in ("R-L","MET.")}
    full["Judge"]=summarize(judged,len(inputs),judge_fail)
    result={"sample_set":"gen_core" if split=="core" else split,"input_setting":input_setting,
            "model":cfg["expected_model"],"data_version":"v1.2","full_text_primary":full,
            "substantive_diagnostic":{m:summarize(all_values["substantive",m],len(inputs),reasons["substantive",m]) for m in ("R-L","MET.")},
            "G0_copy_O1":{v:{m:summarize(baseline_values[v,m],len(inputs),["baseline_metric_failed"]*(len(inputs)-len(baseline_values[v,m]))) for m in ("R-L","MET.")} for v in ("full","substantive")},
            "paired_ROUGE_L_minus_G0":summarize(delta_values,len(inputs),["pair_unavailable"]*(len(inputs)-len(delta_values))),
            "judge_evidence_unknown_n":evidence_unknown,"judge_calibration":"not expert validated; D student review pending unless a completed form is supplied",
            "notes":["Primary Table 3 scores use full O2 text; substantive-reference scores are separate diagnostics.",
                     "ROUGE-L uses exact LCS with Porter stemming, equivalent to rouge_score rougeL use_stemmer=True.",
                     "METEOR: NLTK 3.9.2, lower-case ASCII alphanumeric tokens, WordNet, alpha=.9 beta=3 gamma=.5.",
                     "Means are over successful scored cases; coverage and failure counts are reported. Quality and citation errors are not excluded.",
                     "Both generator and judge are GPT-5-mini; historical agreement is not legal validity.",
                     "Supplied substantive text may contain fragments after source template removal; no target text is manually repaired."]}
    suffix=f"{split}_{input_setting}"
    metric_path=root/"metrics/C"/f"generation_metrics_{suffix}.json";write_json(metric_path,result)
    write_csv(root/"metrics/C"/f"generation_scores_{suffix}.csv",rows)
    prompt_hash=sha256((root/"prompts/examiner_generation.txt").read_text())
    run_id=f"C_{split}_{input_setting}_{prompt_hash[:10]}_low8192r16384"
    submitted=[]
    for col,s in full.items():
        submitted.append(dict(owner="C",table3_column=col,model="gpt-5-mini",input_setting=input_setting,
            sample_set="gen_core" if split=="core" else ("gen_subset" if split=="extension" else "dev_not_reportable"),
            value="" if s["value"] is None else s["value"],eligible_n=s["eligible_n"],scored_n=s["scored_n"],failed_n=s["failed_n"],
            excluded_reason=json.dumps(s["failure_reasons"]),split_detail="data_v1 v1.2; fixed nested gen_core 50; no post-cutoff generation inputs",
            prompt_version=f"generation:{prompt_hash}; judge:{sha256((root/'prompts/generation_judge.txt').read_text())}",
            run_id=run_id,source_file=str(metric_path.relative_to(root)),
            notes="Full-text primary; low; 8192 with one 16384 retry; no temperature; unknown evidence retained; same-model judge is not expert validation"))
    name="C_metrics.csv" if split=="core" and input_setting=="state_with_history" else f"C_metrics_{suffix}.csv"
    if split!="dev":write_csv(root/"results"/name,submitted,TEMPLATE_COLUMNS)
    print("Saved metrics and submission:",metric_path,name)
    return result

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=str(ROOT));ap.add_argument("--split",choices=["dev","core","extension"],default="core")
    ap.add_argument("--input-setting",choices=["state_with_history","history_only"],default="state_with_history")
    a=ap.parse_args();score(a.root,a.split,a.input_setting)
