"""Run a sealed, private GPT input package. No retrieval, labels or scoring here."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent/'code'))
import b_prediction as bp
from b_run_paced import paced_transport

HEADER='\n\nEXAMINER PROFILE (past, other families):\n'
PROMPT='prompts/examiner_prediction.FROZEN.txt'


def require(ok, message):
    if not ok:raise ValueError(message)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configuration(root):
    c=json.loads((root/'frozen_setting.json').read_text())['config']
    return {**{k:c[k] for k in ('endpoint','deployment','expected_model','deployment_type')},
            'task':'prediction','reasoning_effort':'low','initial_max_completion_tokens':8192,
            'retry_max_completion_tokens':16384,'content_attempt_limit':2,'temperature':'omitted',
            'transport_retries':0,'response_format':{'type':'json_object'},
            'implementation_hash':file_hash(root/'code/b_prediction.py')}


def check(root):
    root=Path(root).resolve()
    manifest=json.loads((root/'PACKAGE_MANIFEST.json').read_text())
    require(manifest.get('private_team_only') is True,'Not a private input package')
    seen=set()
    for entry in manifest['files']:
        rel=entry['path']; p=bp.safe_path(root,rel)
        require(rel not in seen and not p.is_symlink() and p.is_file(),'Duplicate/missing package file')
        seen.add(rel)
        require(file_hash(p)==entry['sha256'],'Package hash mismatch: '+rel)
    required={'run_gpt.py','code/b_prediction.py','code/b_run_paced.py',PROMPT,'protocol.json',
              'frozen_setting.json','inputs/own.jsonl','inputs/mismatched.jsonl','inputs/dev.jsonl'}
    require(required<=seen,'Package manifest misses required files')
    require(file_hash(root/'run_gpt.py')==file_hash(__file__),'Run the packaged runner; code hash differs')
    require(file_hash(root/'code/b_prediction.py')==file_hash(bp.__file__),'Loaded adapter hash differs')
    protocol=json.loads((root/'protocol.json').read_text())
    cfg=configuration(root)
    require(cfg==protocol['configuration'],'Frozen GPT configuration mismatch')
    require(cfg['expected_model']=='gpt-5-mini-2025-08-07' and cfg['deployment_type']=='Global Standard',
            'Unexpected GPT version/deployment type')
    require(protocol['baseline_reuse_verified_by_B'] is True,'B baseline verification missing')
    data={v:bp.read_jsonl(root/'inputs'/f'{v}.jsonl') for v in ('own','mismatched','dev')}
    indices={v:bp.index(rows) for v,rows in data.items()}
    for v,rows in data.items():
        require(len(rows)==protocol['dev_n' if v=='dev' else 'core_n'],'Input count mismatch: '+v)
        for r in rows:
            require(r['input_setting']==('dev_format_only' if v=='dev' else v),'Condition mismatch')
            require(HEADER in r['user_message'],'Missing profile header')
            base,text=r['user_message'].rsplit(HEADER,1)
            require(hashlib.sha256(base.encode()).hexdigest()==r['base_user_message_hash'],'Base hash mismatch')
            require(hashlib.sha256(text.encode()).hexdigest()==r['profile_hash'],'Profile hash mismatch')
            require(hashlib.sha1(text.encode()).hexdigest()==r['profile_provenance']['profile_text_sha1'],
                    'Profile SHA1 mismatch')
            if v!='dev':
                require(r['profile_provenance']['release_id']==protocol['release_id'],'Profile release mismatch')
    require(list(indices['own'])==list(indices['mismatched']),'Core IDs/order mismatch')
    require(not(set(indices['dev'])&set(indices['own'])),'Dev/core overlap')
    for s,a in indices['own'].items():
        b=indices['mismatched'][s]
        for k in ('app_id','cutoff','input_hash','state_hash','state_input_hash','state_prompt_hash',
                  'missing_doc_ids','base_user_message_hash'):
            require(a[k]==b[k],'Paired base/state mismatch: '+s+'/'+k)
    return {'package_id':protocol['package_id'],'core_n':protocol['core_n'],'dev_n':protocol['dev_n'],
            'manifest_sha256':file_hash(root/'PACKAGE_MANIFEST.json'),'checks_passed':True}


def provenance(root, rows):
    cfg=configuration(root); prompt=(root/PROMPT).read_text()
    return [{'sample_id':r['sample_id'],'input_setting':r['input_setting'],
             'request_hash':bp.digest({'messages':[{'role':'system','content':prompt},
                 {'role':'user','content':r['user_message']}],'config':cfg,
                 'provenance':{k:v for k,v in r.items() if k!='user_message'}}),
             'profile_provenance':r['profile_provenance'],'profile_hash':r['profile_hash'],
             'base_user_message_hash':r['base_user_message_hash'],'state_hash':r['state_hash'],
             'package_manifest_sha256':file_hash(root/'PACKAGE_MANIFEST.json')}
            for r in rows]


def verify_results(root, stage, complete=True):
    out=root/'runs/gpt'/stage
    rows=bp.read_jsonl(out/'examiner_prediction.jsonl'); ii=bp.index(rows)
    source=bp.read_jsonl(root/'inputs'/f'{stage}.jsonl')
    pi=bp.index(provenance(root,source)); cfg=configuration(root)
    require(set(ii)<=set(pi) and (not complete or set(ii)==set(pi)),
            'Output sample IDs mismatch: '+stage)
    for s,r in ii.items():
        require(r['request_hash']==pi[s]['request_hash'] and r['configuration']==cfg,
                'Output request/config mismatch: '+s)
        require(r['prompt_hash']==file_hash(root/PROMPT),'Output prompt mismatch: '+s)
        if r['status']=='success':
            require(r['model']==cfg['expected_model'] and r['finish_reason']=='stop','Output model/finish mismatch')
            bp.validate_prediction(r['prediction'])
    return rows


def offline(root):
    root=Path(root).resolve(); report=check(root); counts={}
    source=bp.read_jsonl(root/'inputs/dev.jsonl'); samples={r['user_message']:i for i,r in enumerate(source)}
    prediction={'p_second_oa':.7,'p_type':{'CTNF':.2,'CTFR':.5,'NOA':.3},
                'predicted_type':'CTFR','claim_ground_pairs':[[343,'103'],[344,'112b']]}
    def send(payload):
        i=samples[payload['messages'][1]['content']];counts[i]=counts.get(i,0)+1
        finish='length' if i==1 and counts[i]==1 else 'stop'
        content='{"p_second_oa":2}' if i==2 else json.dumps(prediction)
        return {'model':configuration(root)['expected_model'],'choices':[{'finish_reason':finish,
                'message':{'content':content}}],'usage':{'total_tokens':0,'simulated':True}}
    config=json.loads((root/'frozen_setting.json').read_text())['config']
    with tempfile.TemporaryDirectory(prefix='gpt_handoff_offline_') as d:
        bp.run(root/'inputs/dev.jsonl',root/PROMPT,d,config,transport=send)
        rows=bp.read_jsonl(Path(d)/'examiner_prediction.jsonl')
        require([r['status'] for r in rows]==['success','success','failed'],'Offline retry/schema check failed')
        require(rows[1]['max_completion_tokens']==16384,'Offline truncation retry failed')
        before=sum(counts.values());bp.run(root/'inputs/dev.jsonl',root/PROMPT,d,config,transport=send)
        require(sum(counts.values())-before==2,'Offline successful cache reuse failed')
    report.update(api_calls=0,simulated=True,live_dev_passed=False)
    bp.atomic_json(root/'checks/offline.json',report)
    return report


@contextlib.contextmanager
def exclusive(root):
    p=root/'runs/gpt/.runner.lock';p.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise ValueError('Another GPT runner may be active; inspect .runner.lock before restarting') from None
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally:p.unlink(missing_ok=True)


def execute(root, stage, transport=None, interval=65):
    root=Path(root).resolve();report=check(root)
    require(stage in ('dev','core'),'Unknown stage')
    gatepath=root/'runs/gpt/dev/live_gate.json'
    if stage=='core':
        require(gatepath.exists(),'Run real dev successfully before core')
        gate=json.loads(gatepath.read_text())
        require(gate['manifest_sha256']==report['manifest_sha256'],'dev gate package mismatch')
        p=root/'runs/gpt/dev/examiner_prediction.jsonl'
        require(p.exists() and gate['dev_results_sha256']==file_hash(p),'dev result hash changed')
        rows=verify_results(root,'dev')
        require(len(rows)==report['dev_n'] and all(r['status']=='success' for r in rows),'dev incomplete')
    cfg=json.loads((root/'frozen_setting.json').read_text())['config']
    if transport is None:
        require(bool(os.environ.get('AZURE_OPENAI_API_KEY')),'Set AZURE_OPENAI_API_KEY in your terminal')
        transport=paced_transport(bp.azure_transport(cfg),interval)
    with exclusive(root):
        if stage=='dev':gatepath.unlink(missing_ok=True)
        result={}
        for v in (('dev',) if stage=='dev' else ('own','mismatched')):
            out=root/'runs/gpt'/v; source=bp.read_jsonl(root/'inputs'/f'{v}.jsonl')
            expected=provenance(root,source)
            # Refuse stale successful outputs even when a cache file is absent.
            if (out/'examiner_prediction.jsonl').exists():
                previous=verify_results(root,v,complete=False)
                for row in previous:
                    if row['status']=='success':
                        cache=out/'cache'/(row['request_hash']+'.json')
                        if not cache.exists():bp.atomic_json(cache,row)
            bp.jsonl(out/'request_provenance.jsonl',expected)
            result[v]=bp.run(root/'inputs'/f'{v}.jsonl',root/PROMPT,out,cfg,transport=transport)
            rows=verify_results(root,v);pi=bp.index(expected)
            bp.jsonl(out/'examiner_prediction.with_provenance.jsonl',[
                {**r,'profile_provenance':pi[r['sample_id']]['profile_provenance'],
                 'package_manifest_sha256':report['manifest_sha256']} for r in rows])
        if stage=='dev' and result['dev']['success_n']==report['dev_n']:
            bp.atomic_json(gatepath,{**report,'dev_results_sha256':file_hash(root/'runs/gpt/dev/examiner_prediction.jsonl'),
                                   'run_id':result['dev']['run_id'],'scored':False})
        return result


def export_results(root):
    root=Path(root).resolve();report=check(root)
    result_status={}
    for v in ('own','mismatched'):
        p=root/'runs/gpt'/v/'examiner_prediction.jsonl'
        rows=verify_results(root,v,complete=False) if p.exists() else []
        result_status[v]={'success_n':sum(r['status']=='success' for r in rows),
                          'failed_or_missing_n':report['core_n']-sum(r['status']=='success' for r in rows)}
    manifest=json.loads((root/'PACKAGE_MANIFEST.json').read_text())
    files=[root/e['path'] for e in manifest['files']]+[root/'PACKAGE_MANIFEST.json']
    files+=sorted(p for folder in (root/'runs',root/'checks') if folder.exists()
                  for p in folder.rglob('*') if p.is_file() and p.name!='.runner.lock')
    require(not(root/'runs/gpt/.runner.lock').exists(),'Runner active; export after it stops')
    require(all(not p.is_symlink() for p in files),'Symlink in export')
    result={**report,'conditions':result_status,
            'core_complete':all(v['success_n']==report['core_n'] for v in result_status.values()),
            'private_team_only':True,'files':[{'path':str(p.relative_to(root)),'sha256':file_hash(p)} for p in files]}
    stamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=root.parent/(root.name+'_RETURN_'+stamp+'.zip')
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,root.name+'/'+str(p.relative_to(root)))
        z.writestr(root.name+'/RETURN_MANIFEST.json',json.dumps(result,ensure_ascii=False,indent=2))
    return target


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('check','dev','core','export'))
    p.add_argument('--package',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--interval',type=float,default=65)
    a=p.parse_args()
    try:
        if a.command=='check':r=offline(a.package)
        elif a.command=='export':r={'return_zip':str(export_results(a.package))}
        else:
            r=execute(a.package,a.command,interval=a.interval)
            print(json.dumps(r,indent=2));return 0 if all(v['failed_n']==0 for v in r.values()) else 2
        print(json.dumps(r,indent=2));return 0
    except (ValueError,FileNotFoundError,KeyError,json.JSONDecodeError) as exc:
        # No credentials or arbitrary API exception text printed by this wrapper.
        print('Stopped: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
