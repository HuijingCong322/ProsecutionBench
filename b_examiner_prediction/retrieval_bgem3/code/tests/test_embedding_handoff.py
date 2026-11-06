import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def test_handoff_module_exists():assert (Path(__file__).resolve().parents[1]/'b_embedding_handoff.py').is_file()
def test_review_cohort_cannot_be_replaced_or_duplicated():
 from b_embedding_handoff import require_review_cohort
 rows=[{'sample_id':'S','variant':v} for v in ['own','mismatched','artunit']]
 require_review_cohort(rows,['S'])
 with pytest.raises(ValueError):require_review_cohort(rows+rows,['S'])
 with pytest.raises(ValueError):require_review_cohort(rows,['T'])

def test_seal_rejects_profile_modified_after_review(tmp_path):
 from b_embedding_handoff import verify_final_files
 import json,hashlib,csv
 p=tmp_path/'p.json';body='visible profile';p.write_text(json.dumps({'profile_text':body,'profile_text_sha1':hashlib.sha1(body.encode()).hexdigest(),'retrieved_cases':[],'retrieved_k':0,'card_sha1':'card'}))
 (tmp_path/'RELEASE_MANIFEST.json').write_text('{"profiles":1}')
 row={'profile_path':'p.json','profile_sha1':hashlib.sha1(p.read_bytes()).hexdigest(),'profile_text_sha1':hashlib.sha1(body.encode()).hexdigest(),'retrieved_k':0,'card_sha1':'card'}
 with (tmp_path/'profile_manifest.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=row);w.writeheader();w.writerow(row)
 verify_final_files(tmp_path)
 p.write_text(p.read_text()+' ')
 with pytest.raises(ValueError,match='final profile'):verify_final_files(tmp_path)

def test_second_seal_cannot_rewrite_existing_manifest(tmp_path):
 from b_embedding_handoff import seal
 d=tmp_path/'release';d.mkdir();(d/'profile_manifest.csv').write_text('profile_path\n');(d/'RELEASE_MANIFEST.json').write_text('{"profiles":0,"release_id":"r"}')
 m=d/'HANDOFF_MANIFEST_SHA256.json';m.write_text('KEEP')
 (tmp_path/'release_TEAM_ONLY.zip').write_bytes(b'old archive')
 with pytest.raises(ValueError):seal(d)
 assert m.read_text()=='KEEP'
