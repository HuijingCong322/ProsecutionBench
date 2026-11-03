import sys
import threading
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import b_phase2_prediction as p


def test_parallel_resume_preserves_requests_and_success_cache(tmp_path):
    import b_qwen_phase2_concurrent as c
    rows=p.dev_rows(); inputs=tmp_path/'inputs.jsonl';p.bp.jsonl(inputs,rows)
    config=__import__('json').loads(p.frozen_path('qwen').read_text())['config']
    out=tmp_path/'out'; calls=[]
    def good(payload):
        calls.append(payload)
        return {'model':config['expected_model'],'choices':[{'finish_reason':'stop','message':{'content':p.bp.canonical(p.fixture_prediction())}}],'usage':{'total_tokens':1}}
    first=tmp_path/'first.jsonl';p.bp.jsonl(first,rows[:1])
    p.bq.run_qwen(first,p.PROMPT,out,config,transport=good)
    cached=next((out/'cache').glob('*.json')); original=cached.read_bytes();calls.clear()
    barrier=threading.Barrier(2)
    def parallel(payload):
        barrier.wait(timeout=5)
        return good(payload)
    report=c.run_concurrent(inputs,out,workers=2,transport=parallel)
    assert report['reused_success_n']==1 and report['success_n']==3
    assert len(calls)==2 and cached.read_bytes()==original
    assert all(x['max_tokens']==8192 and set(x)=={'model','messages','max_tokens'} for x in calls)
    assert [r['sample_id'] for r in p.bp.read_jsonl(out/'examiner_prediction.jsonl')]==[r['sample_id'] for r in rows]
    for r in p.bp.read_jsonl(out/'examiner_prediction.jsonl'):
        assert r['request_hash']==c.request_hash(next(x for x in rows if x['sample_id']==r['sample_id']),r['configuration'])
    def forbidden(payload):raise AssertionError('successful sample was called again')
    again=c.run_concurrent(inputs,out,workers=4,transport=forbidden)
    assert again['reused_success_n']==3 and again['scheduled_n']==0
    assert len(p.bp.read_jsonl(out/'usage_log.jsonl'))==3


def test_summary_success_without_cache_is_reused(tmp_path):
    import b_qwen_phase2_concurrent as c
    rows=p.dev_rows()[:1]; inputs=tmp_path/'in.jsonl';p.bp.jsonl(inputs,rows)
    out=tmp_path/'out'
    config=c.configuration()
    row={**rows[0],'status':'success','finish_reason':'stop','model':config['expected_model'],
         'configuration':config,'prediction':p.fixture_prediction(),'request_hash':c.request_hash(rows[0],config)}
    p.bp.jsonl(out/'examiner_prediction.jsonl',[row])
    def forbidden(payload):raise AssertionError('successful sample was called again')
    assert c.run_concurrent(inputs,out,workers=2,transport=forbidden)['scheduled_n']==0


def test_invalid_cached_success_stops_before_any_call(tmp_path):
    import b_qwen_phase2_concurrent as c
    rows=p.dev_rows()[:1]; inputs=tmp_path/'in.jsonl';p.bp.jsonl(inputs,rows)
    config=c.configuration(); h=c.request_hash(rows[0],config)
    p.bp.atomic_json(tmp_path/'out/cache'/f'{h}.json',{'status':'success','request_hash':h,'model':'wrong'})
    with pytest.raises(ValueError,match='cached success'):
        c.run_concurrent(inputs,tmp_path/'out',workers=2,transport=lambda _:pytest.fail('called API'))


def test_truncation_retry_and_failure_resume_keep_original_budgets(tmp_path):
    import b_qwen_phase2_concurrent as c
    rows=p.dev_rows()[:1];inputs=tmp_path/'in.jsonl';p.bp.jsonl(inputs,rows)
    budgets=[];config=c.configuration()
    def truncated(payload):
        budgets.append(payload['max_tokens'])
        return {'model':config['expected_model'],'choices':[{'finish_reason':'length','message':{'content':'{'}}],'usage':{'total_tokens':1}}
    out=tmp_path/'out'
    result=c.run_concurrent(inputs,out,workers=2,transport=truncated)
    assert result['failed_n']==1 and budgets==[8192,16384]
    def good(payload):
        budgets.append(payload['max_tokens'])
        return {'model':config['expected_model'],'choices':[{'finish_reason':'stop','message':{'content':p.bp.canonical(p.fixture_prediction())}}],'usage':{'total_tokens':1}}
    result=c.run_concurrent(inputs,out,workers=2,transport=good)
    assert result['success_n']==1 and budgets==[8192,16384,8192]
    assert len(p.bp.read_jsonl(out/'usage_log.jsonl'))==3


def test_second_coordinator_refused_before_call(tmp_path):
    import fcntl
    import b_qwen_phase2_concurrent as c
    out=tmp_path/'out';out.mkdir()
    with (out/'.concurrent.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='Another concurrent runner'):
            c.run_concurrent(tmp_path/'unused',out,transport=lambda _:pytest.fail('called API'))
