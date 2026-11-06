"""Private, review-gated shared profile snapshot. No prediction runner or upload."""
from __future__ import annotations
import argparse,copy,csv,json,hashlib,shutil,zipfile
from collections import Counter
from pathlib import Path
import b_sentence_sources as s
from b_sentence_embedding import digest,write_json
from b_embedding_profiles import DEFAULT,readjl,jsonl,csvfile,new_output,apply_relevance_gate,render_profile
from b_embedding_review import validate,verify_quote

DEST=s.B/'outputs/profile_bgem3_v1_shared_2026_11_05'

def require_review_cohort(reviews,ids):
 expected={(sid,v) for sid in ids for v in ['own','mismatched','artunit']};keys=[(r['sample_id'],r['variant']) for r in reviews]
 if len(keys)!=len(set(keys)) or set(keys)!=expected:raise ValueError('Original fixed review cohort mismatch')

def handoff(root=DEFAULT,dest=DEST):
 root=Path(root);dest=Path(dest);raw=root/'shared_candidate';validate(root)
 contract=json.loads((root/'embedding_contract.json').read_text());cohorts=json.loads((root/'cohorts.json').read_text());query={r['sample_id']:r['technical'] for r in readjl(root/'queries.jsonl')}
 reviewpath=root/'fixed_ten/review/fixed_ten/independent_semantic_review.csv';reviews=s.rows(reviewpath);require_review_cohort(reviews,cohorts['fixed_ten']);review={(r['sample_id'],r['variant']):r for r in reviews}
 for r in reviews:
  path=raw/'candidate_profiles'/r['variant']/f'{r["sample_id"]}.json';p=json.loads(path.read_text())
  if s.sha(path)!=r['profile_sha1'] or p['profile_text_sha1']!=r['profile_text_sha1']:raise ValueError('Fixed-ten review does not bind full candidate file')
  if r['verdict'] not in ['pass_with_limits','needs_fix']:raise ValueError('Incomplete relevance review')
 dest=new_output(dest);template=(raw/'prompts/profile_block.txt').read_text();(dest/'prompts').mkdir();(dest/'prompts/profile_block.txt').write_text(template)
 manifest=[];links=[];postreview=[];withheld=[];lengths=[];final_checks=[]
 for row in s.rows(raw/'profile_manifest.csv'):
  sid=row['sample_id'];variant=row['variant'];path=raw/row['profile_path'];candidate=json.loads(path.read_text());key=(sid,variant)
  if key in review:
   p=apply_relevance_gate(path,review[key],template,contract,query[sid]['text_sha256'])
  else:
   p=copy.deepcopy(candidate);p['C_review_status']='automatic_checks_passed_not_in_fixed_ten_review';p['review_authority']='automatic source/identity/family/hash checks; not a manual or human D/C signoff';p['review_withheld_app_ids']=[]
  p['freeze_status']='locked_shared_profile_bgem3_v1';p['review_protocol']='3-case technical precheck, then original fixed 10 cases/all 30 variants; all profiles automatic checks'
  p.pop('tokenizer',None) # Old profile-length tokenizer is not the embedding tokenizer.
  for rendered_rank,e in enumerate(p['retrieved_cases'],1):e['rendered_rank']=rendered_rank
  out=dest/row['profile_path'];write_json(out,p)
  m={**row,'profile_sha1':s.sha(out),'profile_text_sha1':p['profile_text_sha1'],'retrieved_k':p['retrieved_k'],'raw_ranking_k':candidate['retrieved_k'],'review_status':p['C_review_status'],'candidate_profile_sha1':s.sha(path),'withheld_app_ids':';'.join(p['review_withheld_app_ids'])};manifest.append(m)
  # Check body rendering and immutable data independently of review metadata.
  rendered=render_profile(p,p['retrieved_cases'],template,contract,query[sid]['text_sha256'])
  if rendered['profile_text']!=p['profile_text']:raise ValueError('Effective profile body mismatch')
  for field in ['statistics','shrunk_statistics','statistics_text','statistics_text_sha1','D_original_card_text','card_sha1','D_card_sha1']:
   if p[field]!=candidate[field]:raise ValueError('Statistics changed during review gate')
  retained=[e['episode_id'] for e in p['retrieved_cases']]
  expected=[e['episode_id'] for e in candidate['retrieved_cases'] if e['app_id'] not in p['review_withheld_app_ids']]
  if retained!=expected:raise ValueError('Review gate added/reordered an example')
  if len(p['profile_text'].encode())>8000:raise ValueError('Conservative profile size bound exceeded')
  for position,e in enumerate(p['retrieved_cases'],1):
   for q in [e['evidence']['reply'],e['evidence']['next']]:
    if q:verify_quote(q,p['cutoff'])
   links.append({'sample_id':sid,'cutoff':p['cutoff'],'variant':variant,'historical_app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'rank':e['rank'],'rendered_rank':position,'similarity':e['similarity'],'model_id':contract['model_id'],'model_revision':contract['revision'],'text_sha256':e['technical_text_sha256'],'query_text_sha256':query[sid]['text_sha256'],'source_paths':json.dumps([x['path'] for x in e['technical_sources']]),'source_relative_paths':json.dumps([x['relative_path'] for x in e['technical_sources']]),'source_sha1':json.dumps({x['relative_path']:x['sha1'] for x in e['technical_sources']}),'summary_source_paths':json.dumps(e['source_paths']),'profile_path':row['profile_path'],'profile_sha1':m['profile_sha1'],'profile_text_sha1':m['profile_text_sha1'],'card_sha1':p['card_sha1'],'retrieval_review_status':p['C_review_status']})
  if key in review:
   postreview.append({'sample_id':sid,'variant':variant,'reviewer':review[key]['reviewer'],'candidate_profile_sha1':s.sha(path),'candidate_profile_text_sha1':candidate['profile_text_sha1'],'final_profile_sha1':s.sha(out),'final_profile_text_sha1':p['profile_text_sha1'],'retained_app_ids':';'.join(e['app_id'] for e in p['retrieved_cases']),'withheld_app_ids':';'.join(p['review_withheld_app_ids']),'raw_verdict':review[key]['verdict'],'final_disposition':'qualified_retained_subset_only' if p['retrieved_k'] else 'statistics_only_no_approved_comparable','notes':review[key]['notes'],'human_D_C_signoff_claimed':False})
  for e in candidate['retrieved_cases']:
   if e['app_id'] in p['review_withheld_app_ids']:withheld.append({'sample_id':sid,'variant':variant,'historical_app_id':e['app_id'],'episode_id':e['episode_id'],'raw_rank':e['rank'],'similarity':e['similarity'],'reason':'fresh_fixed_ten_technical_relevance_failure_no_replacement','review_notes':review[key]['notes']})
  lengths.append({'sample_id':sid,'variant':variant,'utf8_bytes':len(p['profile_text'].encode()),'characters':len(p['profile_text'])})
  final_checks.append({'sample_id':sid,'variant':variant,'profile_path':row['profile_path'],'profile_sha1':m['profile_sha1'],'profile_text_sha1':m['profile_text_sha1'],'card_sha1':p['card_sha1'],'retrieved_k':p['retrieved_k'],'raw_candidate_profile_sha1':s.sha(path),'source_identity_family_date_checks':'inherited_by_verified_ordered_subset_of_freshly_revalidated_candidate','statistics_unchanged':True,'body_rendering_verified':True,'no_replacement_or_reordering':True,'fresh_relevance_review':key in review})
 if len(manifest)!=300:raise ValueError('Expected all 300 shared profiles')
 csvfile(dest/'profile_manifest.csv',manifest);csvfile(dest/'historical_links.csv',links);csvfile(dest/'review_withheld_examples.csv',withheld);csvfile(dest/'fixed_ten_final_review.csv',postreview);csvfile(dest/'profile_lengths_independent.csv',lengths)
 csvfile(dest/'automatic_profile_checks.csv',final_checks)
 write_json(dest/'automatic_validation.json',{'status':'PASS_WITH_DOCUMENTED_LIMITS','profiles_checked':len(final_checks),'report_applies_to':'final review-gated handoff files and hashes','all_final_files_texts_cards_checked':True,'effective_k_counts':dict(Counter(r['retrieved_k'] for r in manifest)),'underlying_source_pool_and_raw_top3_revalidated':True,'review_action':'only recorded weak raw-top3 examples removed; no new source/example added','manual_semantic_review_cases':len(cohorts['fixed_ten']),'all_profiles_manually_reviewed':False,'human_D_C_signoff_claimed':False})
 for source in ['embedding_contract.json','technical_source_manifest.csv','technical_field_exclusion_audit.csv','source_audit.json','length_audit.json','rendering_noise_audit.json','technical_quality_audit.json','source_manifest_coverage_audit.json','episode_interval_audit.json','exact_cache_import_audit.csv','cache_completeness_audit.json','embedding_cache_manifest_verified.csv','old_snapshot_preservation_audit.json','local_runtime_benchmark.json','cohorts.json','embedding_cache_manifest_all.csv','encoding_summary_all.json']:
  shutil.copy2(root/source,dest/source)
 for source in ['old_vs_new_topk.csv','full_ranking.csv']:
  shutil.copy2(raw/source,dest/source)
 effective=[]
 for difference in s.rows(raw/'old_vs_new_topk.csv'):
  p=json.loads((dest/'candidate_profiles'/difference['variant']/f'{difference["sample_id"]}.json').read_text())
  effective.append({**difference,'new_effective_k':p['retrieved_k'],'new_effective_app_ids':';'.join(e['app_id'] for e in p['retrieved_cases']),'new_effective_episode_ids':';'.join(e['episode_id'] for e in p['retrieved_cases']),'new_effective_similarities':json.dumps([e['similarity'] for e in p['retrieved_cases']]),'withheld_app_ids':';'.join(p['review_withheld_app_ids']),'effective_review_status':p['C_review_status']})
 csvfile(dest/'old_vs_new_effective_retrieval.csv',effective)
 for source in ['automatic_profile_checks.csv','automatic_validation.json']:shutil.copy2(raw/source,dest/('raw_candidate_'+source))
 shutil.copy2(raw/'historical_links.csv',dest/'ranking_top3_links_before_review.csv')
 shutil.copytree(root/'fixed_ten/review/fixed_ten',dest/'review/fixed_ten')
 shutil.copytree(root/'precheck/review/precheck',dest/'review/precheck')
 shutil.copy2(root/'precheck/PRECHECK_ACCEPTED.json',dest/'review/PRECHECK_ACCEPTED.json')
 write_json(dest/'SOURCE_ROOTS.json',{'A_profile_corpus':str(s.A),'target_data_package':str(s.T),'D_episode_and_cards':str(s.D),'old_locked_release':str(s.RELEASE),'embedding_cache':contract['cache_root'],'path_remapping':'historical_links source_relative_paths and technical_source_manifest relative_path are portable; resolve against A or target source roots'})
 shutil.copy2(root/'queries.jsonl',dest/'queries.jsonl');shutil.copy2(root/'technical_records.jsonl',dest/'technical_records.jsonl');shutil.copy2(root/'source_flag_semantics.json',dest/'source_flag_semantics.json')
 mapping=[]
 for item in readjl(root/'candidate_mapping.jsonl'):
  e=item['episode'];tech=item['technical'];mapping.append({'sample_id':item['sample_id'],'cutoff':item['cutoff'],'variant':item['variant'],'historical_app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'technical_anchor_date':e['reply_date'],'technical_text_sha256':tech['text_sha256'],'missing_fields':';'.join(tech['missing_fields']),'source_paths':json.dumps([x['relative_path'] for x in tech['fields'].values()])})
 csvfile(dest/'application_episode_mapping.csv',mapping)
 portable=[]
 for source in s.rows(root/'technical_source_manifest.csv'):
  portable.append({'source_root_alias':'A_profile_corpus' if Path(source['path']).is_relative_to(s.A) else 'target_data_package',**source})
 csvfile(dest/'technical_source_manifest_portable.csv',portable)
 summary={'release_id':'B_shared_BGE_M3_dense_v1_2026_11_05','profiles':len(manifest),'raw_k_counts':dict(Counter(r['raw_ranking_k'] for r in manifest)),'effective_k_counts':dict(Counter(r['retrieved_k'] for r in manifest)),'profiles_with_withheld_examples':sum(bool(r['withheld_app_ids']) for r in manifest),'withheld_example_count':len(withheld),'fixed_review_cases':cohorts['fixed_ten'],'fixed_review_rows':len(postreview),'all_profiles_automatic_checked':True,'all_profiles_manually_reviewed':False,'reviewer':'Codex technical reviews; no human D/C signature claimed','selection_rule':'raw cosine top3 retained; only specifically reviewed weak top3 examples withheld, no replacement or re-ranking','prediction_api_calls':0,'raw_candidate_root':str(raw),'contract_hash':digest(contract),'model_id':contract['model_id'],'model_revision':contract['revision'],'old_locked_snapshot_modified':False,'downstream_scope':'shared profiles only; no B predictions launched','limitations':['Missing dated titles and incomplete/OCR/figure content remain qualified','A family-root coverage, identity fallback and assignment-only attribution remain','Semantic review covers original fixed ten, not all 300 profiles','Both representation and encoder changed relative to old TF-IDF; no encoder-only gain claim']}
 write_json(dest/'RELEASE_MANIFEST.json',summary);return dest,summary

def verify_final_files(dest):
 dest=Path(dest);manifest=s.rows(dest/'profile_manifest.csv');release=json.loads((dest/'RELEASE_MANIFEST.json').read_text())
 if len(manifest)!=release['profiles']:raise ValueError('Incomplete final profile manifest')
 for r in manifest:
  path=(dest/r['profile_path']).resolve()
  if not path.is_relative_to(dest.resolve()) or s.sha(path)!=r['profile_sha1']:raise ValueError('Changed final profile file')
  p=json.loads(path.read_text());h=hashlib.sha1(p['profile_text'].encode()).hexdigest()
  if h!=r['profile_text_sha1'] or h!=p['profile_text_sha1'] or len(p['retrieved_cases'])!=int(r['retrieved_k']) or p['retrieved_k']!=int(r['retrieved_k']) or p['card_sha1']!=r['card_sha1']:raise ValueError('Changed final profile body/k/card')
 return len(manifest)

def seal(dest):
 dest=Path(dest);archive=dest.parent/(dest.name+'_TEAM_ONLY.zip')
 if (dest/'HANDOFF_MANIFEST_SHA256.json').exists() or archive.exists():raise ValueError('Existing sealed snapshot/archive must not be overwritten')
 verify_final_files(dest)
 files=[]
 for p in sorted(dest.rglob('*')):
  if p.is_file() and p.name!='HANDOFF_MANIFEST_SHA256.json':files.append({'path':str(p.relative_to(dest)),'bytes':p.stat().st_size,'sha256':s.sha(p,'sha256')})
 write_json(dest/'HANDOFF_MANIFEST_SHA256.json',{'release_id':json.loads((dest/'RELEASE_MANIFEST.json').read_text())['release_id'],'private_team_only':True,'files':files})
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(dest.rglob('*')):
   if p.is_file():z.write(p,str(Path(dest.name)/p.relative_to(dest)))
 return archive

def main():
 ap=argparse.ArgumentParser();ap.add_argument('command',choices=['build','seal']);ap.add_argument('--root',type=Path,default=DEFAULT);ap.add_argument('--dest',type=Path,default=DEST);a=ap.parse_args()
 if a.command=='build':print(json.dumps(handoff(a.root,a.dest)[1],indent=2))
 else:print(seal(a.dest))
if __name__=='__main__':main()
