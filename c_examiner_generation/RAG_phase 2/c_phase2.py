"""C Phase 2 overlay for immutable ProsecutionBench inputs and reviewed v4."""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

COMMIT = "b1df977eb63ad04fcb736de7574643fb07a343a0"
RELEASE_ID = "B_D_C_v4_reviewed_2026_11_02"
RELEASE_SHA = "1335e2d0cea22484acb03dfba14797908b8d921118670a5435140c5bb240be93"
HANDOFF_SHA = "25e3b454d222e1d6a9bd502423a19ac0df7e86a7bfc461a5cd9243f78cd42066"
MODELS = {"gpt5mini":"gpt-5-mini-2025-08-07","qwen36_27b":"qwen--qwen3.6-27b"}
LABELS = {"gpt5mini":"gpt-5-mini","qwen36_27b":"Qwen3.6-27B"}
SETTINGS = {"prof":"own","mismatch":"mismatched"}
METRICS = ("R-L","MET.","Judge")
DEV_IDS = {"11968167_t1","11968173_t1","11968176_t1"}


def need(test, message):
    if not test:
        raise ValueError(message)


def sha(data, kind="sha256"):
    return hashlib.new(kind, data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def unpack_release(archive, directory):
    directory = Path(directory)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            need(not p.is_absolute() and ".." not in p.parts and p.parts[0]=="B_D_C_phase1_v4_reviewed", "Unexpected release ZIP path")
        z.extractall(directory)
    return directory/"B_D_C_phase1_v4_reviewed"


def csvrows(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))


