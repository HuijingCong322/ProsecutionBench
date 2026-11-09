"""Independent BGE-M3 shared-profile build, manifests and local review materials."""
from __future__ import annotations
import argparse,copy,csv,hashlib,html,json,re,time
from collections import Counter
from pathlib import Path
import b_sentence_sources as s
from b_sentence_embedding import MODEL_ID,REVISION,digest,write_json,select_top

DEFAULT=s.B/'outputs/profile_bgem3_v1_candidate_2026_11_05_r9'
RUNTIME=s.B/'outputs/embedding_runtime_bgem3'
PRECHECK=['13484627','13773735','14353039']

def new_output(root):
 root=Path(root)
 if root.exists():raise ValueError('New output directory required')
 root.mkdir(parents=True);return root

def jsonl(path,values):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(v,ensure_ascii=False,allow_nan=False)+'\n' for v in values))
def readjl(path):return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def csvfile(path,values):
 values=list(values);keys=list(dict.fromkeys(k for r in values for k in r));p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys or ['sample_id']);w.writeheader();w.writerows(values)

def quote(path,limit=380):
 p=Path(path);raw=p.read_text();start=0
 # Exact character spans: remove nothing inside the quote, no generated paraphrase.
 # Prefer substantive discussion over headings/contact material when available.
 for match in re.finditer(r'(?im)^.*(?:claims?\s+\d|applicants?\s+(?:ha|submit|argu)|this (?:office action|is in response)).*$',raw):
  if not re.search(r'directed to|whose telephone',match[0],re.I):start=match.start();break
 end=min(start+limit,len(raw))
 if end<len(raw) and ' ' in raw[start:end]:end=start+raw[start:end].rfind(' ')
 return {'path':str(p),'sha1':s.sha(p),'start_char':start,'end_char':end,'quote':raw[start:end],'clipped':end<len(raw),'source_date':p.name[:10],'transform':'exact_character_span_with_external_clipping_marker'}

def render_profile(old,cases,template,contract,query_hash):
 p=copy.deepcopy(old)
 for key in ['reviewed_candidate_file_sha1','review_authority','quarantined_episode_ids','C_proposed_statistics_text','review_quarantine_policy']:p.pop(key,None)
 p['retrieval_review_action']='new_embedding_selection_pending_review'
 p['retrieved_cases']=cases;p['retrieved_k']=len(cases)
 blocks=[]
 if len(cases)<3:blocks.append(f'Only {len(cases)} eligible distinct-application/family examples are supplied; report actual coverage.')
 for i,e in enumerate(cases,1):blocks.append(f'Example {i}: application {e["app_id"]} (other family).\n'+'\n'.join(e['summary_lines']))
 if not cases:blocks.append('No reviewed comparable example is supplied; do not infer a case-specific analogy from missing examples.')
 p['profile_text']=template.format(cutoff=p['cutoff'],D_verified_statistics_with_denominators=p['statistics_text'],three_retrieved_two_line_case_summaries_with_sources='\n'.join(blocks))
 p['profile_text_sha1']=hashlib.sha1(p['profile_text'].encode()).hexdigest();p['profile_block_sha1']=hashlib.sha1(template.encode()).hexdigest()
 p['schema_version']='B-shared-profile-bgem3-dense-v1';p['C_review_status']='pending_new_review';p['freeze_status']='candidate_not_frozen';p['retrieval_method']='BGE-M3 dense normalized cosine on dated technical title/abstract/claims; earliest eligible episode/application; deterministic distinct-family top3'
 p['embedding_contract_hash']=digest(contract);p['embedding_model_id']=contract['model_id'];p['embedding_revision']=contract['revision'];p['query_text_sha256']=query_hash
 p['profile_mode']='statistics_plus_retrieved_examples' if cases else 'statistics_only';p['query_sha1']=None
 p.pop('token_count',None);p.pop('token_count_upper_bound_utf8_bytes',None);p.pop('candidate_episode_n_before_review_quarantine',None)
 p['limitations']=[x for x in p.get('limitations',[]) if not any(z in x for z in ['New file hashes','Human review','Human review and team','C relevance quarantine','Original D card text'])]+['New embedding retrieval requires fresh source/relevance review; old C judgments do not approve these files.','Date-verified title may be absent; missing fields and historical claims versions are recorded.','Technical representation and encoder both differ from the old TF-IDF setting.']
 return p

