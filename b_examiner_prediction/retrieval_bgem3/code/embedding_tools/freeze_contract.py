import sys,json,platform,importlib.metadata
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_embedding_profiles import DEFAULT,RUNTIME,write_json
if len(sys.argv)>1: DEFAULT=Path(sys.argv[1]).resolve()
from b_sentence_embedding import MODEL_ID,REVISION,digest
from b_sentence_sources import sha
bench=json.loads((DEFAULT/'local_runtime_benchmark.json').read_text());lengths=json.loads((DEFAULT/'length_audit.json').read_text());art=json.loads((RUNTIME/'model_artifacts.json').read_text());pool=json.loads((RUNTIME/'model/1_Pooling/config.json').read_text())
assert pool['pooling_mode_cls_token'] and not pool['pooling_mode_mean_tokens'] and bench['device']=='mps'
packages={line.split('==')[0]:line.split('==')[1] for line in (Path(__file__).resolve().parents[1]/'requirements.bgem3.lock.txt').read_text().splitlines() if '==' in line}
contract={'model_id':MODEL_ID,'revision':REVISION,'dimension':1024,'artifacts':art['files'],'dependencies':packages,'python_version':platform.python_version(),'platform':platform.platform(),'device':'mps','dtype':'float16','dense_output_dtype':'float32','attention':'sdpa','cpu_threads':4,'batch_size':1,'seed':0,'model_eval':True,'sparse':False,'colbert':False,'reranker':False,'task_prefix':'','text_template':'dated_technical_title_abstract_claims_v1; available fields concatenated Title/Abstract/Claims, whitespace normalized; no query/passage prefixes','max_sequence_length':8192,'content_window':8190,'overlap':128,'special_tokens':2,'long_text_policy':'token_id_windows_all_covered; normalized_CLS_per_window; equal_chunk_mean_then_L2; never truncate','normalization':'L2','similarity':'cosine_normalized_dot_product','sort':'score DESC, app_id ASC, family_root ASC, episode_id ASC','episode_choice':'earliest fully source-and-technical-eligible reply_date then episode_id per application; outcome-blind ordering','cache_root':str((DEFAULT.parent/'embedding_cache_bgem3_dense_v1').resolve()),'encoder_sha256':sha(Path(__file__).resolve().parents[1]/'b_sentence_embedding.py','sha256'),'source_code_sha256':sha(Path(__file__).resolve().parents[1]/'b_sentence_sources.py','sha256'),'measured_length_audit_sha256':sha(DEFAULT/'length_audit.json','sha256'),'local_benchmark_sha256':sha(DEFAULT/'local_runtime_benchmark.json','sha256'),'contract_status':'frozen_after_actual_text_lengths_and_local_GPU_benchmark','prediction_api_calls':0}
assert not (DEFAULT/'embedding_contract.json').exists()
write_json(DEFAULT/'embedding_contract.json',contract);print('Frozen contract',digest(contract),flush=True)