def uniq(rows, key="sample_id"):
    d = {r[key]:r for r in rows}
    need(len(d)==len(rows), f"Duplicate {key}")
    return d


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Experiment:
    def __init__(self, repo, release, out):
        self.repo, self.release, self.out = map(lambda p:Path(p).resolve(), (repo,release,out))
        self.c = self.repo/"c_examiner_generation"
        self.q = self.c/"qwen36_27b"
        self.g = self.c/"gpt5mini"
        self.version = read(self.release/"RELEASE_MANIFEST.json")
        need(sha((self.release/"RELEASE_MANIFEST.json").read_bytes())==RELEASE_SHA and self.version["release_id"]==RELEASE_ID, "Use the exact reviewed v4 release")
        need(sha((self.release/"HANDOFF_MANIFEST_SHA256.json").read_bytes())==HANDOFF_SHA, "Handoff manifest differs")
        self.release_files = uniq(read(self.release/"HANDOFF_MANIFEST_SHA256.json")["files"], "path")
        mf = self.release/"profile_manifest.csv"
        need(sha(mf.read_bytes())==self.version["profile_manifest_sha256"], "v4 manifest hash differs")
        need(sha((self.release/"prompts/profile_block.txt").read_bytes(),"sha1")==self.version["prompt_sha1"],"v4 profile template differs")
        need(sha((self.release/"source_D/stats_cards.jsonl").read_bytes(),"sha1")==self.version["D_source_cards_sha1"],"D source cards differ")
        pm = csvrows(mf)
        self.profile_rows = {(r["sample_id"],r["setting"]):r for r in pm}
        need(len(pm)==len(self.profile_rows)==300,"Expected 300 unique profiles")
        self.profiles={}
        for key, r in self.profile_rows.items():
            path=r["profile_path"]
            need(path==f"candidate_profiles/{key[1]}/{key[0]}.json","Unexpected profile path")
            raw=(self.release/path).read_bytes()
            need(sha(raw)==self.release_files[path]["sha256"] and sha(raw,"sha1")==r["profile_sha1"],f"v4 profile file hash mismatch {key}")
            p=json.loads(raw)
            need((p["sample_id"],p["setting"])==key and p["cutoff"]==r["cutoff"],f"Profile mapping mismatch {key}")
            need(sha(p["profile_text"],"sha1")==p["profile_text_sha1"]==r["profile_text_sha1"] and p["profile_block_sha1"]==self.version["prompt_sha1"],f"Profile text/template mismatch {key}")
            need(p["retrieved_k"]==int(r["retrieved_k"])==len(p["retrieved_cases"]) and p["D_card_sha1"]==r["D_card_sha1"]==r["card_sha1"],f"Profile metadata mismatch {key}")
            self.profiles[key]=p
        need(dict(Counter(str(p["retrieved_k"]) for p in self.profiles.values()))==self.version["actual_k_counts"],"Unexpected full v4 coverage")

        snap=read(self.q/"config/source_snapshot_hashes.json")
        qp=read(self.q/"config/frozen_protocol.json")
        gp=read(self.g/"config/frozen_protocol.json")
        self.source_hashes={}
        def verify(path, expected):
            actual=sha(path.read_bytes())
            need(actual==expected,f"Frozen C source changed: {path.name}")
            self.source_hashes[str(path.relative_to(self.repo))]=actual
        for rel in ["inputs/generation_core.jsonl","inputs/generation_dev.jsonl","gold/generation_targets.jsonl","prompts/examiner_generation.txt","prompts/generation_judge.txt","code/legacy/common.py","code/legacy/run_experiments.py","code/legacy/score_generation.py"]:
            verify(self.q/rel,snap[rel])
        verify(self.q/"code/qwen_c_runner.py",qp["implementation_hash"])
        self.configs={"gpt5mini":read(self.q/"config/azure_config.json"),"qwen36_27b":read(self.q/"config/qwen_config.json")}
        for model, field in [("gpt5mini","judge_configuration"),("qwen36_27b","generator_configuration")]:
            need(self.configs[model]==qp[field],f"{model} config changed")
        need(qp["generator_actual_model"]==MODELS["qwen36_27b"] and qp["judge_model"]==MODELS["gpt5mini"],"Unexpected original model IDs")
        self.prompt=(self.q/"prompts/examiner_generation.txt").read_text(encoding="utf-8")
        self.judge_prompt=(self.q/"prompts/generation_judge.txt").read_text(encoding="utf-8")
        for key, body in [("generation_prompt_hash",self.prompt),("judge_prompt_hash",self.judge_prompt)]:
            need(sha(body)==gp[key]==qp[key],f"Original {key} differs")
        self.tokenizer_info=read(self.q/"config/qwen_tokenizer.json")
        need(self.tokenizer_info==qp["tokenizer"],"Original tokenizer metadata changed")
        sys.path[:0]=[str(self.q/"code/legacy"),str(self.q/"code")]
        import common, run_experiments, qwen_c_runner, score_generation
        self.common,self.base,self.qrunner,self.scoring=common,run_experiments,qwen_c_runner,score_generation
        self.rows={s:uniq(common.read_jsonl(self.q/"inputs"/f"generation_{s}.jsonl")) for s in ("dev","core")}
        self.gold=uniq(common.read_jsonl(self.q/"gold/generation_targets.jsonl"))
        need(len(self.rows["core"])==50 and set(self.rows["dev"])==DEV_IDS and not (DEV_IDS & self.rows["core"].keys()),"Fixed gen_core50/dev3 split differs")
        self.baselines={}
        baseline_hashes={"gpt5mini":"bc687112643a1c01c6f1881fc60b97b67cd3a6b85fb078f844b06adf0c6db7f0",
                         "qwen36_27b":"d27b80bc50f15e8c160eac699da6552b56b87bf04c732bd33e55ee876048c5fd"}
        for model, path in {
            "gpt5mini":self.g/"metrics/generation_scores_core_state_with_history.csv",
            "qwen36_27b":self.q/"metrics/C/qwen_generation_scores_core.csv"
        }.items():
            verify(path,baseline_hashes[model])
            self.baselines[model]=uniq(csvrows(path))
            need(set(self.baselines[model])==self.rows["core"].keys(),f"{model} baseline cohort differs")
        for split, rows in self.rows.items():
            for sid, row in rows.items():
                ref=self.gold[sid]
                need(row["state"] is not None and sid==f"{row['app_id']}_t1","Missing frozen state or ID mismatch")
                need(all(d["date"]<=row["cutoff"] and d["doc_id"]!=ref["target_doc_id"] for d in row["documents"]),f"Cutoff/O2 check failed {sid}")
                need(ref["target_date"]>row["cutoff"],f"Unexpected target date {sid}")
                if split=="core":
                    for b in self.baselines.values():
                        need(b[sid]["input_hash"]==row["input_hash"] and b[sid]["target_doc_id"]==ref["target_doc_id"],f"Baseline mismatch {sid}")
                    need(self.baselines["gpt5mini"][sid]["model_input_hash"]==sha(self.base.generation_user(row)),f"GPT baseline request mismatch {sid}")
                    for v in SETTINGS.values():
                        p=self.profiles[(str(row["app_id"]),v)]
                        need(p["cutoff"]==row["cutoff"] and p["prediction_sample_id"]==sid,f"Core profile mapping mismatch {sid}/{v}")
                else:
                    need(all((str(row["app_id"]),v) not in self.profiles for v in SETTINGS.values()), "Dev unexpected overlap with released profiles")
        self.out.mkdir(parents=True,exist_ok=True)

    def request(self, row, split, setting):
        variant=SETTINGS[setting]
        if split=="core":
            key=(str(row["app_id"]),variant)
            p=self.profiles[key]; r=self.profile_rows[key]
            block=p["profile_text"]
            meta={k:r[k] for k in ("profile_sha1","profile_text_sha1","card_sha1")}
            meta.update(retrieved_k=p["retrieved_k"],profile_mode=p["profile_mode"],profile_release_id=RELEASE_ID,
                        profile_manifest_sha256=self.version["profile_manifest_sha256"], profile_variant=variant)
        else:
            # Same shape, explicit placeholders only; never borrow a test profile.
            i=sorted(DEV_IDS).index(row["sample_id"])
            k=(3,0,1)[i]
            group=f"synthetic fixture {i+1} / {variant}"
            examples="\n".join(f"Example {j+1}: synthetic reply followed by a synthetic communication; no real source." for j in range(k))
            block=(f"[DEV FORMAT ONLY: {group}; NOT REAL EXAMINER HISTORY]\n"
                   f"Examiner history reference available before {row['cutoff']}\n\n"
                   "Historical statistics\nObserved 2 of 5 fictional replies; 3 still waiting. Figures are placeholders.\n\n"
                   f"Retrieved historical episodes\n{examples or 'No retrieved examples (statistics-only fixture).'}\n\n"
                   "Do not treat these placeholders as facts or cite them. Follow the original output schema.")
            meta={"profile_sha1":None,"profile_text_sha1":sha(block,"sha1"),"card_sha1":None,
                  "retrieved_k":k,"profile_mode":"synthetic_dev_format_only","profile_release_id":None,"profile_variant":variant}
        user=self.base.generation_user(row)+"\n\n"+block
        return user,meta

    def judge_user(self,row,result):
        ref=self.gold[row["sample_id"]]
        return self.common.canonical({"sample_id":row["sample_id"],"cutoff":row["cutoff"],"record":row["documents"],
            "predicted_A1_state":row["state"],"candidate":result["parsed"],"mechanical_citation_audit":result["citation_audit"],
            "actual_O2":{"doc_id":ref["target_doc_id"],"code":ref["target_code"],"date":ref["target_date"],"text":ref["target_text"]}})

    def preflight(self, model, count_tokens=False):
        cfgs=json.loads(json.dumps(self.configs))
        # Credentials stay in the process environment. Endpoint overrides do not change model settings.
        envs={"gpt5mini":("AZURE_OPENAI_ENDPOINT","AZURE_OPENAI_DEPLOYMENT"),"qwen36_27b":("QWEN_AZURE_ENDPOINT","QWEN_AZURE_DEPLOYMENT")}
        active={"gpt5mini",model}
        cfgs={m:c for m,c in cfgs.items() if m in active}
        for m,(ep,dep) in envs.items():
            if m not in active: continue
            c=cfgs[m]
            c["base_url"]=self.common.normalize_endpoint(os.environ.get(ep,c["base_url"]))
            host=urlsplit(c["base_url"]).hostname
            need(host and host.endswith((".azure.com",".azure.net")),f"Use the Azure deployment HTTPS endpoint for {m}")
            c["deployment"]=os.environ.get(dep,c["deployment"])
        # GPT's adapter reads these two overrides itself, so preflight locks the same effective values.
        config_names={"gpt5mini":"azure_config","qwen36_27b":"qwen_config"}
        root=self.out/model
        signature={"repo_commit":COMMIT,"release_id":RELEASE_ID,"release_sha256":RELEASE_SHA,
            "profile_manifest_sha256":self.version["profile_manifest_sha256"],"source_sha256":self.source_hashes,
            "generation_prompt_hash":sha(self.prompt),"judge_prompt_hash":sha(self.judge_prompt),
            "overlay_sha256":sha(Path(__file__).read_bytes()),"configs":cfgs,"model":model,"dev_ids":sorted(DEV_IDS),
            "core_ids":list(self.rows["core"]),"coverage":self.coverage()}
        lock=root/"run_lock.json"
        if lock.exists(): need(read(lock)==signature,"Run inputs/settings changed; use the original version or a new output folder")
        else: self.common.write_json(lock,signature)
        for m in cfgs:
            self.common.write_json(root/"config"/(config_names[m]+".json"),cfgs[m])
        self.common.write_json(root/"config/frozen_protocol.json",{"generator_actual_model":MODELS["qwen36_27b"]})
        if count_tokens:
            if model=="qwen36_27b":
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer
                t=self.tokenizer_info
                p=Path(hf_hub_download(t["model"],"tokenizer.json",revision=t["revision"]))
                need(sha(p.read_bytes())==t["tokenizer_sha256"],"Qwen tokenizer hash mismatch")
                tok=Tokenizer.from_file(str(p))
                cnt=lambda p,u: len(tok.encode(p).ids)+len(tok.encode(u).ids)+512
                cap=cfgs[model]["context_window_tokens"]
            else:
                cnt=lambda p,u:self.common.count_tokens([{"content":p},{"content":u}])
                cap=cfgs[model]["context_window_tokens"]
            sizes=[cnt(self.prompt,self.request(row,s,setting)[0]) for s,rows in self.rows.items() for row in rows.values() for setting in SETTINGS]
            need(max(sizes)+16384+2048 < cap, "Context window reserve exceeded; do not crop history")
            self.common.write_json(root/"token_preflight.json",{"lock_sha256":sha(lock.read_bytes()),"max_generation_input_tokens_with_overhead":max(sizes),"context_window":cap,"reserved_output_tokens":16384,"requests_checked":len(sizes)})
        return root

    def coverage(self):
        return {s:dict(sorted(Counter(str(self.profiles[(str(r["app_id"]),v)]["retrieved_k"]) for r in self.rows["core"].values()).items()))
                for s,v in SETTINGS.items()}

    def output(self, root, model, split, setting, stage):
        return root/split/f"generation_{stage}_{model}_{setting}.jsonl"

    def records(self,path):
        return uniq(self.common.read_jsonl(path))

    def verify_result(self, r, row, split, setting, model):
        user,meta=self.request(row,split,setting)
        need(r["sample_id"]==row["sample_id"] and r["input_hash"]==row["input_hash"] and r["model_input_hash"]==sha(user)
             and r["prompt_hash"]==sha(self.prompt) and all(r.get(k)==v for k,v in meta.items())
             and r["split"]==split and r["setting"]==setting and r["generator"]==model,
             f"Stale or mismatched prediction: {row['sample_id']}/{model}/{setting}")
        if r["status"]=="success":
            need(r["model"]==MODELS[model] and not self.common.generation_validator(r["parsed"],row["sample_id"]), "Success record fails model/schema check")

    def verify_judge(self,j,r,row):
        need(j["candidate_request_hash"]==r["request_hash"] and j["profile_sha1"]==r["profile_sha1"] and j["profile_text_sha1"]==r["profile_text_sha1"]
             and j["input_hash"]==row["input_hash"] and j["model_input_hash"]==sha(self.judge_user(row,r))
             and j["prompt_hash"]==sha(self.judge_prompt),"Stale judge output")
        if j["status"]=="success":
            need(j["model"]==MODELS["gpt5mini"] and not self.common.judge_validator(j["parsed"],row["sample_id"]),"Invalid successful judge")

    def run(self, model, split, settings=None, only_judge=False, retry_failed=False):
        root=self.preflight(model)
        token=root/"token_preflight.json"
        need(token.exists() and read(token)["lock_sha256"]==sha((root/"run_lock.json").read_bytes()),"Run the tokenizer preflight first")
        if split=="core": self.gate(model,require=True)
        runner=self.qrunner.QwenRunner(root) if model=="qwen36_27b" else self.common.AzureRunner(root)
        if only_judge: runner=self.common.AzureRunner(root)
        for setting in settings or SETTINGS:
            if only_judge:
                self.run_judge(root,model,split,setting,runner,retry_failed)
                continue
            p=self.output(root,model,split,setting,"predictions")
            done=self.records(p)
            need(done.keys()<=self.rows[split].keys(),"Unexpected cases in output")
            for i,(sid,row) in enumerate(self.rows[split].items(),1):
                if sid in done:
                    self.verify_result(done[sid],row,split,setting,model)
                    if not (retry_failed and done[sid]["status"]=="api_failed"):
                        continue
                    self.common.append_jsonl(root/"retry_history.jsonl",done[sid])
                user,meta=self.request(row,split,setting)
                kwargs={"retry_api_failures":retry_failed} if model=="qwen36_27b" else {}
                r=runner.call(f"C_v4_{split}_{setting}",sid,self.prompt,user,row["input_hash"],self.common.generation_validator,**kwargs)
                if r["status"]=="success": r["citation_audit"]=self.base.citation_audit(r["parsed"],row)
                r.update(meta,split=split,setting=setting,generator=model,cutoff=row["cutoff"],
                         input_setting="state_with_history+profile")
                self.verify_result(r,row,split,setting,model)
                done[sid]=r
                self.common.write_jsonl(p,done.values())
                print(model,split,setting,f"{i}/{len(self.rows[split])}",sid,r["status"],flush=True)
                if split=="dev" and r["status"]!="success": raise ValueError(f"Dev format check failed: {sid}; inspect saved output")
            if split=="dev":
                self.run_judge(root,model,split,setting,self.common.AzureRunner(root),retry_failed)

    def run_judge(self,root,model,split,setting,runner,retry_failed=False):
        candidates=self.records(self.output(root,model,split,setting,"predictions"))
        need(candidates.keys()==self.rows[split].keys(),"Finish generation for this condition before judging")
        path=self.output(root,model,split,setting,"judges")
        done=self.records(path)
        for sid,row in self.rows[split].items():
            r=candidates[sid]
            self.verify_result(r,row,split,setting,model)
            if r["status"]!="success": continue
            if sid in done:
                self.verify_judge(done[sid],r,row)
            retry=sid in done and retry_failed and done[sid]["status"]=="api_failed"
            if retry: self.common.append_jsonl(root/"retry_history.jsonl",done[sid])
            if sid not in done or retry:
                j=runner.call(f"C_v4_judge_{model}_{split}_{setting}",sid,self.judge_prompt,self.judge_user(row,r),row["input_hash"],self.common.judge_validator)
                j.update(candidate_request_hash=r["request_hash"],profile_sha1=r["profile_sha1"],profile_text_sha1=r["profile_text_sha1"])
                self.verify_judge(j,r,row)
                done[sid]=j
                self.common.write_jsonl(path,done.values())
                print(model,split,setting,"judge",sid,j["status"],flush=True)
            if split=="dev": break

    def gate(self,model,require=False):
        root=self.preflight(model)
        proof={"model":model,"run_lock_sha256":sha((root/"run_lock.json").read_bytes()),"checks":{}}
        for s in SETTINGS:
            pred=self.records(self.output(root,model,"dev",s,"predictions"))
            judges=self.records(self.output(root,model,"dev",s,"judges"))
            need(set(pred)==DEV_IDS and all(r["status"]=="success" for r in pred.values()),f"{model}/{s}: all three dev generations must pass")
            for sid,r in pred.items(): self.verify_result(r,self.rows["dev"][sid],"dev",s,model)
            need(len(judges)==1 and all(sid in pred and j["status"]=="success" for sid,j in judges.items()),f"{model}/{s}: one valid dev judge required")
            for sid,j in judges.items(): self.verify_judge(j,pred[sid],self.rows["dev"][sid])
            proof["checks"][s]={"dev_cases":sorted(pred),"judge_cases":sorted(judges),
                "prediction_sha256":sha(self.output(root,model,"dev",s,"predictions").read_bytes()),
                "judge_sha256":sha(self.output(root,model,"dev",s,"judges").read_bytes())}
        f=root/"DEV_GATE.json"
        if require: need(f.exists() and read(f)==proof,"Inspect dev outputs, then run approve-dev before core")
        else: self.common.write_json(f,proof)
        return proof

    def score(self, model):
        root=self.preflight(model)
        self.gate(model,require=True)
        basekeys=("rougeL_full","meteor_full","judge_overall") if model=="gpt5mini" else ("qwen_rougeL","qwen_meteor","qwen_judge")
        vals={"noprof":{k:{} for k in METRICS}}
        for sid,r in self.baselines[model].items():
            for k,col in zip(METRICS,basekeys):
                if r[col]!="": vals["noprof"][k][sid]=float(r[col])
        allrows=[]; coverage={}; failures={}; submissions=[]; actions={}
        for s in SETTINGS:
            p=self.records(self.output(root,model,"core",s,"predictions"))
            j=self.records(self.output(root,model,"core",s,"judges"))
            need(p.keys()==self.rows["core"].keys(),f"Incomplete core generation {s}")
            need(j.keys()=={i for i,r in p.items() if r["status"]=="success"},f"Incomplete judge outputs {s}")
            vals[s]={k:{} for k in METRICS}; coverage[s]=dict(Counter(r["status"] for r in p.values()))
            actions[s]={}
            failures[s]={k:Counter() for k in METRICS}
            for sid,row in self.rows["core"].items():
                r=p[sid]; self.verify_result(r,row,"core",s,model)
                record={"sample_id":sid,"condition":s,"status":r["status"],"retrieved_k":r["retrieved_k"],
                        "profile_sha1":r["profile_sha1"],"input_hash":r["input_hash"],"model_input_hash":r["model_input_hash"]}
                if r["status"]=="success":
                    ref=self.gold[sid]["target_text"]; candidate=r["parsed"]["office_action"]
                    record["next_action_type"]=r["parsed"]["next_action_type"]
                    actions[s][sid]=record["next_action_type"]
                    for k,fn in [("R-L",self.scoring.rouge_l),("MET.",self.scoring.meteor)]:
                        record[k]=vals[s][k][sid]=fn(ref,candidate)
                    self.verify_judge(j[sid],r,row)
                    record["judge_status"]=j[sid]["status"]
                    if j[sid]["status"]=="success": record["Judge"]=vals[s]["Judge"][sid]=j[sid]["parsed"]["overall"]
                    else: failures[s]["Judge"][j[sid]["status"]]+=1
                else:
                    for k in METRICS: failures[s][k][r["status"]]+=1
                allrows.append(record)
        summary={s:{k:{"mean":statistics.mean(v.values()) if v else None,"scored_n":len(v),
                           "eligible_n":50,"failed_n":50-len(v)} for k,v in z.items()} for s,z in vals.items()}
        comparisons={}
        for a,b in [("prof","noprof"),("mismatch","noprof"),("prof","mismatch")]:
            comparisons[f"{a}_minus_{b}"]={k:paired(vals[a][k],vals[b][k]) for k in METRICS}
        common_k3={sid for sid,row in self.rows["core"].items()
                   if all(self.profiles[(str(row["app_id"]),v)]["retrieved_k"]==3 for v in SETTINGS.values())}
        sensitivity={k:paired({i:v for i,v in vals["prof"][k].items() if i in common_k3},
                              {i:v for i,v in vals["mismatch"][k].items() if i in common_k3}) for k in METRICS}
        for s in ("prof",):
            for k,m in summary[s].items():
                submissions.append(dict(owner="C",table3_column=k,model=LABELS[model],input_setting="state_with_history+profile",sample_set="gen_core",
                    value=m["mean"],eligible_n=50,scored_n=m["scored_n"],failed_n=m["failed_n"],excluded_reason=json.dumps(failures[s][k]),
                    split_detail="fixed 50 gen_core; A1 cutoff; reviewed v4",prompt_version=f"generation:{sha(self.prompt)}; judge:{sha(self.judge_prompt)}",
                    run_id=f"C_v4_{model}_{s}",source_file=f"{model}/comparison.json",notes=f"{s}; judge GPT-5-mini; actual retrieved_k retained"))
        self.scoring.write_csv(root/"case_scores.csv",allrows)
        self.prior()
        prior_rows=self.records(self.out/"generation_predictions_statistics_prior.jsonl")
        diagnostic={}
        for s,pred in actions.items():
            ids=sorted(i for i in pred if prior_rows[i]["next_action_type"])
            correct=lambda i, label: int(label==prior_rows[i]["gold_action_type"])
            diagnostic[s]=paired({i:correct(i,pred[i]) for i in ids},
                                 {i:correct(i,prior_rows[i]["next_action_type"]) for i in ids})
        report={"release":RELEASE_ID,"model":model,"summary":summary,"paired":comparisons,"generation_status":coverage,
                "retrieved_k":self.coverage(),"bootstrap":{"n":1000,"seed":20261010,"unit":"case","interval":"95% percentile"},
                "supplemental_action_accuracy_delta_vs_statistics_prior":diagnostic,
                "supplemental_prof_minus_mismatch_common_k3":{"eligible_n":len(common_k3),"paired":sensitivity},
                "notes":"Own-profile primary; complete pairs per contrast/metric; model-specific reused baseline. No dev results in metrics."}
        self.common.write_json(root/"comparison.json",report)
        return submissions

    def prior(self):
        # Supplemental next-action diagnostic only: a numeric prior cannot produce an Office Action.
        mapping={"allowance":"NOA","final_rejection":"CTFR","nonfinal_rejection":"CTNF","other":"other"}
        rows=[]
        for sid,row in self.rows["core"].items():
            key=str(row["app_id"]),"own"
            p=self.profiles[key]; stat=p["statistics"]["next_letter"]
            counts={k:0 for k in ("CTNF","CTFR","NOA","other")}
            for k,n in stat["type_counts"].items(): counts[mapping.get(k,"other")]+=n
            need(sum(counts.values())==stat["n_observed"],f"Unexpected observed-count denominator {sid}")
            top=max(counts.values()); winners=[k for k,v in counts.items() if v==top]
            guess=winners[0] if top and len(winners)==1 else None
            gold=self.gold[sid]["target_code"]; gold=gold if gold in ("CTNF","CTFR","NOA") else "other"
            rows.append({"sample_id":sid,"profile_sha1":self.profile_rows[key]["profile_sha1"],"n_observed":stat["n_observed"],
                         "status":"predicted" if guess else "abstain_empty_or_tie","next_action_type":guess,"gold_action_type":gold})
        got=[r for r in rows if r["next_action_type"]]
        self.common.write_jsonl(self.out/"generation_predictions_statistics_prior.jsonl",rows)
        report={"task":"supplemental next-action type only","release":RELEASE_ID,"eligible_n":50,"predicted_n":len(got),
                "accuracy_on_predicted":sum(r["next_action_type"]==r["gold_action_type"] for r in got)/len(got) if got else None,
                "office_action_text_metrics":"not applicable"}
        self.common.write_json(self.out/"statistics_prior_diagnostic.json",report)
        return report


