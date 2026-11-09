"""Separate Qwen3.6-27B adapter. Leaves GPT runner and existing cache intact."""
import argparse,hashlib,json,os,re,uuid
from datetime import datetime,timezone
from pathlib import Path
from b_prediction import read_jsonl,index,digest,canonical,atomic_json,jsonl,csvfile,validate_prediction,TYPES,azure_transport
from b_run_paced import paced_transport


def implementation_hash():
    return digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('b_prediction.py')]})


def matches_model(model,expected=None):
    if not isinstance(model,str) or not model:return False
    if expected:return model==expected
    return re.sub('[^a-z0-9]','',model.lower()) in {'qwen3627b','qwenqwen3627b'}


def parse_content(content):
    if not isinstance(content,str):raise ValueError('Final content absent')
    text=content.strip()
    if text.startswith('<think>'):
        end=text.find('</think>')
        if end<0:raise ValueError('Unclosed thinking block')
        text=text[end+len('</think>'):].strip()
    if text.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```',text)
        if not match:raise ValueError('Malformed final JSON fence')
        text=match[1]
    return json.loads(text)


def error_detail(exc):
    response=getattr(exc,'response',None)
    if response is None:return ''
    text=response.text
    for name in ('AZURE_OPENAI_API_KEY','QWEN_API_KEY'):
        key=os.environ.get(name)
        if key:text=text.replace(key,'[REDACTED]')
    return text[:1200]

def run_qwen(inputs, prompt, output, config, transport=None, validator=validate_prediction, task='prediction'):
    rows=read_jsonl(inputs);index(rows)
    output=Path(output);prompt_text=Path(prompt).read_text();prompt_hash=hashlib.sha256(prompt_text.encode()).hexdigest()
    if not config.get('endpoint') or not config.get('deployment'):
        raise ValueError('Azure endpoint/deployment are required')
    send=transport or azure_transport(config)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    config={'endpoint':config['endpoint'],'deployment':config['deployment'],
            'expected_model':config.get('expected_model'),'deployment_type':'not_verified_Qwen_Azure_deployment'}
    configuration={**config,'task':task,'reasoning_effort':'omitted_provider_default',
                   'thinking':'provider_default_not_claimed_equivalent_to_GPT_low',
                   'initial_max_tokens':8192,'retry_max_tokens':16384,'content_attempt_limit':2,
                   'temperature':'omitted_provider_default','transport_retries':0,'response_format':'omitted_JSON_prompt_only',
                   'state_provider':'fixed_previously_generated_GPT5mini_states',
                   'implementation_hash':implementation_hash()}
    results=[]
    for row in rows:
        messages=[{'role':'system','content':prompt_text},{'role':'user','content':row['user_message']}]
        request_hash=digest({'messages':messages,'config':configuration,'provenance':{k:v for k,v in row.items() if k!='user_message'}})
        cache=output/'cache'/(request_hash+'.json')
        if cache.is_file():
            cached=json.loads(cache.read_text())
            if cached.get('request_hash')==request_hash and cached.get('status')=='success' and matches_model(cached.get('model'),config['expected_model']):
                validator(cached['prediction']);results.append(cached)
                print(f"[{len(results)}/{len(rows)}] {row['sample_id']} cached", flush=True)
                continue
        base={k:row.get(k) for k in ('sample_id','app_id','cutoff','input_hash','state_input_hash','state_hash','state_prompt_hash','missing_doc_ids')}
        base['base_user_message_hash']=row.get('base_user_message_hash') or hashlib.sha256(row['user_message'].encode()).hexdigest()
        base['input_setting']=row.get('input_setting','no_profile')
        base['profile_hash']=row.get('profile_hash')
        base.update(run_id=run_id,prompt_hash=prompt_hash,request_hash=request_hash,configuration=configuration)
        budget=8192;final=None
        for attempt in (1,2):
            payload={'model':config['deployment'],'messages':messages,'max_tokens':budget}
            meta={**base,'attempt':attempt,'max_tokens':budget}
            try:
                response=send(payload)
            except Exception as exc:
                code=getattr(getattr(exc,'response',None),'status_code',None)
                meta.update(status='failed',reason='api_error',exception_type=type(exc).__name__,http_status=code,api_error_detail=error_detail(exc))
                atomic_json(output/'raw'/f'{request_hash}_{run_id}_{attempt}.json',meta)
                log_path=output/'usage_log.jsonl';log_path.parent.mkdir(parents=True,exist_ok=True)
                with log_path.open('a') as stream:stream.write(canonical(meta)+'\n')
                final={**meta,'prediction':None};break
            meta['response']=response
            try:
                if not isinstance(response,dict):
                    raise ValueError('Malformed API envelope')
                meta.update(model=response.get('model'),usage=response.get('usage'))
                if not matches_model(meta['model'],config['expected_model']):
                    raise ValueError('unexpected_model_version')
                choice=response['choices'][0];finish=choice['finish_reason'];content=choice['message']['content']
                meta['finish_reason']=finish
                if finish=='length':
                    raise ValueError('truncated')
                if finish!='stop':
                    raise ValueError('non_stop_finish')
                parsed=validator(parse_content(content))
                meta.update(status='success',reason='')
                final={k:v for k,v in meta.items() if k!='response'}
                final['prediction']=parsed
            except (ValueError,KeyError,TypeError,IndexError):
                reason=('unexpected_model_version' if isinstance(response,dict) and not matches_model(response.get('model'),config['expected_model'])
                        else 'truncated' if meta.get('finish_reason')=='length' else 'invalid_json_or_schema_or_finish')
                meta.update(status='failed',reason=reason)
                final={k:v for k,v in meta.items() if k!='response'}
                final['prediction']=None
            atomic_json(output/'raw'/f'{request_hash}_{run_id}_{attempt}.json',meta)
            log={k:v for k,v in meta.items() if k!='response'}
            log_path=output/'usage_log.jsonl';log_path.parent.mkdir(parents=True,exist_ok=True)
            with log_path.open('a') as stream:stream.write(canonical(log)+'\n')
            if final['status']=='success':
                atomic_json(cache,final);break
            if final['reason']=='unexpected_model_version':
                break
            if attempt==1:
                budget=16384 if meta.get('finish_reason')=='length' else 8192
        results.append(final)
        print(f"[{len(results)}/{len(rows)}] {row['sample_id']} {final['status']} {final['reason']}", flush=True)
        jsonl(output/'examiner_prediction.jsonl',results)
    jsonl(output/'examiner_prediction.jsonl',results)
    csvfile(output/'examiner_prediction.csv',[
        {**{k:r.get(k) for k in ('sample_id','status','reason','input_hash','prompt_hash','request_hash','model')},
         'p_second_oa':(r.get('prediction') or {}).get('p_second_oa'),
         **{'p_'+t:(r.get('prediction') or {}).get('p_type',{}).get(t) for t in TYPES},
         'predicted_type':(r.get('prediction') or {}).get('predicted_type')} for r in results])
    jsonl(output/'claim_ground_predictions.jsonl',[
        {'sample_id':r['sample_id'],'status':r['status'],'claim_ground_pairs':(r.get('prediction') or {}).get('claim_ground_pairs'),
         'input_hash':r['input_hash'],'prompt_hash':r['prompt_hash'],'request_hash':r['request_hash']} for r in results])
    summary={'run_id':run_id,'eligible_n':len(rows),'success_n':sum(r['status']=='success' for r in results),
             'failed_n':sum(r['status']!='success' for r in results),'configuration':configuration}
    atomic_json(output/'run_summary.json',summary)
    return summary



def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_files(b):
    return {'dev':b/'prepared_dev/inputs/prediction_dev.jsonl',
            'core':b/'prepared/inputs/prediction_core.jsonl',
            'profile':b/'prepared/paired/with_profile.jsonl'}


def freeze_qwen(b):
    root=b/'outputs/qwen36_27b';rows=read_jsonl(root/'dev/examiner_prediction.jsonl')
    expected=set(index(read_jsonl(stage_files(b)['dev'])))
    assert len(rows)==3 and set(index(rows))==expected,'Three successful dev outputs required'
    assert all(r['status']=='success' for r in rows),'Development failures must be resolved first'
    models={r['model'] for r in rows};assert len(models)==1,'Returned model IDs differ'
    assert all(r['configuration']==rows[0]['configuration'] for r in rows),'Dev settings differ'
    prompt=b/'prompts/examiner_prediction.FROZEN.txt'
    ph=file_hash(prompt);assert all(r['prompt_hash']==ph for r in rows),'Prompt changed; rerun dev'
    assert all(r['configuration']['implementation_hash']==implementation_hash() for r in rows),'Adapter changed; rerun dev'
    gpt_freeze=json.loads((b/'frozen_setting.json').read_text())
    assert ph==gpt_freeze['prompt_hash'],'GPT prompt changed'
    assert file_hash(stage_files(b)['profile'])==gpt_freeze['paired_with_profile_sha256'],'GPT profile inputs changed'
    assert file_hash(b/'prepared/paired/examiner_profile_contexts.jsonl')==gpt_freeze['profile_contexts_sha256'],'GPT profile contexts changed'
    source_rows=index(read_jsonl(stage_files(b)['dev']))
    for r in rows:
        validate_prediction(r['prediction'])
        source=source_rows[r['sample_id']]
        request=digest({'messages':[{'role':'system','content':prompt.read_text()},{'role':'user','content':source['user_message']}],
                        'config':r['configuration'],'provenance':{k:v for k,v in source.items() if k!='user_message'}})
        assert r['request_hash']==request,'Development inputs changed; rerun dev'
    first=rows[0]['configuration']
    frozen={'setting_label':'Qwen36_27B_Azure_default_thinking_fixed_GPT_states',
            'config':{'endpoint':first['endpoint'],'deployment':first['deployment'],'expected_model':next(iter(models))},
            'prompt_hash':ph,'implementation_hash':implementation_hash(),
            'input_file_hashes':{name:file_hash(path) for name,path in stage_files(b).items()},
            'profile_contexts_sha256':file_hash(b/'prepared/paired/examiner_profile_contexts.jsonl'),
            'dev_review':'schema_probability_and_model_checked;no_prompt_tuning',
            'state_source':'GPT5mini_existing_fixed_states_not_Qwen_extracted',
            'configuration':first}
    atomic_json(root/'frozen_setting.json',frozen);return frozen


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=('dev','freeze','core','profile'),required=True)
    p.add_argument('--interval',type=float,default=65)
    p.add_argument('--endpoint',default=os.environ.get('QWEN_ENDPOINT','https://week1011.services.ai.azure.com/openai/v1/'))
    p.add_argument('--deployment',default=os.environ.get('QWEN_DEPLOYMENT','qwen--qwen36-27b'))
    a=p.parse_args();b=Path(__file__).resolve().parent;root=b/'outputs/qwen36_27b'
    if a.stage=='freeze':print(json.dumps(freeze_qwen(b),indent=2));return
    prompt=b/'prompts/examiner_prediction.FROZEN.txt';paths=stage_files(b)
    config={'endpoint':a.endpoint,'deployment':a.deployment}
    if a.stage!='dev':
        frozen=json.loads((root/'frozen_setting.json').read_text())
        assert config=={k:frozen['config'][k] for k in ('endpoint','deployment')},'Deployment/endpoint changed'
        assert file_hash(prompt)==frozen['prompt_hash'],'Frozen prompt changed'
        assert implementation_hash()==frozen['implementation_hash'],'Adapter changed after dev'
        assert all(file_hash(paths[k])==v for k,v in frozen['input_file_hashes'].items()),'Frozen inputs changed'
        assert file_hash(b/'prepared/paired/examiner_profile_contexts.jsonl')==frozen['profile_contexts_sha256'],'Profile context changed'
        config=frozen['config']
    else:
        assert file_hash(prompt)==json.loads((b/'frozen_setting.json').read_text())['prompt_hash'],'GPT frozen prompt mismatch'
    if os.environ.get('QWEN_API_KEY'):os.environ['AZURE_OPENAI_API_KEY']=os.environ['QWEN_API_KEY']
    out=root/a.stage
    atomic_json(out/'request_pacing.json',{'interval_seconds':a.interval,'api_retries_added':0})
    send=paced_transport(azure_transport(config),a.interval)
    print(json.dumps(run_qwen(paths[a.stage],prompt,out,config,transport=send),indent=2))

if __name__=='__main__':main()
