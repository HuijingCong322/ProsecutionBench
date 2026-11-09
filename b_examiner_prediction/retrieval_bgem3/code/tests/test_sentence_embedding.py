"""Real cache/window/ranking guards; the neural forward pass is separately benchmarked."""
import sys,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def module():
 import b_sentence_embedding
 return b_sentence_embedding

def test_embedding_module_exists():assert (Path(__file__).resolve().parents[1]/'b_sentence_embedding.py').is_file()
def test_windows_cover_every_token_without_truncation():
 m=module();w=m.token_windows(25,10,2)
 assert w==[(0,10),(8,18),(16,25)]
 assert set(i for a,b in w for i in range(a,b))==set(range(25))
 with pytest.raises(ValueError):m.token_windows(25,10,10)
def test_cache_invalidates_with_revision_and_templates():
 m=module();assert m.cache_key({'revision':'a','template':'a'},'technical')!=m.cache_key({'revision':'b','template':'a'},'technical')
 assert m.cache_key({'revision':'a','template':'a'},'technical')!=m.cache_key({'revision':'a','template':'b'},'technical')
def test_cosine_ranking_ties_stable_and_family_unique():
 m=module();items=[{'app_id':'B','family_id':'F','episode_id':'b','score':1.},{'app_id':'A','family_id':'F','episode_id':'a','score':1.},{'app_id':'C','family_id':'G','episode_id':'c','score':0.5}]
 assert [r['app_id'] for r in m.select_top(items)]==['A','C']
def test_invalid_vector_cannot_be_cached_or_loaded(tmp_path):
 m=module();c=m.VectorCache(tmp_path,{'dimension':2,'revision':'a'})
 with pytest.raises(ValueError):c.put('T',[0.,0.],{})
 with pytest.raises(ValueError):c.put('T',[float('nan'),1.],{})
 c.put('T',[1.,0.],{'chunks':1});assert c.get('T')['vector']==[1.,0.]
 path=next(tmp_path.glob('*.json'));v=json.loads(path.read_text());v['vector']=[0.,1.];path.write_text(json.dumps(v))
 with pytest.raises(ValueError,match='checksum'):c.get('T')

def test_model_contract_rejects_wrong_revision_and_changed_artifact(tmp_path):
 m=module();p=tmp_path/'config.json';p.write_text('pinned')
 import hashlib
 c={'model_id':'BAAI/bge-m3','revision':m.REVISION,'dimension':1024,'artifacts':[{'path':'config.json','bytes':6,'sha256':hashlib.sha256(b'pinned').hexdigest()}]}
 m.verify_model_contract(c,tmp_path)
 c['revision']='not_approved'
 with pytest.raises(ValueError,match='model/revision'):m.verify_model_contract(c,tmp_path)
 c['revision']=m.REVISION;p.write_text('changed')
 with pytest.raises(ValueError,match='artifact'):m.verify_model_contract(c,tmp_path)
