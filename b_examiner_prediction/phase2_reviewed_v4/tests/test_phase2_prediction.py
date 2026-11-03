import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import b_phase2_prediction as p


def test_append_profile_exposes_only_text_and_preserves_state():
    base={'sample_id':'a_t1','app_id':'a','cutoff':'2010-01-01','user_message':'BASE','state_hash':'fixed'}
    profile={'prediction_sample_id':'a_t1','cutoff':'2010-01-01','profile_text':'HISTORY','card_sha1':'secret','review':'secret'}
    result=p.append_profile(base,profile,{'profile_sha1':'file','profile_text_sha1':p.sha1('HISTORY'),'card_sha1':'secret'},'own')
    assert result['user_message']=='BASE'+p.PROFILE_HEADER+'HISTORY'
    assert result['state_hash']=='fixed' and base['user_message']=='BASE'
    bad={**profile,'cutoff':'2011-01-01'}
    with pytest.raises(ValueError):p.append_profile(base,bad,{},'own')


def test_profile_text_tamper_rejected():
    with pytest.raises(ValueError):
        p.append_profile({'sample_id':'a','cutoff':'x','user_message':'base'},
                         {'prediction_sample_id':'a','cutoff':'x','profile_text':'changed'},
                         {'profile_text_sha1':p.sha1('old')},'own')


def test_gold_unknown_and_out_of_scope_are_excluded():
    types=[{'sample_id':'a','eligible':'True','next_type':'allowance','occurrence':'0'},
           {'sample_id':'b','eligible':'True','next_type':'final_rejection','occurrence':'1'},
           {'sample_id':'c','eligible':'False','next_type':'restriction','occurrence':''}]
    grounds=[{'sample_id':'a','pairs':[]},{'sample_id':'b','pairs':None},{'sample_id':'c','pairs':[]}]
    rows=p.eligibility(types,grounds,{'a':'f','b':'f','c':'g'})
    assert [r['sample_id'] for r in rows if r['ground_eligible']]==['a']
    assert rows[1]['ground_exclusion']=='unknown_ground_label'
    assert rows[2]['type_exclusion']=='out_of_scope:restriction'


def test_paired_bootstrap_clusters_and_is_deterministic():
    rows=[{'sample_id':str(i),'family_id':'f'+str(i//2),'eligible':True,'next_type':t,'occurrence':int(t!='allowance'),'pairs':[]} for i,t in enumerate(['allowance','final_rejection','allowance','nonfinal_rejection'])]
    pred={'p_second_oa':.7,'p_type':{'CTNF':.2,'CTFR':.5,'NOA':.3},'predicted_type':'CTFR','claim_ground_pairs':[]}
    results={r['sample_id']:{'status':'success','prediction':pred} for r in rows}
    out=p.paired_comparison(rows,results,results,n_boot=1000)
    assert out['bootstrap_n']==1000 and out['seed']==20261010
    assert out['family_n']==2 and out['metrics']['Occ']['delta']==0
    assert out['metrics']['Occ']['ci95']==[0.,0.]
    assert out==p.paired_comparison(rows,results,results,n_boot=1000)


def test_baseline_message_change_is_rejected():
    rows=p.bp.read_jsonl(p.CORE)
    rows[0]={**rows[0],'user_message':rows[0]['user_message']+' changed'}
    with pytest.raises(ValueError,match='Base message changed'):
        p.audit_baseline('gpt',rows)


def test_bootstrap_point_metrics_match_original_scorer_with_unknown_gold():
    gold=[{'sample_id':str(i),'family_id':'f'+str(i//2),'eligible':True,
           'next_type':t,'occurrence':int(t!='allowance'),'pairs':pairs}
          for i,(t,pairs) in enumerate([('allowance',[]),('final_rejection',[[343,'103']]),
                                        ('nonfinal_rejection',None),('allowance',[])])]
    results={r['sample_id']:{'sample_id':r['sample_id'],'status':'success',
              'prediction':p.fixture_prediction()} for r in gold}
    original=p.bp.score(gold,list(results.values()))
    actual=p.paired_comparison(gold,results,results,n_boot=10)
    assert actual['paired_ground_n']==3
    for metric in ('Occ','Type','Grnd'):
        assert actual['metrics'][metric]['left']==pytest.approx(original[metric]['value'])


def test_full_offline_harness_checks_retry_and_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'ROOT',tmp_path)
    monkeypatch.setattr(p,'check_locks',lambda:None)
    p.bp.jsonl(tmp_path/'inputs/dev.jsonl',p.dev_rows())
    audits={m:p.audit_baseline(m,p.bp.read_jsonl(p.CORE)) for m in p.MODELS}
    p.bp.atomic_json(tmp_path/'baseline_reuse.json',audits)
    report=p.offline()
    assert report['api_calls']==0 and not report['scored']
    assert all(r['resume_simulated_calls']==2 for r in report['models'])


def test_existing_taxonomy_exclusion_is_preserved():
    types,grounds=p.scoring_gold()
    rows=p.eligibility(types,grounds,{r['sample_id']:r['sample_id'] for r in types})
    assert sum(r['type_eligible'] for r in rows)==99
    assert sum(r['ground_eligible'] for r in rows)==62
    conflict=next(r for r in rows if r['sample_id']=='14012315_t1')
    assert conflict['type_eligible'] and conflict['ground_exclusion']=='taxonomy_conflict:112d'