def apply_relevance_gate(path,review,template,contract,query_hash):
 p=json.loads(Path(path).read_text())
 if s.sha(path)!=review['profile_sha1'] or p['profile_text_sha1']!=review['profile_text_sha1']:raise ValueError('Stale review hash')
 weak=set(filter(None,re.split(r'[;,]',review['weak_app_ids'])))
 if not weak.issubset({r['app_id'] for r in p['retrieved_cases']}):raise ValueError('Review references an unselected application')
 if review['verdict']=='needs_fix' and not weak:raise ValueError('Unresolved review failure')
 retained=[e for e in p['retrieved_cases'] if e['app_id'] not in weak]
 result=render_profile(p,retained,template,contract,query_hash)
 result['review_withheld_app_ids']=sorted(weak);result['ranking_candidate_profile_sha1']=review['profile_sha1'];result['ranking_candidate_profile_text_sha1']=review['profile_text_sha1']
 result['C_review_status']='fresh_technical_review_pass_with_limits_after_withholding' if weak else 'fresh_technical_review_pass_with_limits'
 result['review_authority']='Codex independent technical review; not a human D/C signature'
 result['retrieval_review_action']='weak_examples_withheld_without_replacements' if weak else 'new_embedding_examples_technically_reviewed_with_limits'
 return result

def prepare(root):
 root=new_output(root);c=s.Corpus();queries=[];mappings=[];exclusions=[];records={}
 for case in c.cases:
  q=c.targets.target(case)
  if not q['text']:raise ValueError('Target has no technical content')
  queries.append({'sample_id':case['sample_id'],'cutoff':case['cutoff'],'technical':q});records[q['text_sha256']]=q
  for variant in ['own','mismatched','artunit']:
   pool,excluded=c.pool(case,variant);exclusions.extend(excluded)
   for item in pool:
    record={'sample_id':case['sample_id'],'cutoff':case['cutoff'],'variant':variant,**item}
    mappings.append(record);records[item['technical']['text_sha256']]=item['technical']
  if len(queries)%20==0:print('source audit',len(queries),flush=True)
 jsonl(root/'queries.jsonl',queries);jsonl(root/'candidate_mapping.jsonl',mappings);jsonl(root/'technical_records.jsonl',records.values());csvfile(root/'candidate_exclusions.csv',exclusions)
 sources={r['path']:r for record in records.values() for r in record['fields'].values()}
 csvfile(root/'technical_source_manifest.csv',[{k:v for k,v in r.items() if k!='text'} for r in sources.values()])
 write_json(root/'cohorts.json',{'precheck':PRECHECK,'fixed_ten':c.fixed_review_ids,'precheck_replaces_fixed_ten':False,'former_weak_blocks':[['14482153','mismatched'],['13773735','mismatched'],['13773735','artunit'],['13577408','mismatched'],['13577408','artunit']]})
 report={'cases':len(queries),'candidate_application_rows':len(mappings),'unique_technical_texts':len(records),'source_files':len(sources),'field_presence':dict(Counter(k for r in records.values() for k in r['fields'])),'exclusion_reasons':dict(Counter(r['reason'] for r in exclusions)),'prediction_api_calls':0,'status':'sources_prepared_pending_encoder_and_review'}
 write_json(root/'source_audit.json',report);print(json.dumps(report,indent=2),flush=True)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['prepare','encode','build']);ap.add_argument('--root',type=Path,default=DEFAULT);ap.add_argument('--stage',choices=['precheck','fixed_ten','all'],default='precheck');a=ap.parse_args()
 if a.command=='prepare':prepare(a.root)
 elif a.command=='encode':encode_stage(a.root,a.stage)
 elif a.command=='build':build(a.root,a.stage)

def source_file(c,app,doc_id):
 folder=s.A/'apps'/app/'text'
 choices=list(folder.glob('*_'+doc_id+'.substantive.txt'))+list(folder.glob('*_'+doc_id+'.txt'))
 for p in choices:
  if p.read_text().strip():return p
 return None

