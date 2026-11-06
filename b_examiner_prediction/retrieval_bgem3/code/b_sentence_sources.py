"""Date-qualified patent technical sources and D pools. No encoder or model API."""
from __future__ import annotations
from collections import defaultdict
from datetime import date,timedelta
from functools import lru_cache
from pathlib import Path
import csv, hashlib, json, re

B=Path(__file__).resolve().parent
A=B.parent/'shared/profile_corpus_v2/profile_corpus'
T=B.parent/'shared/data_package/data_v1_share'
D=B.parent/'shared/D_phase1_v1_handoff/D_phase1_v1'
RELEASE=B/'outputs/profile_phase1_v4_reviewed'

def rows(path):
 with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(path,algorithm='sha1'):return hashlib.new(algorithm,Path(path).read_bytes()).hexdigest()
def textsha(text):return hashlib.sha256(text.encode()).hexdigest()
def norm(text):return re.sub(r'\s+',' ',text).strip()
SVG_NOISE=re.compile(r'SVG\s*\S+?\.svg[\d.\s]*(?:(?:Drawing|Chemistry|Graph|Table|Maths|DNA)\s*)?Black\s+and\s+white\s*',re.I)
PROSECUTION_NOISE=re.compile(r'\bexaminer\b|\bart[ -]+unit\b|\boffice\s+action\b|\b35\s+U\.?\s*S\.?\s*C\b|\binterview\s+summary\b|\bresponse\s+to\s+rejection\b',re.I)
def flag(value):return str(value).lower()=='true'
def date_allowed(source,anchor,cutoff):return bool(source) and source<=anchor and source<cutoff

def check_catalog(dt,code,doc_id,catalog):
 matches=catalog.get(doc_id,[])
 if not any(r['official_date']==dt and r['doc_code']==code for r in matches):
  raise ValueError(f'catalog date/code mismatch: {dt}/{code}/{doc_id}')

def parse_record_filename(name,catalog):
 stem=Path(name).name.removesuffix('.txt').removesuffix('.substantive')
 dt=stem[:10];doc=stem.rsplit('_',1)[-1];encoded=stem[11:-(len(doc)+1)]
 matches=[r for r in catalog.get(doc,[]) if r['official_date']==dt and re.sub(r'[^A-Za-z0-9]','_',r['doc_code'])==encoded]
 if not matches:raise ValueError('catalog filename mismatch: '+name)
 return dt,matches[0]['doc_code'],doc

def read_technical(path):
 p=Path(path)
 if p.suffix=='.json':
  values=json.loads(p.read_text())
  if not isinstance(values,list):raise ValueError('Claims JSON must be a list')
  text=norm(SVG_NOISE.sub(' ',' '.join(str(r.get('text') or '') for r in values if not re.search(r'cancel|withdraw',str(r.get('status','')),re.I))))
  # Numeric OCR debris is not a patent technical representation.
  return text if re.search(r'[A-Za-z]{2,}',text) and not PROSECUTION_NOISE.search(text) else ''
 text=norm(SVG_NOISE.sub(' ',p.read_text()))
 return text if not PROSECUTION_NOISE.search(text) else ''

