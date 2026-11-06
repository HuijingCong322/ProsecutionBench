import sys,json,time,platform,hashlib
from pathlib import Path
import torch
from transformers import AutoTokenizer,AutoModel
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_embedding_profiles import DEFAULT,RUNTIME,readjl,write_json
if len(sys.argv)>1: DEFAULT=Path(sys.argv[1]).resolve()
print('MPS',torch.backends.mps.is_available(),flush=True)
if not torch.backends.mps.is_available():raise RuntimeError('MPS unavailable in benchmark')
torch.set_num_threads(4);torch.manual_seed(0)
tok=AutoTokenizer.from_pretrained(RUNTIME/'model',local_files_only=True)
model=AutoModel.from_pretrained(RUNTIME/'model',local_files_only=True,torch_dtype=torch.float16,attn_implementation='sdpa').to('mps').eval()
records=readjl(DEFAULT/'technical_records.jsonl');long=max(records,key=lambda r:len(r['text']));ids=tok.encode(long['text'],add_special_tokens=False,truncation=False)
results=[]
for n in [512,2046,4094,8190]:
 inp=tok.prepare_for_model(ids[:n],add_special_tokens=True,truncation=False,return_attention_mask=True)
 t={k:torch.tensor([v],device='mps') for k,v in inp.items() if k in ['input_ids','attention_mask']};torch.mps.synchronize();started=time.perf_counter()
 with torch.inference_mode():out=model(**t).last_hidden_state[:,0,:].float().cpu()
 torch.mps.synchronize();elapsed=time.perf_counter()-started
 assert out.shape==(1,1024) and torch.isfinite(out).all() and out.norm()>0
 r={'content_tokens':n,'total_tokens':len(inp['input_ids']),'elapsed_seconds':elapsed,'mps_allocated_bytes':torch.mps.current_allocated_memory(),'mps_driver_bytes':torch.mps.driver_allocated_memory(),'dense_norm_before_normalization':float(out.norm())};results.append(r);print(json.dumps(r),flush=True)
 del t,out;torch.mps.empty_cache()
write_json(DEFAULT/'local_runtime_benchmark.json',{'device':'mps','dtype':'float16','dense_output_dtype':'float32','attention':'sdpa','torch':torch.__version__,'platform':platform.platform(),'cpu_threads':4,'recommended_mps_max_memory':torch.mps.recommended_max_memory(),'measurements':results,'benchmark_text_sha256':long['text_sha256'],'benchmark_slices_not_production_truncation':True})
print('DONE',flush=True)
