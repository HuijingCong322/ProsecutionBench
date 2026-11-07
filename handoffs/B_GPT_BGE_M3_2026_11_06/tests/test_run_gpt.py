"""Behavior tests: tampering/gating/provenance/resume, with only network replaced."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
import pytest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE/'code'))
import b_prediction as bp


def module():
    assert (SOURCE/'run_gpt.py').is_file(), 'New runnable GPT handoff is not implemented'
    return importlib.import_module('run_gpt')


def seal(root):
    files=[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in sorted(root.rglob('*')) if p.is_file() and p.name!='PACKAGE_MANIFEST.json'
           and '__pycache__' not in p.parts]
    (root/'PACKAGE_MANIFEST.json').write_text(json.dumps({'private_team_only':True,'files':files}))


@pytest.fixture
def package(tmp_path):
    m=module(); root=tmp_path/'package'; root.mkdir()
    shutil.copy(SOURCE/'run_gpt.py',root/'run_gpt.py')
    shutil.copytree(SOURCE/'code',root/'code',ignore=shutil.ignore_patterns('__pycache__'))
    (root/'inputs').mkdir(); (root/'prompts').mkdir()
    (root/'prompts/examiner_prediction.FROZEN.txt').write_text('Return valid prediction JSON.')
    config={'endpoint':'https://example.test/openai/v1/','deployment':'test',
            'expected_model':'gpt-5-mini-2025-08-07','deployment_type':'Global Standard'}
    (root/'frozen_setting.json').write_text(json.dumps({'config':config}))
    protocol={'package_id':'synthetic_test','release_id':'test_release','core_n':1,'dev_n':3,
              'baseline_reuse_verified_by_B':True,'configuration':{
        **config,'task':'prediction','reasoning_effort':'low','initial_max_completion_tokens':8192,
        'retry_max_completion_tokens':16384,'content_attempt_limit':2,'temperature':'omitted',
        'transport_retries':0,'response_format':{'type':'json_object'},
        'implementation_hash':hashlib.sha256((root/'code/b_prediction.py').read_bytes()).hexdigest()}}
    (root/'protocol.json').write_text(json.dumps(protocol))
    def row(s, variant):
        base='OBSERVED CASE '+s; text='Own history' if variant=='own' else 'Other history'
        return {'sample_id':s,'app_id':s.removesuffix('_t1'),'cutoff':'2010-01-01',
                'input_hash':'fixedinput','state_hash':'fixedstate','state_input_hash':'fixedstateinput',
                'state_prompt_hash':'fixedstateprompt','missing_doc_ids':[],
                'input_setting':variant,'base_user_message_hash':hashlib.sha256(base.encode()).hexdigest(),
                'profile_hash':hashlib.sha256(text.encode()).hexdigest(),
                'profile_provenance':{'profile_text_sha1':hashlib.sha1(text.encode()).hexdigest(),
                    'release_id':'test_release','retrieved_k':'0','card_sha1':'fixedcard'},
                'user_message':base+'\n\nEXAMINER PROFILE (past, other families):\n'+text}
    for v in ('own','mismatched'):bp.jsonl(root/'inputs'/f'{v}.jsonl',[row('123_t1',v)])
    dev=[row(str(i)+'_t1','dev_format_only') for i in range(3)]
    bp.jsonl(root/'inputs/dev.jsonl',dev);seal(root)
    return m,root


def send(payload):
    return {'model':'gpt-5-mini-2025-08-07','choices':[{'finish_reason':'stop','message':{'content':json.dumps({
        'p_second_oa':.7,'p_type':{'CTNF':.2,'CTFR':.5,'NOA':.3},'predicted_type':'CTFR',
        'claim_ground_pairs':[[343,'103']]})}}],'usage':{'total_tokens':10}}


def test_tampered_input_rejected_before_execution(package):
    m,root=package
    with (root/'inputs/own.jsonl').open('a') as f:f.write('changed')
    with pytest.raises(ValueError,match='hash'):m.check(root)


def test_different_base_or_state_between_conditions_is_rejected(package):
    m,root=package
    rows=bp.read_jsonl(root/'inputs/mismatched.jsonl');rows[0]['state_hash']='different'
    bp.jsonl(root/'inputs/mismatched.jsonl',rows);seal(root)
    with pytest.raises(ValueError,match='base|state'):m.check(root)


def test_core_cannot_run_before_real_dev_gate(package):
    m,root=package
    with pytest.raises(ValueError,match='dev'):m.execute(root,'core',transport=send)
    assert not (root/'runs/gpt/own').exists()


def test_dev_gate_provenance_and_success_cache(package):
    m,root=package
    m.execute(root,'dev',transport=send)
    m.execute(root,'core',transport=send)
    rows=bp.read_jsonl(root/'runs/gpt/own/examiner_prediction.jsonl')
    provenance=bp.read_jsonl(root/'runs/gpt/own/request_provenance.jsonl')
    assert rows[0]['status']=='success' and rows[0]['request_hash']==provenance[0]['request_hash']
    assert provenance[0]['profile_provenance']['release_id']=='test_release'
    assert rows[0]['state_hash']=='fixedstate'
    def forbidden(payload):raise AssertionError('Successful result should not call network again')
    m.execute(root,'core',transport=forbidden)
    rows=bp.read_jsonl(root/'runs/gpt/own/examiner_prediction.jsonl')
    assert rows[0]['status']=='success'
    out=m.export_results(root)
    with zipfile.ZipFile(out) as z:
        assert any(n.endswith('/runs/gpt/own/request_provenance.jsonl') for n in z.namelist())
        assert any('/raw/' in n for n in z.namelist())
        assert not any('gold' in n or '.venv/' in n for n in z.namelist())


def test_changed_dev_results_invalidates_gate(package):
    m,root=package;m.execute(root,'dev',transport=send)
    p=root/'runs/gpt/dev/examiner_prediction.jsonl';p.write_text('[]')
    with pytest.raises(ValueError,match='dev'):m.execute(root,'core',transport=send)


def test_offline_does_not_create_live_gate(package):
    m,root=package
    report=m.offline(root)
    assert report['api_calls']==0 and report['checks_passed']
    assert not (root/'runs/gpt/dev/live_gate.json').exists()


def test_failed_core_is_explicit_and_export_reports_incomplete(package):
    m,root=package;m.execute(root,'dev',transport=send)
    def failure(payload):raise RuntimeError('network failure')
    summary=m.execute(root,'core',transport=failure)
    assert summary['own']['success_n']==0 and summary['own']['failed_n']==1
    out=m.export_results(root)
    with zipfile.ZipFile(out) as z:
        name=next(n for n in z.namelist() if n.endswith('/RETURN_MANIFEST.json'))
        report=json.loads(z.read(name));assert report['core_complete'] is False


def test_resume_partial_results_without_cache_does_not_resend_success(package):
    m,root=package;m.execute(root,'dev',transport=send);m.execute(root,'core',transport=send)
    # Interrupted summary may contain only a completed prefix; cache can be lost.
    shutil.rmtree(root/'runs/gpt/own/cache')
    def forbidden(payload):raise AssertionError('Previously verified success must be reused')
    m.execute(root,'core',transport=forbidden)
    assert bp.read_jsonl(root/'runs/gpt/own/examiner_prediction.jsonl')[0]['status']=='success'
    # A truncated/partial summary with a valid successful prefix is resumable.
    bp.jsonl(root/'runs/gpt/own/examiner_prediction.jsonl',[])
    m.execute(root,'core',transport=forbidden)
    assert len(bp.read_jsonl(root/'runs/gpt/own/examiner_prediction.jsonl'))==1