def checked_summary_source(c,path,cutoff):
 path=Path(path);dt,code,doc=s.parse_record_filename(path.name,c.hist.catalog(path.parents[1].name))
 if dt>=cutoff:raise ValueError('Summary source date')
 relative=str(path.relative_to(s.A));expected=c.hist.manifest.get(relative)
 if not expected or s.sha(path)!=expected['sha1']:raise ValueError('Summary source hash')
 return {'path':str(path),'date':dt,'sha1':s.sha(path),'doc_code':code,'doc_id':doc}

def summary_case(c,item,score,rank,contract,query):
 e=item['episode'];r=item['case_episode'];app=e['app_id'];cutoff=r['cutoff'];sources=[];prior=[];replies=[];nexts=[]
 for doc in filter(None,e['prior_doc_ids'].split(';')):
  p=source_file(c,app,doc)
  if p:prior.append(p)
 for rel in filter(None,e['reply_text_paths'].split(';')):
  p=s.A/rel
  if p.exists() and p.read_text().strip():replies.append(p)
 for doc in filter(None,e['next_doc_ids'].split(';')):
  p=source_file(c,app,doc)
  if p:nexts.append(p)
 for p in dict.fromkeys(prior+replies+nexts):sources.append(checked_summary_source(c,p,cutoff))
 if any(x['date']>e['next_date'] for x in sources if Path(x['path']) in prior+replies):raise ValueError('Pre-outcome source after next notice')
 # Bind D outcome to original transaction record, independently of similarity.
 tr=s.A/'apps'/app/'transactions.csv';events=s.rows(tr)
 if not any(x['event_date']==e['next_date'] and x['event_code']==e['next_code'] for x in events):raise ValueError('D next transaction not found')
 if s.sha(tr)!=c.hist.manifest[str(tr.relative_to(s.A))]['sha1']:raise ValueError('Transaction hash mismatch')
 rp=next(iter(sorted(replies,key=lambda p:('_REM_' not in p.name,p.name))),None);np=next(iter(nexts),None)
 rq=quote(rp) if rp else None;nq=quote(np) if np else None
 reply=f'Reply recorded {e["reply_date"]} [transaction {e["reply_codes"]}]. '
 reply+=('Exact source excerpt: '+rq['quote']+(' [...]' if rq['clipped'] else '')) if rq else 'No readable reply body is supplied; its arguments or strategy are unknown.'
 attrib='examiner of record verified (contact paragraph; may be co-signed by a primary/SPE)' if e['signature_basis']=='actions_csv_verified' else 'application-assignment attribution only; handling examiner not verified from a contact paragraph'
 nxt=f'Next recorded communication {e["next_date"]}: {e["next_type"]}; {e["next_days"]} days after reply; {attrib}.'
 if nq:nxt+=' Exact source excerpt: '+nq['quote']+(' [...]' if nq['clipped'] else '')
 else:nxt+=' Notice text unavailable; only recorded event type and date are supported.'
 technical=item['technical']
 return {'episode_id':e['episode_id'],'app_id':app,'historical_app_id':app,'family_root':e['family_root'],'family_id':e['family_root'],'examiner_id':e['examiner_id'],'prior_date':e['prior_date'],'reply_date':e['reply_date'],'next_date':e['next_date'],'next_type':e['next_type'],'elapsed_days':int(e['next_days']),'signature_basis':e['signature_basis'],'physical_signatory_verified':False,'reply_text_status':'available' if rq else 'unavailable','similarity':score,'rank':rank,'source_dates':sorted(set(x['date'] for x in sources)|{e['prior_date'],e['reply_date'],e['next_date']}),'source_paths':[x['path'] for x in sources],'source_sha1':{x['path']:x['sha1'] for x in sources},'summary_sources':sources,'evidence':{'reply':rq,'next':nq,'next_transaction':{'path':str(tr),'sha1':s.sha(tr),'event_date':e['next_date'],'event_code':e['next_code']}},'summary_lines':[reply,nxt],'technical_sources':[{k:v for k,v in x.items() if k!='text'} for x in technical['fields'].values()],'technical_text_sha256':technical['text_sha256'],'query_text_sha256':query['text_sha256'],'missing_technical_fields':technical['missing_fields'],'model_id':contract['model_id'],'model_revision':contract['revision'],'embedding_contract_hash':digest(contract),'summary_method':'exact_source_character_spans_and_D_transaction_v1'}

