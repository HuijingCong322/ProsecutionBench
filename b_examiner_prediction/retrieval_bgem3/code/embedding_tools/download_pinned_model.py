from huggingface_hub import snapshot_download
from pathlib import Path
import json,hashlib,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_embedding_profiles import RUNTIME
root=RUNTIME
p=snapshot_download('BAAI/bge-m3',revision='5617a9f61b028005a4858fdac845db406aefb181',local_dir=root/'model',allow_patterns=['config.json','pytorch_model.bin','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model','1_Pooling/config.json','modules.json','sentence_bert_config.json'],max_workers=3)
files=[{'path':str(f.relative_to(root/'model')),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in sorted((root/'model').rglob('*')) if f.is_file() and '.cache' not in f.parts]
(root/'model_artifacts.json').write_text(json.dumps({'model_id':'BAAI/bge-m3','revision':'5617a9f61b028005a4858fdac845db406aefb181','files':files},indent=2)+'\n')
print('DONE',p,flush=True)
