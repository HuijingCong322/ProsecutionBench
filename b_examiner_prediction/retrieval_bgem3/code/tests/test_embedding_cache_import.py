import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def test_exact_input_vectors_can_migrate_only_when_encoder_operation_is_identical(tmp_path):
 from b_embedding_cache_import import import_exact
 from b_sentence_embedding import VectorCache
 old={'dimension':2,'revision':'r','dtype':'fp32','text_template':'T','source_code_sha256':'old','measured_length_audit_sha256':'old'}
 new={**old,'source_code_sha256':'new','measured_length_audit_sha256':'new'}
 oc=VectorCache(tmp_path,old);nc=VectorCache(tmp_path,new);saved=oc.put('same technical text',[1.,0.],{'chunks':1,'truncated':False})
 assert import_exact('different technical text',oc,nc) is False
 assert import_exact('same technical text',oc,nc) is True
 loaded=nc.get('same technical text');assert loaded['vector']==[1.,0.] and loaded['metadata']['imported_from_checksum']==saved['checksum']
 changed=VectorCache(tmp_path,{**new,'dtype':'fp16'})
 with pytest.raises(ValueError,match='operation'):import_exact('same technical text',oc,changed)
 changed=VectorCache(tmp_path,{**new,'text_template':'DIFFERENT'})
 with pytest.raises(ValueError,match='operation'):import_exact('same technical text',oc,changed)
