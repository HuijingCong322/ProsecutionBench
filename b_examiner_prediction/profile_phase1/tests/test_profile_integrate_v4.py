import sys,copy,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import b_profile_integrate_v4 as p


def card():
    c={'sample_id':'13484627','variant':'own','cutoff':'2015-04-03','card_text':'Grounds in 2 signed rejections: 103 in 50%.','stats':{'n':2},'shrunk':None}
    c['card_sha1']=hashlib.sha1(json.dumps(c,sort_keys=True).encode()).hexdigest();return c


def test_contact_attribution_replaces_signatory_claim_globally():
    assert p.attribution_text('signature verified in A actions.csv')=='examiner of record verified (contact paragraph; may be co-signed by a primary/SPE)'
    assert 'handling examiner' in p.attribution_text('Grounds in 2 signed rejections: 103 in 50%.')
    assert 'signature verified' not in p.attribution_text('signature verified in A actions.csv')
    assert 'handling examiner not verified' in p.attribution_text('assigned-examiner attribution; signature unverified')


def test_restore_original_tfidf_episode_without_changing_card_or_source():
    eid='ex_2acc44e527:13482424:2014-11-25:I5XVMRV0PXXIFW4'
    source={'sample_id':'13484627','setting':'own','retrieved_cases':[{'episode_id':eid,'app_id':'13482424','signature_basis':'actions_csv_verified','summary_lines':['Reply text','Next: signature verified in A actions.csv.']}],
            'retrieved_k':1,'statistics_text':'old','limitations':[]}
    original=copy.deepcopy(source);c=card()
    r=p.revise(source,c,'{D_verified_statistics_with_denominators}\n{three_retrieved_two_line_case_summaries_with_sources}\nCompare a signature-verified action.',set())
    assert source==original and r['retrieved_k']==1 and r['retrieved_cases'][0]['episode_id']==eid
    assert r['statistics']==c['stats'] and r['card_sha1']==c['card_sha1'] and r['D_original_card_text']==c['card_text']
    assert 'signed rejections' not in r['profile_text'] and 'signature verified' not in r['profile_text'] and 'signature-verified' not in r['profile_text']
    assert r['retrieved_cases'][0]['examiner_attribution_basis']=='contact_paragraph_handling_examiner_verified_by_A'
    assert r['retrieved_cases'][0]['signature_basis']=='actions_csv_verified'
    assert r['freeze_status']=='candidate_pending_D_C_team'


def test_template_uses_contact_attribution_without_signatory_claims():
    template='Compare an assignment-attributed notice with a signature-verified action.'
    assert 'signature-verified' not in p.attribution_text(template)
    assert 'handling-examiner' in p.attribution_text(template)
