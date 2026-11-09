"""Concurrent Qwen phase-2 scheduling; immutable original adapter and requests.

Workers use private journals and the existing success cache. Only the coordinator
writes aggregate outputs. The original phase-2 module and dev gates stay valid.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import threading
import time
import uuid

import b_phase2_prediction as p


def configuration():
    return p.audit_baseline('qwen',p.bp.read_jsonl(p.CORE))['configuration']


def request_hash(row, config):
    return p.bp.digest({'messages':p.messages(row),'config':config,
                       'provenance':{k:v for k,v in row.items() if k!='user_message'}})


def successes(rows, output, config):
    """Fail closed on inconsistent successes instead of silently paying again."""
    output=Path(output); old={}
    path=output/'examiner_prediction.jsonl'
    if path.exists():old=p.bp.index(p.bp.read_jsonl(path))
    found={}
    for row in rows:
        sample=row['sample_id']; h=request_hash(row,config)
        cache=output/'cache'/f'{h}.json'; candidates=[]
        if cache.exists():candidates.append(json.loads(cache.read_text()))
        if old.get(sample,{}).get('status')=='success':candidates.append(old[sample])
        for value in candidates:
            p.require(value.get('status')=='success' and value.get('request_hash')==h
                      and value.get('model')==config['expected_model']
                      and value.get('configuration')==config
                      and value.get('finish_reason')=='stop', 'Invalid cached success: '+sample)
            p.bp.validate_prediction(value['prediction'])
        if candidates:
            p.require(all(c['prediction']==candidates[0]['prediction'] for c in candidates),
                      'Conflicting cached success: '+sample)
            found[sample]=candidates[0]
    return found


class SharedPacing:
    """Optional start spacing plus provider-wide Retry-After; no extra retries."""
    def __init__(self,send,interval):
        p.require(interval>=0,'interval must be nonnegative')
        self.send=send;self.interval=interval;self.next_at=0.;self.lock=threading.Lock()

    def __call__(self,payload):
        while True:
            with self.lock:
                delay=self.next_at-time.monotonic()
                if delay<=0:
                    self.next_at=time.monotonic()+self.interval
                    break
            time.sleep(min(delay,1.))
        try:
            return self.send(payload)
        except Exception as exc:
            response=getattr(exc,'response',None)
            if getattr(response,'status_code',None)==429:
                try:cooldown=float(response.headers.get('retry-after',65))
                except (ValueError,TypeError):cooldown=65
                with self.lock:self.next_at=max(self.next_at,time.monotonic()+max(0,cooldown))
            raise


def merge_usage(output):
    """Recover isolated worker attempts after interruption; append each only once."""
    target=output/'usage_log.jsonl'
    seen={p.bp.canonical(r) for r in p.bp.read_jsonl(target)} if target.exists() else set()
    with target.open('a') as stream:
        for path in sorted((output/'concurrent_workers').glob('*/usage_log.jsonl')):
            if not (path.parent/'run_summary.json').exists():
                continue  # Active worker journals may still be appending.
            for row in p.bp.read_jsonl(path):
                key=p.bp.canonical(row)
                if key not in seen:
                    stream.write(key+'\n');seen.add(key)


def checkpoint(rows, results, provenance, output):
    ordered=[results[r['sample_id']] for r in rows if r['sample_id'] in results]
    p.bp.jsonl(output/'examiner_prediction.jsonl',ordered)
    joined=[{**r,'profile_provenance':provenance[r['sample_id']]['profile_provenance'],
             'wrapper_sha256':p.fh(p.__file__),'scheduler_sha256':p.fh(__file__)} for r in ordered]
    p.bp.jsonl(output/'examiner_prediction.with_provenance.jsonl',joined)
    p.bp.jsonl(output/'claim_ground_predictions.jsonl',[
        {'sample_id':r['sample_id'],'status':r['status'],
         'claim_ground_pairs':(r.get('prediction') or {}).get('claim_ground_pairs'),
         'input_hash':r.get('input_hash'),'prompt_hash':r.get('prompt_hash'),'request_hash':r['request_hash']} for r in ordered])
    p.bp.csvfile(output/'examiner_prediction.csv',[
        {'sample_id':r['sample_id'],'status':r['status'],'reason':r.get('reason',''),
         'request_hash':r['request_hash'],'model':r.get('model'),
         'p_second_oa':(r.get('prediction') or {}).get('p_second_oa'),
         **{'p_'+t:(r.get('prediction') or {}).get('p_type',{}).get(t) for t in p.bp.TYPES},
         'predicted_type':(r.get('prediction') or {}).get('predicted_type')} for r in ordered])


def run_concurrent(inputs, output, workers=4, transport=None, interval=0):
    p.require(isinstance(workers,int) and workers>0,'workers must be positive')
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    with (output/'.concurrent.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another concurrent runner owns this condition')
        rows=p.bp.read_jsonl(inputs);p.bp.index(rows);config=configuration()
        results=successes(rows,output,config);reused=len(results)
        pending=[r for r in rows if r['sample_id'] not in results]
        provenance={r['sample_id']:{'sample_id':r['sample_id'],'request_hash':request_hash(r,config),
                    'profile_provenance':r['profile_provenance'],
                    'base_user_message_hash':r['base_user_message_hash'],'profile_hash':r['profile_hash'],
                    'wrapper_sha256':p.fh(p.__file__),'scheduler_sha256':p.fh(__file__),
                    'inputs_sha256':p.fh(inputs),'configuration':config} for r in rows}
        p.bp.jsonl(output/'request_provenance.jsonl',list(provenance.values()))
        p.bp.atomic_json(output/'concurrency.json',{'workers':workers,'interval_seconds':interval,
             'scheduler_sha256':p.fh(__file__),'original_adapter_hash':p.adapter_hash('qwen'),
             'request_configuration_unchanged':True,'reused_success_n':reused,
             'scheduled_n':len(pending),'transport_retries_added':0})
        if pending:
            frozen=json.loads(p.frozen_path('qwen').read_text())['config']
            if transport is None:
                previous=os.environ.get('AZURE_OPENAI_API_KEY')
                try:
                    if os.environ.get('QWEN_API_KEY'):
                        os.environ['AZURE_OPENAI_API_KEY']=os.environ['QWEN_API_KEY']
                    transport=p.bp.azure_transport(frozen)
                finally:
                    if previous is None:os.environ.pop('AZURE_OPENAI_API_KEY',None)
                    else:os.environ['AZURE_OPENAI_API_KEY']=previous
            send=SharedPacing(transport,interval)
            (output/'cache').mkdir(exist_ok=True);(output/'raw').mkdir(exist_ok=True)
            def work(row):
                h=request_hash(row,config)
                directory=output/'concurrent_workers'/(h+'_'+uuid.uuid4().hex[:12])
                directory.mkdir(parents=True)
                p.bp.jsonl(directory/'input.jsonl',[row])
                (directory/'cache').symlink_to((output/'cache').resolve(),target_is_directory=True)
                (directory/'raw').symlink_to((output/'raw').resolve(),target_is_directory=True)
                p.bq.run_qwen(directory/'input.jsonl',p.PROMPT,directory,frozen,transport=send)
                result=p.bp.read_jsonl(directory/'examiner_prediction.jsonl')[0]
                p.require(result['request_hash']==h and result['configuration']==config,'Worker request drift')
                return result
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures=[pool.submit(work,r) for r in pending]
                for future in as_completed(futures):
                    result=future.result();results[result['sample_id']]=result
                    merge_usage(output);checkpoint(rows,results,provenance,output)
        merge_usage(output);checkpoint(rows,results,provenance,output)
        summary={'eligible_n':len(rows),'success_n':sum(r['status']=='success' for r in results.values()),
                 'failed_n':sum(r['status']!='success' for r in results.values()),
                 'reused_success_n':reused,'scheduled_n':len(pending),'workers':workers,'configuration':config}
        p.bp.atomic_json(output/'run_summary.json',summary)
        return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--interval',type=float,default=0)
    parser.add_argument('--plan-only',action='store_true',help='Read-only cache inventory; no API calls')
    args=parser.parse_args();p.check_locks()
    p.require(args.workers>0 and args.interval>=0,'Invalid concurrency settings')
    # Original module is unchanged, so the already passed live dev gate remains valid.
    gate=json.loads((p.ROOT/'runs/qwen/dev/live_gate.json').read_text())
    p.require(gate['wrapper_sha256']==p.fh(p.__file__) and gate['dev_inputs_sha256']==p.fh(p.ROOT/'inputs/dev.jsonl')
              and gate['success_n']==3 and gate['prompt_sha256']==p.fh(p.PROMPT),'Live Qwen dev gate invalid')
    config=configuration(); summaries={}
    for variant in p.VARIANTS:
        inputs=p.ROOT/'inputs'/f'{variant}.jsonl';out=p.ROOT/'runs/qwen'/variant
        if args.plan_only:
            rows=p.bp.read_jsonl(inputs);cached=successes(rows,out,config)
            summaries[variant]={'total_n':len(rows),'reused_success_n':len(cached),
                                'pending_n':len(rows)-len(cached),'workers':args.workers,'api_calls':0}
        else:
            summaries[variant]=run_concurrent(inputs,out,args.workers,interval=args.interval)
    print(json.dumps(summaries,indent=2))

if __name__=='__main__':main()
