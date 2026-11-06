"""Keep old profiles immutable and require new, source-bound material."""
import sys,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def module():
 import b_embedding_profiles
 return b_embedding_profiles

def test_profile_module_exists():assert (Path(__file__).resolve().parents[1]/'b_embedding_profiles.py').is_file()
def test_quote_is_exact_source_prefix_and_marked_clipping(tmp_path):
 m=module();p=tmp_path/'source.txt';p.write_text('A turbine uses a rotor. '+('Technical material. '*20))
 q=m.quote(p,80)
 assert q['quote']==p.read_text()[:q['end_char']]
 assert q['clipped'] is True and q['sha1']
def test_render_preserves_statistics_without_mutating_old_profile():
 m=module();old={'sample_id':'S','cutoff':'2015-01-01','setting':'own','statistics':{'n':7},'shrunk_statistics':{},'statistics_text':'raw 7','statistics_text_sha1':'stat','card_sha1':'card','D_card_sha1':'card','profile_text':'old','retrieved_cases':[],'limitations':[]}
 before=copy.deepcopy(old)
 r=m.render_profile(old,[],'{D_verified_statistics_with_denominators}\n{three_retrieved_two_line_case_summaries_with_sources}',{'model_id':'BAAI/bge-m3','revision':'new'},'hash')
 assert old==before and r['statistics']=={'n':7} and r['card_sha1']=='card'
 assert r['profile_text']!='old' and r['profile_text_sha1'] and r['retrieved_k']==0
 assert r['C_review_status']=='pending_new_review'
 assert 'Codex' not in r['profile_text']
def test_new_output_refuses_existing_directory(tmp_path):
 m=module()
 with pytest.raises(ValueError):m.new_output(tmp_path)

def test_profile_does_not_claim_old_retrieval_review_or_prior_query():
 m=module();old={'sample_id':'S','cutoff':'2015-01-01','setting':'own','statistics_text':'raw','statistics':{},'shrunk_statistics':{},'card_sha1':'c','D_card_sha1':'c','limitations':[],'query_sha1':'OLD','retrieval_review_action':'unchanged_D_pool_TFIDF_selection','review_quarantine_policy':'old','reviewed_candidate_file_sha1':'OLD'}
 r=m.render_profile(old,[],'{D_verified_statistics_with_denominators}{three_retrieved_two_line_case_summaries_with_sources}',{'model_id':'BAAI/bge-m3','revision':'r'},'q')
 assert r['retrieval_review_action']=='new_embedding_selection_pending_review'
 assert 'review_quarantine_policy' not in r and 'reviewed_candidate_file_sha1' not in r
 assert r['query_sha1'] is None

def test_review_gate_removes_only_recorded_weak_cases_without_replacement(tmp_path):
 m=module();old={'sample_id':'S','cutoff':'2015-01-01','setting':'own','statistics_text':'raw','statistics':{},'shrunk_statistics':{},'card_sha1':'c','D_card_sha1':'c','limitations':[],'profile_text':'old','profile_text_sha1':'text','retrieved_cases':[{'app_id':'A','summary_lines':['a'],'rank':1},{'app_id':'B','summary_lines':['b'],'rank':2},{'app_id':'C','summary_lines':['c'],'rank':3}]}
 path=tmp_path/'p.json';m.write_json(path,old)
 review={'profile_sha1':m.s.sha(path),'profile_text_sha1':'text','verdict':'needs_fix','weak_app_ids':'B'}
 result=m.apply_relevance_gate(path,review,'{D_verified_statistics_with_denominators}{three_retrieved_two_line_case_summaries_with_sources}',{'model_id':'BAAI/bge-m3','revision':'r'},'q')
 assert [r['app_id'] for r in result['retrieved_cases']]==['A','C']
 assert result['retrieved_k']==2 and result['card_sha1']=='c'
 assert result['review_withheld_app_ids']==['B']
 review['profile_sha1']='stale'
 with pytest.raises(ValueError,match='review hash'):m.apply_relevance_gate(path,review,'',{},'q')
