"""Fresh file-bound technical audit and readable review packs; no human signoff claims."""
from __future__ import annotations
import argparse,html,json,hashlib,math
from collections import Counter
from pathlib import Path
import b_sentence_sources as s
from b_embedding_profiles import readjl,csvfile,write_json,DEFAULT
from b_sentence_embedding import digest,VectorCache,cache_key,select_top,MODEL_ID,REVISION

def verify_quote(q,cutoff):
 p=Path(q['path']);raw=p.read_text()
 if not q['source_date']<cutoff:raise ValueError('Quote source date')
 if s.sha(p)!=q['sha1']:raise ValueError('Quote source hash')
 if raw[q['start_char']:q['end_char']]!=q['quote']:raise ValueError('Quote source span mismatch')

def validate(root,stage='shared_candidate'):
 root=Path(root);out=root/stage;c=s.Corpus();manifest=s.rows(out/'profile_manifest.csv');contract=json.loads((root/'embedding_contract.json').read_text());cache=VectorCache(contract['cache_root'],contract)
 queries={r['sample_id']:r['technical'] for r in readjl(root/'queries.jsonl')};mapping={(r['sample_id'],r['variant'],r['episode']['episode_id']):r for r in readjl(root/'candidate_mapping.jsonl')};checks=[];all_sources=set();spans=0
 if (contract['model_id'],contract['revision'])!=(MODEL_ID,REVISION):raise ValueError('Unapproved model/revision')
 for row in manifest:
  sid=row['sample_id'];v=row['variant'];path=out/row['profile_path'];p=json.loads(path.read_text());old=json.loads((s.RELEASE/'candidate_profiles'/v/f'{sid}.json').read_text());case=next(x for x in c.cases if x['sample_id']==sid);card=c.cards[sid,v]
  if s.sha(path)!=row['profile_sha1'] or hashlib.sha1(p['profile_text'].encode()).hexdigest()!=row['profile_text_sha1']:raise ValueError('Profile file/text manifest hash')
  if p['profile_text_sha1']!=row['profile_text_sha1'] or p['embedding_contract_hash']!=digest(contract):raise ValueError('Profile contract hash')
  if p['cutoff']!=case['cutoff'] or p['target_examiner_id']!=case['examiner_id']:raise ValueError('A target identity/cutoff')
  for field in ['statistics','shrunk_statistics','D_original_card_text','D_card_sha1','card_sha1','statistics_text','statistics_text_sha1']:
   if p[field]!=old[field]:raise ValueError('Frozen D/statistics rendering changed: '+field)
  if p['card_sha1']!=card['card_sha1'] or p['statistics']!=card['stats']:raise ValueError('D original card mismatch')
  if len(p['retrieved_cases'])!=int(row['retrieved_k']) or p['retrieved_k']!=int(row['retrieved_k']):raise ValueError('Actual k mismatch')
  q=queries[sid];qcache=cache.get(q['text'])
  if s.textsha(q['text'])!=q['text_sha256']:raise ValueError('Query representation text/hash mismatch')
  if not qcache:raise ValueError('Query cache missing')
  if c.targets.target(case)['text_sha256']!=q['text_sha256']:raise ValueError('Stale target technical representation')
  live_pool,_=c.pool(case,v)
  live={(r['episode']['episode_id'],r['technical']['text_sha256']) for r in live_pool}
  saved={(eid,r['technical']['text_sha256']) for (sample,variant,eid),r in mapping.items() if (sample,variant)==(sid,v)}
  if live!=saved:raise ValueError('Stale/ineligible D application-episode mapping')
  scored=[]
  for candidate in live_pool:
   doc=cache.get(candidate['technical']['text'])
   if not doc:raise ValueError('Eligible candidate cache missing')
   e=candidate['episode'];scored.append({'app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'score':sum(a*b for a,b in zip(qcache['vector'],doc['vector']))})
  if [r['episode_id'] for r in select_top(scored)]!=[r['episode_id'] for r in p['retrieved_cases']]:raise ValueError('Incorrect deterministic top3')
  for source in q['fields'].values():
   if source['date']>p['cutoff'] or s.sha(source['path'])!=source['sha1']:raise ValueError('Target technical source date/hash')
  apps=set();families=set();texts=[]
  for e in p['retrieved_cases']:
   item=mapping[sid,v,e['episode_id']];tech=item['technical'];master=item['episode'];app=e['app_id'];family=e['family_root']
   if s.textsha(tech['text'])!=tech['text_sha256']:raise ValueError('Document representation text/hash mismatch')
   if app in apps or family in families or app in c.bench_apps or family in c.bench_families:raise ValueError('Duplicate/benchmark family')
   apps.add(app);families.add(family)
   if master['prior_signed']=='false' or master['next_signed']=='false' or not s.flag(item['case_episode']['next_signed_ok']):raise ValueError('Other-examiner action')
   if any(x>=p['cutoff'] for x in e['source_dates']):raise ValueError('Summary dates')
   for x in tech['fields'].values():
    if not s.date_allowed(x['date'],master['reply_date'],p['cutoff']):raise ValueError('Technical version date')
    if s.sha(x['path'])!=x['sha1'] or s.textsha(s.read_technical(x['path']))!=x['text_sha256']:raise ValueError('Technical file/text hash')
    all_sources.add(x['path'])
   dcache=cache.get(tech['text'])
   if not dcache:raise ValueError('Document cache missing')
   score=sum(a*b for a,b in zip(qcache['vector'],dcache['vector']))
   if not math.isfinite(score) or abs(score-e['similarity'])>1e-12:raise ValueError('Cosine score mismatch')
   if e['technical_text_sha256']!=tech['text_sha256'] or e['model_revision']!=contract['revision']:raise ValueError('Link text/model mismatch')
   if e['technical_sources']!=[{k:v for k,v in x.items() if k!='text'} for x in tech['fields'].values()]:raise ValueError('Displayed technical-source link mismatch')
   if e['query_text_sha256']!=q['text_sha256']:raise ValueError('Displayed query text hash mismatch')
   for qspan in [e['evidence']['reply'],e['evidence']['next']]:
    if qspan:verify_quote(qspan,p['cutoff']);spans+=1
   for x in e['summary_sources']:
    if s.sha(x['path'])!=x['sha1'] or x['date']>=p['cutoff']:raise ValueError('Summary source changed')
    all_sources.add(x['path'])
   if not e['evidence']['reply'] and 'arguments or strategy are unknown' not in e['summary_lines'][0]:raise ValueError('Missing reply qualification')
   texts.extend(e['summary_lines'])
  # Only visible profile_text is a downstream model field; no control names or examiner hashes.
  import re
  if re.search(r'\bex_[a-f0-9]{10}\b|mismatched|wrong examiner',p['profile_text'],re.I):raise ValueError('Control/identity metadata in model text')
  checks.append({'sample_id':sid,'variant':v,'profile_sha1':row['profile_sha1'],'profile_text_sha1':row['profile_text_sha1'],'card_sha1':row['card_sha1'],'dates_ok':True,'identity_ok':'A/D_handling_examiner_with_assignment_and_fallback_limits','families_ok':'pass_with_A_family_scope_limit','sources_ok':True,'summary_spans_faithful':True,'cosine_cache_ok':True,'retrieved_k':p['retrieved_k'],'relevance_review':'separate_fixed_cohort_review'})
 csvfile(out/'automatic_profile_checks.csv',checks)
 result={'status':'PASS_WITH_DOCUMENTED_LIMITS','profiles_checked':len(checks),'source_files_checked':len(all_sources),'exact_summary_spans_checked':spans,'card_values_and_display_preserved':True,'k_counts':dict(Counter(r['retrieved_k'] for r in checks)),'prediction_api_calls':0,'relevance_review':'not_implied_by_automatic_checks','limitations':['A supplied family-root coverage is not exhaustive','Handling examiner may be co-signed; assignment-only notices remain unverified','14353039 target identity fallback remains','Missing date-verified titles and missing/older readable claims are explicit','Approximate ground labels, missing reply bodies and censored tails remain']}
 write_json(out/'automatic_validation.json',result);return result

def render_review(root,stage,cohort):
 root=Path(root);out=root/stage
 # Fresh validation is required; never print automatic_pass from an absent/stale report.
 validate(root,stage)
 cohorts=json.loads((root/'cohorts.json').read_text());ids=cohorts['precheck' if cohort=='precheck' else 'fixed_ten'];queries={r['sample_id']:r['technical'] for r in readjl(root/'queries.jsonl')};mapping={(r['sample_id'],r['variant'],r['episode']['episode_id']):r for r in readjl(root/'candidate_mapping.jsonl')}
 review=out/'review'/cohort;review.mkdir(parents=True,exist_ok=True);queue=[];display=[];index=[]
 for sid in ids:
  for variant in ['own','mismatched','artunit']:
   path=out/'candidate_profiles'/variant/f'{sid}.json';p=json.loads(path.read_text());q=queries[sid];parts=[f'<h1>{sid} / {variant}</h1><p>Cutoff {p["cutoff"]}; actual k={p["retrieved_k"]}. Fresh technical review; no human C/D signature.</p>',f'<h2>Target technical representation</h2><pre>{html.escape(q["text"])}</pre>']
   parts.append('<p>Target sources: '+html.escape(json.dumps([{k:v for k,v in r.items() if k!='text'} for r in q['fields'].values()],ensure_ascii=False))+'</p>')
   compact={'sample_id':sid,'variant':variant,'cutoff':p['cutoff'],'profile_sha1':s.sha(path),'profile_text_sha1':p['profile_text_sha1'],'target_text':q['text'],'target_fields':list(q['fields']),'selected':[]}
   for e in p['retrieved_cases']:
    tech=mapping[sid,variant,e['episode_id']]['technical'];parts.append(f'<h2>Rank {e["rank"]}: {e["app_id"]} / cosine {e["similarity"]:.6f}</h2><pre>{html.escape(tech["text"])}</pre><p>{html.escape(json.dumps(e["technical_sources"],ensure_ascii=False))}</p><h3>Displayed history</h3><pre>{html.escape(chr(10).join(e["summary_lines"]))}</pre>')
    for label in ['reply','next']:
     proof=e['evidence'][label]
     if proof:parts.append(f'<details><summary>{label} source: {html.escape(proof["path"])}</summary><pre>{html.escape(Path(proof["path"]).read_text())}</pre></details>')
    compact['selected'].append({'rank':e['rank'],'app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'score':e['similarity'],'technical_text':tech['text'],'missing_fields':tech['missing_fields'],'summary_lines':e['summary_lines'],'technical_sources':e['technical_sources'],'evidence':e['evidence']})
   parts.append('<h2>Exact downstream profile_text</h2><pre>'+html.escape(p['profile_text'])+'</pre>')
   page='<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;margin:36px;max-width:1100px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:16px}details{margin:16px 0}h2{margin-top:36px}</style>'+''.join(parts)
   filename=f'{sid}_{variant}.html';(review/filename).write_text(page);index.append(f'<li><a href="{filename}">{sid} / {variant}</a></li>');display.append(compact)
   queue.append({'sample_id':sid,'variant':variant,'profile_path':str(path),'profile_sha1':s.sha(path),'profile_text_sha1':p['profile_text_sha1'],'dates':'automatic_pass','identity':'automatic_pass_with_limits','family':'automatic_pass_with_limits','source_fidelity':'automatic_exact_spans_pass','semantic_relevance':'pending','reviewer':'','human_D_C_signoff_claimed':False,'notes':''})
 (review/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>'+cohort+' fixed review</h1><ul>'+''.join(index)+'</ul>');csvfile(review/'review_queue.csv',queue);jsonl=__import__('b_embedding_profiles').jsonl;jsonl(review/'display_records.jsonl',display)
 return {'cohort':cohort,'cases':len(ids),'variants':len(queue),'index':str(review/'index.html')}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('command',choices=['validate','review']);ap.add_argument('--root',type=Path,default=DEFAULT);ap.add_argument('--stage',default='shared_candidate');ap.add_argument('--cohort',choices=['precheck','fixed_ten'],default='fixed_ten');a=ap.parse_args()
 print(json.dumps(validate(a.root,a.stage) if a.command=='validate' else render_review(a.root,a.stage,a.cohort),indent=2))
if __name__=='__main__':main()
