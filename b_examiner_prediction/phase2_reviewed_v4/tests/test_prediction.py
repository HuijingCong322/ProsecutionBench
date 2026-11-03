import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_prediction import prepare, validate_prediction, score, run


def pred(kind='CTFR', p=0.8, pairs=None):
    return {'p_second_oa':p,'p_type':{'CTNF':0.0,'CTFR':p,'NOA':1-p},
            'predicted_type':kind,'claim_ground_pairs':pairs or []}


@pytest.fixture
def package(tmp_path):
    import csv
    root=tmp_path/'dataset';root.mkdir()
    (root/'examples').mkdir();(root/'history.txt').write_text('OBSERVED HISTORY')
    (root/'target.txt').write_text('FUTURE TARGET SECRET')
    row={'sample_id':'123_t1','app_id':'123','family_id':'f1','split':'test','test_core':'True',
         'gen_core':'True','cutoff':'2015-01-01','input_hash':'sharedhash','input_doc_ids':'doc1','missing_doc_ids':''}
    with (root/'sample_manifest.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    example={'app_id':'123','cutoff':row['cutoff'],'inputs':[{'doc_id':'doc1','doc_code':'REM',
             'date':'2015-01-01','text_path':'history.txt','source':'uspto_xml','role':'A1'}],
             'target':{'doc_id':'o2','text_path':'target.txt','source':'uspto_xml'},
             'labels':{'next_type':'final_rejection','occurrence':1,'ordering_uncertain':False,
                       'censored':False,'grounds_o2':{'pairs':[[1,'103'],[2,'objection']]}}}
    (root/'examples/123.json').write_text(json.dumps(example))
    h=hashlib.sha1(b'OBSERVED HISTORY').hexdigest()[:16]
    inp={'sample_id':'123_t1','app_id':'123','stage':'A1_cutoff','cutoff':row['cutoff'],
         'input_hash':h,'input_text':'OBSERVED HISTORY','doc_ids':['doc1'],'omitted_doc_ids':[]}
    state={k:inp[k] for k in ['sample_id','app_id','stage','cutoff','input_hash']}
    state.update(parse_ok=True,finish_reason='stop',state={'entered_claims':[], 'proposed_claims':[], 'rejections':[]})
    for name,value in [('states.jsonl',state),('state_inputs.jsonl',inp)]:
        (tmp_path/name).write_text(json.dumps(value)+'\n')
    return root,tmp_path/'states.jsonl',tmp_path/'state_inputs.jsonl',tmp_path/'prepared'


def test_prepare_isolates_targets_and_preserves_hashes(package):
    summary=prepare(*package,group='core')
    row=json.loads((package[3]/'inputs/prediction_core.jsonl').read_text())
    assert 'OBSERVED HISTORY' in row['user_message']
    assert 'FUTURE TARGET SECRET' not in row['user_message']
    assert row['input_hash']=='sharedhash'
    assert row['state_input_hash'] != row['input_hash']
    assert summary['ready_n']==1
    gold=json.loads((package[3]/'gold/claim_ground_gold.core.draft.jsonl').read_text())
    assert gold['pairs']==[[1,'103']]
    assert gold['objection_pairs']==[[2,'objection']]


@pytest.mark.parametrize('change',[{'date':'2016-01-01'},{'text_path':'../states.jsonl'}])
def test_unsafe_history_rejected(package,change):
    path=package[0]/'examples/123.json';e=json.loads(path.read_text());e['inputs'][0].update(change);path.write_text(json.dumps(e))
    with pytest.raises(ValueError):prepare(*package,group='core')


def test_missing_state_keeps_coverage(package):
    package[1].write_text('')
    summary=prepare(*package,group='core')
    assert summary['blocked_n']==1
    assert (package[3]/'inputs/prediction_core.jsonl').read_text()==''


def test_duplicate_state_rejected(package):
    package[1].write_text(package[1].read_text()*2)
    with pytest.raises(ValueError):prepare(*package,group='core')


@pytest.mark.parametrize('mutator',[
 lambda x:x.update(p_second_oa=float('nan')),
 lambda x:x.update(p_second_oa=True),
 lambda x:x['p_type'].update(CTNF=0.5),
 lambda x:x.update(p_second_oa=0.7),
 lambda x:x.update(predicted_type='NOA'),
 lambda x:x.update(claim_ground_pairs=[[0,'103']]),
 lambda x:x.update(claim_ground_pairs=[[1,'objection']]),
])
def test_invalid_predictions_rejected(mutator):
    x=pred();mutator(x)
    with pytest.raises(ValueError):validate_prediction(x)