def build(root,stage):
 from b_sentence_embedding import VectorCache
 root=Path(root);contract=json.loads((root/'embedding_contract.json').read_text());cache=VectorCache(Path(contract['cache_root']),contract)
 if (contract['model_id'],contract['revision'])!=(MODEL_ID,REVISION):raise ValueError('Unsupported model/revision for profile build')
 c=s.Corpus();queries={r['sample_id']:r for r in readjl(root/'queries.jsonl')};mapping=readjl(root/'candidate_mapping.jsonl');cohorts=json.loads((root/'cohorts.json').read_text());ids=cohorts[stage] if stage in ['precheck','fixed_ten'] else list(queries)
 out=root/(stage if stage in ['precheck','fixed_ten'] else 'shared_candidate');new_output(out)
 template=(s.RELEASE/'prompts/profile_block.txt').read_text();(out/'prompts').mkdir();(out/'prompts/profile_block.txt').write_text(template)
 manifests=[];links=[];diffs=[];rankings=[];profiles=[]
 for sid in ids:
  q=queries[sid]['technical'];qcache=cache.get(q['text'])
  if not qcache:raise ValueError('Missing target embedding '+sid)
  for variant in ['own','mismatched','artunit']:
   candidates=[x for x in mapping if x['sample_id']==sid and x['variant']==variant];scored=[];lookup={}
   for item in candidates:
    dcache=cache.get(item['technical']['text'])
    if not dcache:raise ValueError('Missing candidate embedding')
    score=sum(a*b for a,b in zip(qcache['vector'],dcache['vector']));e=item['episode'];r={'app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'score':score};scored.append(r);lookup[e['episode_id']]=item
   selected=select_top(scored);oldpath=s.RELEASE/'candidate_profiles'/variant/f'{sid}.json';old=json.loads(oldpath.read_text())
   examples=[summary_case(c,lookup[x['episode_id']],x['score'],i,contract,q) for i,x in enumerate(selected,1)]
   p=render_profile(old,examples,template,contract,q['text_sha256']);p['previous_locked_profile_sha1']=s.sha(oldpath);p['candidate_episode_n']=len(candidates)
   # No stale review/metadata is represented as approval of this new retrieval.
   p['statistics_confirmation_status']=old['statistics_confirmation_status'];p['review_authority']='new_review_pending; historical review authority applies only to locked old snapshot'
   rel=f'candidate_profiles/{variant}/{sid}.json';path=out/rel;write_json(path,p);profiles.append(p)
   manifests.append({'sample_id':sid,'cutoff':p['cutoff'],'variant':variant,'setting':variant,'profile_path':rel,'profile_sha1':s.sha(path),'profile_text_sha1':p['profile_text_sha1'],'card_sha1':p['card_sha1'],'D_card_sha1':p['D_card_sha1'],'retrieved_k':len(examples),'candidate_application_n':len(candidates),'model_id':MODEL_ID,'model_revision':REVISION,'embedding_contract_hash':digest(contract),'review_status':'pending_new_review'})
   for rank,x in enumerate(sorted(scored,key=lambda x:(-x['score'],x['app_id'],x['family_id'],x['episode_id'])),1):rankings.append({'sample_id':sid,'cutoff':p['cutoff'],'variant':variant,'application_rank':rank,**x})
   for e in examples:
    links.append({'sample_id':sid,'cutoff':p['cutoff'],'variant':variant,'historical_app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'rank':e['rank'],'similarity':e['similarity'],'model_id':MODEL_ID,'model_revision':REVISION,'text_sha256':e['technical_text_sha256'],'query_text_sha256':q['text_sha256'],'source_paths':json.dumps([x['path'] for x in e['technical_sources']]),'source_sha1':json.dumps({x['path']:x['sha1'] for x in e['technical_sources']}),'summary_source_paths':json.dumps(e['source_paths']),'profile_path':rel,'profile_sha1':s.sha(path),'profile_text_sha1':p['profile_text_sha1'],'card_sha1':p['card_sha1']})
   previous=[e['app_id'] for e in old['retrieved_cases']];current=[e['app_id'] for e in examples]
   diffs.append({'sample_id':sid,'variant':variant,'old_k':old['retrieved_k'],'new_k':len(examples),'old_app_ids':';'.join(previous),'new_app_ids':';'.join(current),'old_episode_ids':';'.join(e['episode_id'] for e in old['retrieved_cases']),'new_episode_ids':';'.join(e['episode_id'] for e in examples),'old_similarities':json.dumps([e['similarity'] for e in old['retrieved_cases']]),'new_similarities':json.dumps([e['similarity'] for e in examples]),'old_method':'legacy_OA_reply_TFIDF','new_method':'dated_technical_BGE_M3_dense','overlap_apps':len(set(previous)&set(current)),'same_order':previous==current,'old_relevance_status':old.get('retrieval_review_action'),'new_review_status':'pending'})
 csvfile(out/'profile_manifest.csv',manifests);csvfile(out/'historical_links.csv',links);csvfile(out/'old_vs_new_topk.csv',diffs);csvfile(out/'full_ranking.csv',rankings)
 write_json(out/'build_summary.json',{'stage':stage,'profiles':len(profiles),'actual_k_counts':dict(Counter(p['retrieved_k'] for p in profiles)),'model_id':MODEL_ID,'model_revision':REVISION,'prediction_api_calls':0,'review_status':'pending_new_review','new_vs_old_representation_and_encoder_changed':True})
 print('built',out,len(profiles),flush=True)
 return out

def encode_stage(root,stage):
 from b_sentence_embedding import DenseEncoder,cache_key
 root=Path(root);contract=json.loads((root/'embedding_contract.json').read_text());cohorts=json.loads((root/'cohorts.json').read_text())
 if stage!='precheck':
  gate=json.loads((root/'precheck/PRECHECK_ACCEPTED.json').read_text())
  for row in gate['profiles']:
   if s.sha(root/'precheck'/row['profile_path'])!=row['profile_sha1']:raise ValueError('Precheck gate profile changed')
  if gate['cases']!=cohorts['precheck'] or not gate['workflow_approved_for_expansion']:raise ValueError('Precheck gate missing')
 ids=set(cohorts[stage]) if stage in ['precheck','fixed_ten'] else None
 records={}
 for q in readjl(root/'queries.jsonl'):
  if ids is None or q['sample_id'] in ids:records[q['technical']['text_sha256']]=q['technical']
 for item in readjl(root/'candidate_mapping.jsonl'):
  if ids is None or item['sample_id'] in ids:records[item['technical']['text_sha256']]=item['technical']
 encoder=DenseEncoder(RUNTIME/'model',contract,contract['cache_root']);journal=root/f'encoding_journal_{stage}.jsonl';start=time.perf_counter();manifest=[]
 for i,(h,record) in enumerate(sorted(records.items()),1):
  if s.textsha(record['text'])!=h:raise ValueError('Prepared technical representation text/hash mismatch')
  try:cached=encoder.encode(record['text'])
  except Exception as error:
   with journal.open('a') as f:f.write(json.dumps({'text_sha256':h,'status':'failed','error':str(error)})+'\n')
   raise
  m={'text_sha256':h,'cache_key':cached['key'],'cache_path':str(Path(contract['cache_root'])/(cached['key']+'.json')),'cache_checksum':cached['checksum'],'contract_hash':digest(contract),'model_revision':REVISION,**cached['metadata']};manifest.append(m)
  with journal.open('a') as f:f.write(json.dumps({'text_sha256':h,'status':'success','cache_key':cached['key']})+'\n')
  if i%25==0 or i==len(records):print(f'encoded {i}/{len(records)}; new={encoder.computed}, reused={encoder.reused}; elapsed={time.perf_counter()-start:.1f}s',flush=True)
 csvfile(root/f'embedding_cache_manifest_{stage}.csv',manifest)
 write_json(root/f'encoding_summary_{stage}.json',{'texts':len(records),'computed':encoder.computed,'reused':encoder.reused,'elapsed_seconds':time.perf_counter()-start,'failures':0,'prediction_api_calls':0,'model_id':MODEL_ID,'revision':REVISION,'contract_hash':digest(contract)})

if __name__=='__main__':main()
