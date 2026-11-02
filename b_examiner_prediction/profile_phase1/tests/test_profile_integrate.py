import sys,copy,hashlib,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import b_profile_integrate as p


def test_pool_is_case_variant_specific_and_unsigned_allowances_survive():
    rows=[{'sample_id':'a','variant':'own','next_observed':'True','next_signed_ok':'True','episode_id':'noa'},
          {'sample_id':'a','variant':'own','next_observed':'True','next_signed_ok':'False','episode_id':'wrong_signer'},
          {'sample_id':'a','variant':'own','next_observed':'False','next_signed_ok':'True','episode_id':'waiting'},
          {'sample_id':'b','variant':'own','next_observed':'True','next_signed_ok':'True','episode_id':'other_case'},
          {'sample_id':'a','variant':'mismatched','next_observed':'True','next_signed_ok':'True','episode_id':'other_variant'}]
    assert [r['episode_id'] for r in p.eligible_case_rows(rows,'a','own')]==['noa']


def card():
    c={'sample_id':'a','variant':'own','cutoff':'2015-01-01','card_text':'Raw original: allowance 32%; median 33.','stats':{},'shrunk':{}}
    c['card_sha1']=hashlib.sha1(json.dumps(c,sort_keys=True).encode()).hexdigest()
    return c


def test_statistics_retains_d_original_verbatim_and_explains_conventions():
    c=card();s=p.statistics_text(c)
    assert s.startswith(c['card_text']+'\n') and 'raw' in s and 'upper median' in s
    assert '32%' in s and '33' in s
    c['card_text']='changed'
    with pytest.raises(ValueError,match='card_sha1'):p.statistics_text(c)


def test_quarantine_is_explicit_and_does_not_mutate_old_profiles():
    source={'sample_id':'a','setting':'own','retrieved_cases':[{'episode_id':'bad','app_id':'1','summary_lines':['medical sentence','outcome']},
                                                            {'episode_id':'ok','app_id':'2','summary_lines':['antenna sentence','outcome']}],
            'retrieved_k':2,'statistics_text':'old','C_review_status':'pending','limitations':[]}
    original=copy.deepcopy(source)
    revised=p.revise(source,card(),'{D_verified_statistics_with_denominators}\n{three_retrieved_two_line_case_summaries_with_sources}',
                     quarantine_ids={'bad'},reject_block=False)
    assert source==original and [r['episode_id'] for r in revised['retrieved_cases']]==['ok']
    assert 'medical sentence' not in revised['profile_text'] and revised['card_sha1']==card()['card_sha1']
    assert revised['freeze_status']=='candidate_pending_D_C_team'
    assert revised['C_review_status']=='pending_re_review_new_hash'
    empty=p.revise(source,card(),'{D_verified_statistics_with_denominators}\n{three_retrieved_two_line_case_summaries_with_sources}',
                   quarantine_ids=set(),reject_block=True)
    assert empty['retrieved_k']==0 and empty['retrieved_cases']==[]
    assert 'No reviewed comparable examples' in empty['profile_text']


def test_missing_old_review_ui_is_reported_but_missing_profile_fails(tmp_path):
    manifest={'files':[{'path':'review/index.html','bytes':3,'sha256':'unused'}]}
    assert p.verify_c_sources(tmp_path,manifest)==['review/index.html']
    manifest['files'].append({'path':'candidate_profiles/own/a.json','bytes':2,'sha256':'unused'})
    with pytest.raises(ValueError,match='Missing required'):
        p.verify_c_sources(tmp_path,manifest)