def test_duplicate_pairs_and_tie_are_deterministic():
    x=pred(p=0.5,pairs=[[1,'103'],[1,'103']])
    assert validate_prediction(x)['claim_ground_pairs']==[[1,'103']]


def test_score_known_metrics_and_false_positive_on_empty_gold():
    gold=[{'sample_id':str(i),'eligible':True,'next_type':t,'occurrence':y,'pairs':g}
          for i,(t,y,g) in enumerate([('CTNF',1,[[1,'103']]),('CTFR',1,[]),('NOA',0,[]),('NOA',0,[])])]
    values=[{'p_second_oa':.9,'p_type':{'CTNF':.9,'CTFR':0.,'NOA':.1},'predicted_type':'CTNF','claim_ground_pairs':[[1,'103']]},pred(p=.8,pairs=[[2,'102']]),pred('NOA',.1),pred('NOA',.2)]
    rows=[{'sample_id':str(i),'status':'success','prediction':v} for i,v in enumerate(values)]
    result=score(gold,rows)
    assert result['Occ']['value']==1
    assert result['Type']['value']==1
    assert result['Grnd']['tp']==1 and result['Grnd']['fp']==1
    assert result['Grnd']['value']==pytest.approx(2/3)
    rows[1]['status']='failed';rows[1]['reason']='invalid_json'
    assert score(gold,rows)['Occ']['failed_n']==1
    with pytest.raises(ValueError):score(gold,rows+[rows[0]])
    with pytest.raises(ValueError):score(gold,rows+[{'sample_id':'unexpected','status':'failed'}])


def test_unknown_ground_is_not_empty():
    gold=[{'sample_id':'s','eligible':True,'next_type':'NOA','occurrence':0,'pairs':None}]
    result=score(gold,[{'sample_id':'s','status':'success','prediction':pred('NOA',.1)}])
    assert result['Grnd']['eligible_n']==0
    assert result['Occ']['value'] is None


def response(content,finish='stop'):
    return {'model':'gpt-5-mini-2025-08-07','choices':[{'message':{'content':content},'finish_reason':finish}],
            'usage':{'prompt_tokens':100,'completion_tokens':20}}


@pytest.mark.parametrize('responses,budgets,status',[
 ([response('', 'length'),response(json.dumps(pred()))],[8192,16384],'success'),
 ([response('', 'length'),response('', 'length')],[8192,16384],'failed'),
 ([response('bad'),response(json.dumps(pred()))],[8192,8192],'success'),
 ([response('', 'length'),response('bad')],[8192,16384],'failed'),
])
def test_retry_budget_and_raw_attempts(package,responses,budgets,status):
    prepare(*package,group='core');calls=[]
    def transport(payload):
        calls.append(payload);return responses[len(calls)-1]
    prompt=package[3]/'prompt.txt';prompt.write_text('PREDICT JSON')
    out=package[3]/'run';config={'endpoint':'https://example.openai.azure.com/openai/v1/','deployment':'mini'}
    result=run(package[3]/'inputs/prediction_core.jsonl',prompt,out,config,transport=transport)
    assert [x['max_completion_tokens'] for x in calls]==budgets
    assert all('temperature' not in x and x['reasoning_effort']=='low' for x in calls)
    row=json.loads((out/'examiner_prediction.jsonl').read_text());assert row['status']==status
    assert len(list((out/'raw').glob('*.json')))==2
    assert result[status+'_n']==1


def test_cache_provenance_and_api_failure(package):
    prepare(*package,group='core');prompt=package[3]/'prompt';prompt.write_text('P1');out=package[3]/'run'
    config={'endpoint':'https://example.openai.azure.com/openai/v1/','deployment':'mini'};calls=[]
    def transport(payload):calls.append(payload);return response(json.dumps(pred()))
    inputs=package[3]/'inputs/prediction_core.jsonl'
    run(inputs,prompt,out,config,transport=transport);run(inputs,prompt,out,config,transport=transport)
    assert len(calls)==1
    prompt.write_text('P2');run(inputs,prompt,out,config,transport=transport);assert len(calls)==2
    config['deployment']='mini2';run(inputs,prompt,out,config,transport=transport);assert len(calls)==3
    def fail(payload):raise RuntimeError('PRIVATE_KEY_SHOULD_NOT_BE_LOGGED')
    prompt.write_text('P3');run(inputs,prompt,out,config,transport=fail)
    content=(out/'examiner_prediction.jsonl').read_text()
    assert 'PRIVATE_KEY' not in content and json.loads(content)['status']=='failed'