class SourceSelector:
 def __init__(self,root,index=None,manifest=None):
  self.root=Path(root).resolve();self.index=index or {};self.manifest=manifest or {}
 @lru_cache(maxsize=None)
 def catalog(self,app):
  p=self.root/'apps'/app/'catalog.csv';result=defaultdict(list)
  if p.exists():
   for r in rows(p):result[r['doc_id']].append(r)
  return result
 def source(self,path,dt,code,doc_id,publication=False):
  p=Path(path).resolve()
  if not p.is_relative_to(self.root):raise ValueError('Source path escape')
  if not publication:
   cat=self.catalog(p.parents[1].name)
   actual=parse_record_filename(p.name.replace('.claims.json','.txt'),cat)
   if actual!=(dt,code,doc_id):raise ValueError('catalog/manifest filename conflict')
   check_catalog(dt,code,doc_id,cat)
  relative=str(p.relative_to(self.root));h=sha(p)
  if relative in self.manifest:
   expected=self.manifest[relative]
   if h!=expected['sha1'] or p.stat().st_size!=int(expected['bytes']):raise ValueError('Source manifest mismatch: '+relative)
  text=read_technical(p)
  return {'path':str(p),'relative_path':relative,'date':dt,'doc_code':code,'doc_id':doc_id,'sha1':h,'text_sha256':textsha(text),'text':text,'version_basis':'pgpub_date' if publication else 'dated_record_catalog','source_manifest_verified':relative in self.manifest,'transform':'whitespace_normalization; explicit_cancelled/withdrawn_status_omitted; observed_SVG_metadata_removed; missing_graphics_not_reconstructed; mixed_prosecution_fields_rejected_not_redacted','known_svg_artifact_present':bool(SVG_NOISE.search(p.read_text())),'rejected_prosecution_metadata':bool(PROSECUTION_NOISE.search(norm(p.read_text())))}
 def assemble(self,app,anchor,cutoff,options,issues=None):
  chosen={};missing=[]
  for field in ['title','abstract','claims']:
   available=options.get(field,[])
   # Dated record supersedes publication at same date; stable doc_id/path tie-break.
   available.sort(key=lambda r:(r['date'],r['version_basis']!='pgpub_date',r['doc_id'],r['path']))
   if available:chosen[field]=available[-1]
   else:missing.append(field)
  text='\n'.join(f'{k.capitalize()}: {r["text"]}' for k,r in chosen.items())
  return {'app_id':app,'anchor_date':anchor,'cutoff':cutoff,'fields':chosen,'missing_fields':missing,'text':text,'text_sha256':textsha(text),'issues':issues or [],'representation_version':'dated_technical_title_abstract_claims_v1'}
 def history(self,app,anchor,cutoff):
  folder=self.root/'apps'/app/'text';options=defaultdict(list);issues=[]
  pub=self.index.get(app,{}).get('pgpub_date','')
  if date_allowed(pub,anchor,cutoff):
   for field,name,code in [('abstract','pgpub_abstract.txt','ABST'),('claims','pgpub_claims.json','CLM')]:
    path=folder/name
    if path.exists():
     r=self.source(path,pub,code,name.split('.')[0],True)
     if r['text']:options[field].append(r)
  # Never rank on ODP title: no dated title provenance in historical corpus.
  for path in sorted(folder.glob('*_CLM_*.claims.json')):
   m=re.fullmatch(r'(\d{4}-\d{2}-\d{2})_CLM_(.+)\.claims\.json',path.name)
   if m and date_allowed(m[1],anchor,cutoff):
    r=self.source(path,m[1],'CLM',m[2])
    if r['text']:options['claims'].append(r)
    else:issues.append({'path':str(path),'reason':'mixed_prosecution_metadata_rejected' if r['rejected_prosecution_metadata'] else 'empty_parsed_claim_listing'})
  return self.assemble(app,anchor,cutoff,options,issues)
 def target(self,case):
  app=case['sample_id'];cutoff=case['cutoff'];e=json.loads((self.root/'examples'/f'{app}.json').read_text());options=defaultdict(list);issues=[]
  # assemble's historical strict date check is handled here: A1-date records are authorized inputs.
  for d in e['inputs']:
   if d['date']>cutoff or d.get('doc_id')==(e.get('target') or {}).get('doc_id'):raise ValueError('Target manifest future/target input')
   if d['doc_code'] not in ['ABST','CLM'] or not d.get('text_path'):continue
   path=self.root/d['text_path']
   if not path.exists():issues.append({'path':str(path),'reason':'missing_target_technical_file'});continue
   if d['doc_code']=='CLM' and path.suffix!='.json':
    parsed=path.with_suffix('.claims.json')
    if parsed.exists():path=parsed
    else:
     issues.append({'path':str(path),'reason':'claims_no_structured_listing'});continue
   r=self.source(path,d['date'],d['doc_code'],d['doc_id'],d['source']=='pgpub_xml')
   if r['text']:options['abstract' if d['doc_code']=='ABST' else 'claims'].append(r)
   else:issues.append({'path':str(path),'reason':'mixed_prosecution_metadata_rejected' if r['rejected_prosecution_metadata'] else 'empty_parsed_claim_listing'})
  return self.assemble(app,cutoff,cutoff,options,issues)

