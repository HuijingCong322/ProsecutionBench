"""Pinned BGE-M3 CLS dense vectors. No sparse/ColBERT/reranker or task prefixes."""
from __future__ import annotations
import hashlib,json,math,os
from pathlib import Path

MODEL_ID='BAAI/bge-m3'
REVISION='5617a9f61b028005a4858fdac845db406aefb181'

def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def token_windows(n,window,overlap):
 if window<=0 or not 0<=overlap<window:raise ValueError('Invalid token window/overlap')
 result=[];start=0
 while start<n:
  end=min(start+window,n);result.append((start,end))
  if end==n:break
  start=end-overlap
 return result

def cache_key(contract,text):return digest({'contract':contract,'text':text})
def unit(v):
 v=[float(x) for x in v]
 if not v or not all(math.isfinite(x) for x in v):raise ValueError('Nonfinite/empty vector')
 n=math.sqrt(sum(x*x for x in v))
 if n<=0:raise ValueError('Zero vector')
 return [x/n for x in v]
def select_top(items,k=3):
 selected=[];apps=set();families=set()
 for r in sorted(items,key=lambda r:(-r['score'],r['app_id'],r['family_id'],r['episode_id'])):
  if not math.isfinite(r['score']):raise ValueError('Nonfinite similarity')
  if r['app_id'] in apps or r['family_id'] in families:continue
  selected.append(r);apps.add(r['app_id']);families.add(r['family_id'])
  if len(selected)==k:break
 return selected

def write_json(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(p)

def verify_model_contract(contract,model_path):
 if (contract.get('model_id'),contract.get('revision'),contract.get('dimension'))!=(MODEL_ID,REVISION,1024):raise ValueError('Unsupported model/revision/dimension')
 root=Path(model_path).resolve()
 if not contract.get('artifacts'):raise ValueError('Missing model artifact hashes')
 for r in contract['artifacts']:
  p=(root/r['path']).resolve()
  if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size!=r['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('Model artifact mismatch: '+r['path'])

class VectorCache:
 def __init__(self,root,contract):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.contract=contract
 def get(self,text):
  key=cache_key(self.contract,text);p=self.root/(key+'.json')
  if not p.exists():return None
  r=json.loads(p.read_text());payload={k:v for k,v in r.items() if k!='checksum'}
  if digest(payload)!=r['checksum']:raise ValueError('Cache checksum mismatch')
  if r['key']!=key or r['contract_hash']!=digest(self.contract):raise ValueError('Cache contract mismatch')
  self.validate(r['vector']);return r
 def validate(self,v):
  if len(v)!=self.contract['dimension']:raise ValueError('Wrong dense dimension')
  normalized=unit(v)
  if max(abs(x-y) for x,y in zip(v,normalized))>1e-5:raise ValueError('Vector not normalized')
 def put(self,text,vector,metadata):
  self.validate(vector);key=cache_key(self.contract,text)
  r={'key':key,'contract_hash':digest(self.contract),'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'vector':[float(x) for x in vector],'metadata':metadata}
  r['checksum']=digest(r);write_json(self.root/(key+'.json'),r);return r

class DenseEncoder:
 def __init__(self,model_path,contract,cache_root):
  import torch
  from transformers import AutoModel,AutoTokenizer
  self.torch=torch;self.contract=contract;self.cache=VectorCache(cache_root,contract);self.reused=0;self.computed=0
  verify_model_contract(contract,model_path)
  if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=contract['encoder_sha256']:raise ValueError('Frozen encoder implementation changed')
  import importlib.metadata
  for package,expected in contract['dependencies'].items():
   if importlib.metadata.version(package)!=expected:raise ValueError('Embedding dependency version changed: '+package)
  torch.set_num_threads(contract['cpu_threads']);torch.manual_seed(0)
  self.tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True)
  dtype={'float16':torch.float16,'float32':torch.float32}[contract['dtype']]
  self.model=AutoModel.from_pretrained(model_path,local_files_only=True,torch_dtype=dtype,attn_implementation=contract['attention']).to(contract['device']).eval()
  if self.model.config.hidden_size!=contract['dimension']:raise ValueError('Model dimension mismatch')
 def encode(self,text):
  if not text.strip():raise ValueError('Cannot encode missing technical text')
  old=self.cache.get(text)
  if old:self.reused+=1;return old
  torch=self.torch;ids=self.tokenizer.encode(text,add_special_tokens=False,truncation=False)
  windows=token_windows(len(ids),self.contract['content_window'],self.contract['overlap']);vectors=[]
  for a,b in windows:
   inp=self.tokenizer.prepare_for_model(ids[a:b],add_special_tokens=True,truncation=False,return_attention_mask=True)
   if len(inp['input_ids'])>self.contract['max_sequence_length']:raise ValueError('Silent truncation prevention')
   tensors={k:torch.tensor([v],device=self.contract['device']) for k,v in inp.items() if k in ['input_ids','attention_mask']}
   with torch.inference_mode():v=self.model(**tensors).last_hidden_state[:,0,:].float().cpu()[0].tolist()
   vectors.append(unit(v))
  # Equal-weight chunk mean, normalized; single chunk is the model's normalized CLS dense output.
  vector=unit([sum(x)/len(vectors) for x in zip(*vectors)])
  result=self.cache.put(text,vector,{'content_tokens':len(ids),'chunks':len(windows),'offsets':windows,'truncated':False,'dense_pooling':'CLS','aggregation':'equal_chunk_mean_then_L2'})
  self.computed+=1;return result