def test_wrong_model_and_changed_model_setting_are_not_reused(package):
    prepare(*package,group='core');prompt=package[3]/'prompt';prompt.write_text('P1');out=package[3]/'run'
    config={'endpoint':'https://example.openai.azure.com/openai/v1/','deployment':'mini','expected_model':'gpt-5-mini-2025-08-07','deployment_type':'Global Standard'}
    inputs=package[3]/'inputs/prediction_core.jsonl';calls=[]
    def transport(payload):
        calls.append(payload);return response(json.dumps(pred()))
    run(inputs,prompt,out,config,transport=transport)
    config['expected_model']='gpt-5-mini-2099-01-01'
    result=run(inputs,prompt,out,config,transport=transport)
    assert len(calls)==2 and result['failed_n']==1
    row=json.loads((out/'examiner_prediction.jsonl').read_text())
    assert row['reason']=='unexpected_model_version'


def test_malformed_api_envelope_retains_failure(package):
    prepare(*package,group='core');prompt=package[3]/'prompt';prompt.write_text('P1');out=package[3]/'run'
    result=run(package[3]/'inputs/prediction_core.jsonl',prompt,out,
               {'endpoint':'https://example.openai.azure.com/openai/v1/','deployment':'mini'},transport=lambda payload:[])
    assert result['failed_n']==1
    row=json.loads((out/'examiner_prediction.jsonl').read_text())
    assert row['reason']=='invalid_json_or_schema_or_finish'
    assert len(list((out/'raw').glob('*.json')))==2


def test_missing_actual_a1_blocks_even_when_prior_history_readable(package):
    root,states,state_inputs,out=package
    e=json.loads((root/'examples/123.json').read_text())
    e['inputs'][0]['role']='O1'
    e['inputs'].append({'doc_id':'missing_a1','doc_code':'REM','date':'2015-01-01',
                        'text_path':'missing.txt','source':'uspto_xml','role':'A1'})
    (root/'examples/123.json').write_text(json.dumps(e))
    p=root/'sample_manifest.csv';p.write_text(p.read_text().replace('sharedhash,doc1,','sharedhash,doc1;missing_a1,'))
    summary=prepare(*package,group='core')
    assert summary['ready_n']==0 and summary['blocked_n']==1
    assert 'missing_actual_A1' in (out/'preparation_coverage_core.csv').read_text()


def test_score_reports_draft_and_reviewed_denominators():
    gold=[{'sample_id':'s','eligible':True,'next_type':'NOA','occurrence':0,'pairs':[],
           'review_status':'automatic_unreviewed','ground_review_status':'human_verified'}]
    result=score(gold,[{'sample_id':'s','status':'success','prediction':pred('NOA',.1)}])
    assert result['Type']['gold_status']=='automatic_unreviewed'
    assert result['Grnd']['gold_status']=='human_verified'


def test_api_failure_is_in_log_and_does_not_stop_next_sample(package):
    prepare(*package,group='core');inputs=package[3]/'inputs/prediction_core.jsonl'
    row=json.loads(inputs.read_text());inputs.write_text(inputs.read_text()+json.dumps({**row,'sample_id':'other_t1'})+'\n')
    prompt=package[3]/'prompt';prompt.write_text('P1');out=package[3]/'run';calls=[]
    def transport(payload):
        calls.append(payload)
        if len(calls)==1:raise RuntimeError('SECRET_VALUE')
        return response(json.dumps(pred()))
    result=run(inputs,prompt,out,{'endpoint':'https://example.openai.azure.com/openai/v1/','deployment':'mini'},transport=transport)
    assert result['failed_n']==1 and result['success_n']==1
    logs=(out/'usage_log.jsonl').read_text()
    assert 'SECRET_VALUE' not in logs
    assert any(json.loads(l).get('reason')=='api_error' for l in logs.splitlines())