def map_pool(case_rows,masters,sample,variant,cutoff,examiners,benchmark_apps,benchmark_families,deduplicate=True):
 valid=[];excluded=[]
 for r in case_rows:
  if (r['sample_id'],r['variant'])!=(sample,variant):continue
  m=masters[r['episode_id']];reason=''
  if r['cutoff']!=cutoff:raise ValueError('D cutoff mismatch')
  if not flag(r['next_observed']):reason='waiting_at_cutoff'
  elif not flag(r['next_signed_ok']) or m['prior_signed']=='false' or m['next_signed']=='false':reason='known_other_examiner_action'
  elif r['examiner_id'] not in examiners:reason='examiner_not_in_D_card'
  elif r['app_id'] in benchmark_apps or r['family_root'] in benchmark_families:reason='benchmark_application_or_family'
  elif not all(d<cutoff for d in [m['prior_date'],r['reply_date'],m['next_date']]):reason='episode_event_not_before_cutoff'
  if reason:excluded.append({'sample_id':sample,'variant':variant,'episode_id':r['episode_id'],'reason':reason});continue
  if r.get('next_days_cut'):
   expected=(date.fromisoformat(r['reply_date'])+timedelta(days=int(r['next_days_cut']))).isoformat()
   if expected!=m['next_date']:raise ValueError('D next event mismatch')
  valid.append(r)
 seen=set();mapped=[]
 for r in sorted(valid,key=lambda r:(r['reply_date'],r['episode_id'])):
  if deduplicate and r['app_id'] in seen:
   excluded.append({'sample_id':sample,'variant':variant,'episode_id':r['episode_id'],'reason':'later_eligible_episode_same_application'});continue
  seen.add(r['app_id']);mapped.append(r)
 return mapped,excluded

class Corpus:
 def __init__(self):
  self.cases=rows(A/'cases.csv');self.index={r['app_id']:r for r in rows(A/'profile_index.csv')}
  self.case_episodes=rows(D/'case_episodes.csv');self.masters={r['episode_id']:r for r in rows(D/'episodes.csv')}
  self.cards={(r['sample_id'],r['variant']):r for r in map(json.loads,(D/'stats_cards.jsonl').read_text().splitlines())}
  benchmark=rows(T/'sample_manifest.csv');self.bench_apps={r['app_id'] for r in benchmark};self.bench_families={r['family_id'] for r in benchmark}
  self.hist=SourceSelector(A,self.index,{r['path']:r for r in rows(A/'MANIFEST.csv')});self.targets=SourceSelector(T)
  self.fixed_review_ids=list(dict.fromkeys(r['sample_id'] for r in rows(RELEASE/'source_review/profile_review_C_done.csv')))
  if len(self.fixed_review_ids)!=10:raise ValueError('Fixed review cohort changed')
 @lru_cache(maxsize=None)
 def episode_source_dates(self,eid):
  e=self.masters[eid];folder=A/'apps'/e['app_id']/'text';sources=[]
  for field in ['prior_doc_ids','next_doc_ids']:
   for doc in filter(None,e[field].split(';')):
    for path in sorted(folder.glob('*_'+doc+'*.txt')):sources.append((path,field))
  for rel in filter(None,e['reply_text_paths'].split(';')):
   if (A/rel).exists():sources.append((A/rel,'reply_text_paths'))
  result=[]
  for path,role in sources:
   dt,code,doc=parse_record_filename(path.name,self.hist.catalog(e['app_id']))
   relative=str(path.relative_to(A));expected=self.hist.manifest.get(relative)
   if not expected or sha(path)!=expected['sha1']:raise ValueError('Episode source manifest mismatch')
   if role!='next_doc_ids' and dt>e['next_date']:return None
   result.append(dt)
  return result
 def pool(self,case,variant):
  card=self.cards[case['sample_id'],variant];exam=card['examiner_ids'];exam=set(exam.split(';') if isinstance(exam,str) else exam)
  mapped,excluded=map_pool(self.case_episodes,self.masters,case['sample_id'],variant,case['cutoff'],exam,self.bench_apps,self.bench_families,deduplicate=False)
  result=[];used=set()
  for r in mapped:
   ix=self.index[r['app_id']]
   if ix['family_root']!=r['family_root'] or ix['examiner_id']!=r['examiner_id']:raise ValueError('A/D identity or family mismatch')
   if not ix['first_signed_action']<case['cutoff']:raise ValueError('A first action after cutoff')
   source_dates=self.episode_source_dates(r['episode_id'])
   if source_dates is None or any(dt>=case['cutoff'] for dt in source_dates):
    excluded.append({'sample_id':case['sample_id'],'variant':variant,'episode_id':r['episode_id'],'reason':'episode_source_date_ineligible'});continue
   technical=self.hist.history(r['app_id'],r['reply_date'],case['cutoff'])
   if not technical['text']:
    excluded.append({'sample_id':case['sample_id'],'variant':variant,'episode_id':r['episode_id'],'reason':'no_date_verified_technical_text'});continue
   if r['app_id'] in used:
    excluded.append({'sample_id':case['sample_id'],'variant':variant,'episode_id':r['episode_id'],'reason':'later_fully_eligible_episode_same_application'});continue
   used.add(r['app_id'])
   result.append({'case_episode':r,'episode':self.masters[r['episode_id']],'technical':technical})
  return result,excluded
