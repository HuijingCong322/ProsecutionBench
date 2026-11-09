"""Audited cache migration: exact text + identical encoder operation, provenance-only changes."""
from pathlib import Path
import argparse,json
from b_sentence_embedding import VectorCache,digest,write_json
from b_embedding_profiles import DEFAULT,readjl,csvfile

# These affect source eligibility/audit evidence, never the actual encoder call.
# Every other known OR unknown field must match, including template, artifacts,
# encoder code, dependencies, device, dtype, chunking, aggregation and cache root.
PROVENANCE_ONLY={'source_code_sha256','measured_length_audit_sha256','local_benchmark_sha256','contract_status'}
def operation(contract):return {k:v for k,v in contract.items() if k not in PROVENANCE_ONLY}
def import_exact(text,old,new):
 if operation(old.contract)!=operation(new.contract):raise ValueError('Encoder operation differs; cannot import successful vector')
 if new.get(text):return False
 record=old.get(text)
 if not record:return False
 metadata={**record['metadata'],'imported_from_contract_hash':digest(old.contract),'imported_from_cache_key':record['key'],'imported_from_checksum':record['checksum'],'reuse_basis':'identical actual input text and every encoder operation/configuration field; source audit provenance only changed'}
 new.put(text,record['vector'],metadata);return True

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=DEFAULT);ap.add_argument('--from-root',type=Path,action='append',required=True);a=ap.parse_args()
 newcontract=json.loads((a.root/'embedding_contract.json').read_text());new=VectorCache(newcontract['cache_root'],newcontract);records=readjl(a.root/'technical_records.jsonl');counts=[]
 for oldroot in a.from_root:
  oldcontract=json.loads((oldroot/'embedding_contract.json').read_text());old=VectorCache(oldcontract['cache_root'],oldcontract)
  if operation(oldcontract)!=operation(newcontract):raise ValueError('Encoder operation differs from '+str(oldroot))
  count=0
  for r in records:count+=import_exact(r['text'],old,new)
  counts.append({'old_root':str(oldroot),'old_contract_hash':digest(oldcontract),'new_contract_hash':digest(newcontract),'exact_text_vectors_imported':count})
 csvfile(a.root/'exact_cache_import_audit.csv',counts);print(json.dumps(counts,indent=2))
if __name__=='__main__':main()
