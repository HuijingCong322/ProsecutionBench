import sys,json,time,platform
from pathlib import Path
from transformers import AutoTokenizer
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));from b_embedding_profiles import DEFAULT,RUNTIME,readjl,write_json,csvfile
records=readjl(DEFAULT/'technical_records.jsonl');tok=AutoTokenizer.from_pretrained(RUNTIME/'model',local_files_only=True)
rows=[]
for i,r in enumerate(records):
 n=len(tok.encode(r['text'],add_special_tokens=False,truncation=False));rows.append({'text_sha256':r['text_sha256'],'app_id':r['app_id'],'tokens':n,'chars':len(r['text'])})
 if (i+1)%1000==0:print('tokenized',i+1,flush=True)
counts=[r['tokens'] for r in rows]
csvfile(DEFAULT/'technical_lengths.csv',rows)
report={'tokenizer_model':'BAAI/bge-m3','revision':'5617a9f61b028005a4858fdac845db406aefb181','representations':len(rows),'token_percentiles':{str(p):float(np.percentile(counts,p)) for p in [0,50,90,95,99,100]},'over_8190':sum(x>8190 for x in counts),'over_2046':sum(x>2046 for x in counts),'silent_truncation':False}
write_json(DEFAULT/'length_audit.json',report);print(json.dumps(report,indent=2),flush=True)
