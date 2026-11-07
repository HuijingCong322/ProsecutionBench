import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'code'))
from b_qwen import parse_content,run_qwen

PRED={'p_second_oa':.7,'p_type':{'CTNF':.3,'CTFR':.4,'NOA':.3},'predicted_type':'CTFR','claim_ground_pairs':[[1,'103']]}

def files(tmp):
    p=tmp/'prompt';p.write_text('Return JSON');i=tmp/'inputs'
    i.write_text(json.dumps({'sample_id':'s','app_id':'1','input_hash':'shared','state_hash':'fixedGPT','cutoff':'2015-01-01','user_message':'Observed record'})+'\n')
    return i,p

def envelope(finish='stop',model='Qwen/Qwen3.6-27B'):
    return {'model':model,'choices':[{'finish_reason':finish,'message':{'content':'<think>private reasoning</think>\n'+json.dumps(PRED)}}],'usage':{'total_tokens':30}}

def test_final_json_is_separate_from_thinking():
    assert parse_content('<think>x</think>\n```json\n'+json.dumps(PRED)+'\n```')==PRED
    with pytest.raises(ValueError):parse_content('<think>unterminated '+json.dumps(PRED))
    with pytest.raises(ValueError):parse_content('random text '+json.dumps(PRED))

def test_payload_retry_cache_and_model_guard(tmp_path):
    i,p=files(tmp_path);calls=[]
    def send(payload):calls.append(payload);return envelope('length' if len(calls)==1 else 'stop')
    conf={'endpoint':'https://example.test/openai/v1/','deployment':'qwen--qwen36-27b','expected_model':'Qwen/Qwen3.6-27B'}
    out=tmp_path/'out';r=run_qwen(i,p,out,conf,transport=send)
    assert r['success_n']==1
    assert [x['max_tokens'] for x in calls]==[8192,16384]
    assert all('reasoning_effort' not in x and 'temperature' not in x and 'max_completion_tokens' not in x for x in calls)
    result=json.loads((out/'examiner_prediction.jsonl').read_text())
    assert result['model']=='Qwen/Qwen3.6-27B' and result['state_hash']=='fixedGPT'
    run_qwen(i,p,out,conf,transport=lambda x:pytest.fail('Successful cache not reused'))
    failed=run_qwen(i,p,tmp_path/'wrong',conf,transport=lambda x:envelope(model='gpt-5-mini'))
    assert failed['failed_n']==1


def test_freeze_rejects_changed_development_inputs(tmp_path):
    from b_qwen import freeze_qwen,file_hash
    b=tmp_path
    paths=[b/'prepared_dev/inputs/prediction_dev.jsonl',b/'prepared/inputs/prediction_core.jsonl',b/'prepared/paired/with_profile.jsonl']
    rows=[{'sample_id':str(i),'app_id':str(i),'cutoff':'2015-01-01','input_hash':'shared','state_hash':'GPT','user_message':'original'} for i in range(3)]
    for path in paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    prompt=b/'prompts/examiner_prediction.FROZEN.txt';prompt.parent.mkdir();prompt.write_text('Return JSON')
    (b/'prepared/paired/examiner_profile_contexts.jsonl').write_text('contexts')
    (b/'frozen_setting.json').write_text(json.dumps({'prompt_hash':file_hash(prompt),'paired_with_profile_sha256':file_hash(paths[2]),'profile_contexts_sha256':file_hash(b/'prepared/paired/examiner_profile_contexts.jsonl')}))
    config={'endpoint':'https://example.test/openai/v1/','deployment':'qwen--qwen36-27b'}
    run_qwen(paths[0],prompt,b/'outputs/qwen36_27b/dev',config,transport=lambda x:envelope())
    freeze=freeze_qwen(b)
    assert freeze['config']['expected_model']=='Qwen/Qwen3.6-27B'
    contexts=b/'prepared/paired/examiner_profile_contexts.jsonl'
    contexts.write_text('changed contexts')
    with pytest.raises(AssertionError,match='GPT profile contexts changed'):freeze_qwen(b)
    contexts.write_text('contexts')
    rows[0]['user_message']='changed'
    paths[0].write_text(''.join(json.dumps(r)+'\n' for r in rows))
    with pytest.raises(AssertionError,match='Development inputs changed'):freeze_qwen(b)


def test_error_redaction_happens_before_truncation(monkeypatch):
    import httpx
    from b_qwen import error_detail
    secret='synthetic_test_secret_123456789'
    monkeypatch.setenv('QWEN_API_KEY',secret)
    response=httpx.Response(400,text='x'*1190+secret,request=httpx.Request('POST','https://example.test'))
    exc=httpx.HTTPStatusError('bad',request=response.request,response=response)
    assert secret[:10] not in error_detail(exc)