def paired(x,y):
    ids=sorted(x.keys() & y.keys())
    ds=[x[i]-y[i] for i in ids]
    rng=random.Random(20261010)
    sims=sorted(statistics.mean(rng.choices(ds,k=len(ds))) for _ in range(1000)) if ds else []
    def quantile(p):
        pos=p*(len(sims)-1); lo=math.floor(pos); hi=math.ceil(pos)
        return sims[lo]+(sims[hi]-sims[lo])*(pos-lo)
    return {"paired_n":len(ids),"paired_sample_ids":ids,"delta":statistics.mean(ds) if ds else None,
            "ci95":[quantile(.025),quantile(.975)] if sims else None}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("stage",choices=["offline","preflight","dev","approve-dev","core","judge","score"])
    p.add_argument("--repo",required=True);p.add_argument("--release",required=True);p.add_argument("--out",required=True)
    p.add_argument("--model",choices=[*MODELS,"both"],default="both")
    p.add_argument("--retry-api-failures",action="store_true",help="Retry transport failures only; preserve previous records")
    a=p.parse_args()
    e=Experiment(a.repo,a.release,a.out)
    models=MODELS if a.model=="both" else [a.model]
    if a.stage=="offline":
        print(json.dumps({"core":len(e.rows["core"]),"dev":len(e.rows["dev"]),"coverage":e.coverage(),"prior":e.prior()},indent=2))
        return
    submissions=[]
    for m in models:
        if a.stage=="preflight":
            root=e.preflight(m,count_tokens=True);print(read(root/"token_preflight.json"))
        elif a.stage=="dev": e.run(m,"dev",retry_failed=a.retry_api_failures)
        elif a.stage=="approve-dev": print(e.gate(m))
        elif a.stage=="core": e.run(m,"core",retry_failed=a.retry_api_failures)
        elif a.stage=="judge": e.run(m,"core",only_judge=True,retry_failed=a.retry_api_failures)
        elif a.stage=="score": submissions+=e.score(m)
    if submissions:
        name="C_metrics.csv" if a.model=="both" else f"C_metrics_{a.model}.csv"
        e.scoring.write_csv(e.out/"submissions"/name,submissions,e.scoring.TEMPLATE_COLUMNS)


if __name__=="__main__":
    main()
