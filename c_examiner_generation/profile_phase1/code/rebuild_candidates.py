"""Assemble one reviewable shared candidate set from A, B, and D. No model calls.

This is a proposed integration for B to adopt, not a silent replacement of B/D.
The final human review and a shared release manifest are deliberately separate.
"""
from pathlib import Path
from collections import defaultdict, Counter
from datetime import date
import argparse
import csv, hashlib, html, io, json, math, re, statistics, zipfile
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--a',type=Path,required=True,help='Extracted A profile_corpus directory')
ap.add_argument('--b',type=Path,required=True,help='Extracted original B phase1 directory')
ap.add_argument('--d',type=Path,required=True,help='Extracted D phase1 directory')
ap.add_argument('--benchmark-zip',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True,help='A NEW output directory')
ap.add_argument('--work-dir',type=Path,required=True,help='Private intermediate directory')
args=ap.parse_args()
A=args.a.resolve();B=args.b.resolve();D=args.d.resolve();OUT=args.output.resolve();WORK=args.work_dir.resolve()
if OUT.exists() and any(OUT.iterdir()):
    ap.error('Use a new output directory. Existing reviews or profiles will not be overwritten.')
WORK.mkdir(parents=True,exist_ok=True)
for p in ['candidate_profiles/own','candidate_profiles/mismatched','candidate_profiles/artunit','audit','review','prompts','code']:(OUT/p).mkdir(parents=True,exist_ok=True)

def rc(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def jl(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]
def sha(p):return hashlib.sha1(Path(p).read_bytes()).hexdigest()
def textsha(s):return hashlib.sha1(s.encode()).hexdigest()
def writecsv(path,rr):
    keys=list(dict.fromkeys(k for r in rr for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rr)
def good(v):return str(v).lower()=='true'
def scrub(t):
    t=re.sub(r'(?im)^.*(?:directed to|whose telephone|examiner[\s,:;]|art unit|supervisor|telephone|e-mail|@).*$',' ',t)
    t=re.sub(r'(?m)^\s*/[^/\n\d]{2,100}/\s*$',' ',t)
    t=re.sub(r'\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b',' ',t)
    return re.sub(r'\s+',' ',t).strip()
def excerpt(path,limit=420):
    raw=path.read_text();ls=raw.splitlines();use=[]
    for i,line in enumerate(ls,1):
        s=scrub(line)
        if len(s)>35:use.append((i,s))
    favored=[x for x in use if re.search(r'claim|reject|amend|allowab|cancel|travers|argu|withdraw|response',x[1],re.I)]
    chosen=(favored or use)[:5]
    if not chosen:return None
    start,end=chosen[0][0],chosen[-1][0];joined=scrub('\n'.join(ls[start-1:end]))
    truncated=len(joined)>limit
    q=joined[:limit]
    if truncated:q=q.rsplit(' ',1)[0]+' [...]'
    return {'path':str(path.relative_to(A)),'sha1':sha(path),'start_line':start,'end_line':end,
            'quote':q,'truncated':truncated,'source_date':path.name[:10],
            'transform':'contact/signature removal; whitespace normalization; marked word-boundary clipping'}
def source_file(app,doc,prefer_sub=False):
    folder=A/'apps'/app/'text'
    options=sorted(folder.glob('*_'+doc+('.substantive.txt' if prefer_sub else '.txt')))
    for p in options:
        if p.read_text().strip():return p
    if prefer_sub:return source_file(app,doc,False)
    return None
def signer_hash_match(raw,expected):
    # Match exact, conventional uppercase LAST, GIVEN name hashes, without exporting names.
    names=[]
    for m in re.finditer(r'directed\s+to\s+(.+?)\s+whose',raw,re.I|re.S):
        s=' '.join(m.group(1).split())
        if 2<=len(s.split())<=6 and len(s)<=100:names.append(s)
    for m in re.finditer(r'/\s*([^/\n]{3,70})\s*/',raw):
        names.append(m.group(1).strip())
    ids=set()
    for s in names:
        s=s.upper().strip();versions={s}
        if ',' not in s:
            words=s.split()
            if len(words)>=2:versions.add(words[-1]+', '+' '.join(words[:-1]))
        for v in versions:ids.add('ex_'+hashlib.sha1(v.encode()).hexdigest()[:10])
    return True if expected in ids else None


# This builder reproduces this audited release, not arbitrary input versions.
EXPECTED_INPUTS = {('A', 'cases.csv'): '31913688b92437cebba59cb6bacd5cbbc74729c7', ('A', 'profile_index.csv'): '4cbe10c3bcd9824fc000feb2301d7ca41fcfe1a2', ('A', 'actions.csv'): 'd129a0f9d2eaf67af188e0cd9029102b29e76c16', ('A', 'checks.json'): 'ea13473a349ab285b922d9fd794e63600786e649', ('A', 'MANIFEST.csv'): '2dc1ef4d8f29991b81094adc69e00861a7f236f3', ('D', 'episodes.csv'): 'c5f52284903dc353a6be13fbf1718f627eb1b1ec', ('D', 'case_episodes.csv'): 'e9ab55a2cfa7dbb46032a440df7335e77a02352d', ('D', 'stats_cards.jsonl'): '5d165efb31b444277eab3fced47807863b149d04', ('D', 'leak_check.csv'): '00d5c1ae91bb42d5016cf354be698448bcc1d3db', ('B', 'query_manifest.jsonl'): '92ef9a84c44603afe68512d5aecd4e0af1b82116', ('B', 'profile_review_C.csv'): '90461c99257097690361421dbef27760ebaa89c5'}
for (tag, relative_path), expected in EXPECTED_INPUTS.items():
    base={'A':A,'B':B,'D':D}[tag]
    if sha(base/relative_path)!=expected:
        raise ValueError(f'Input version mismatch: {tag}/{relative_path}; re-audit changed inputs before building.')
for row in rc(A/'MANIFEST.csv'):
    source=A/row['path']
    if source.stat().st_size!=int(row['bytes']) or sha(source)!=row['sha1']:
        raise ValueError(f"A source manifest mismatch: {row['path']}")

cases=rc(A/'cases.csv');case_by={c['sample_id']:c for c in cases}
index=rc(A/'profile_index.csv');idx_by_app={r['app_id']:r for r in index}
actions=rc(A/'actions.csv');act={(r['app_id'],r['doc_id']):r for r in actions}
cards={(r['sample_id'],r['variant']):r for r in jl(D/'stats_cards.jsonl')}
episodes={r['episode_id']:r for r in rc(D/'episodes.csv')}
cut_by=defaultdict(list)
for r in rc(D/'case_episodes.csv'):cut_by[r['sample_id'],r['variant']].append(r)
review_old=rc(B/'profile_review_C.csv');review_ids=list(dict.fromkeys(r['sample_id'] for r in review_old))
template=(Path(__file__).resolve().parents[1]/'prompts/profile_block.txt').read_text(encoding='utf-8')
(OUT/'prompts/profile_block.txt').write_text(template,encoding='utf-8')
query_by={};query_docs={};current_contexts={};target_identity=[]
oldq={r['sample_id']:r for r in jl(B/'query_manifest.jsonl')}

with zipfile.ZipFile(args.benchmark_zip) as z:
    manifest=list(csv.DictReader(io.StringIO(z.read('data_v1_share/sample_manifest.csv').decode('utf-8-sig'))))
    bench_f={r['family_id'] for r in manifest};bench_a={r['app_id'] for r in manifest}
    for c in cases:
        sid=c['sample_id'];e=json.loads(z.read('data_v1_share/examples/'+sid+'.json'))
        parts=[];docs=[]
        allowed={'CTNF','CTFR','CTRS','NOA','CTAV','CTEQ','CTMS','EXIN','REM','A...','A.NE','A.AF','A.I.','AMSB','CLM'}
        for d in e['inputs']:
            assert d['date']<=c['cutoff'] and d['doc_id']!=(e.get('target') or {}).get('doc_id')
            if d['doc_code'] not in allowed or not d.get('text_path'):continue
            raw=z.read('data_v1_share/'+d['text_path']).decode()
            if d['text_path'].endswith('.json'):raw=' '.join(str(x.get('text','')) for x in json.loads(raw))
            parts.append(scrub(raw)[:12000]);docs.append({**d,'text':raw})
        query_by[sid]='\n'.join(parts);query_docs[sid]=docs
        assert textsha(query_by[sid])==oldq[sid]['query_sha1']
        o1=next((d['text'] for d in docs if d['doc_id']==e['o1']['doc_id']),'')
        target_identity.append({'sample_id':sid,'signer_source':c['signer_source'],
                                'v2_examiner_id':c['examiner_id'],'current_O1_name_hash_match':signer_hash_match(o1,c['examiner_id'])})
        if sid in review_ids:
            try:abstract=z.read('data_v1_share/apps/'+sid+'/text/pgpub_abstract.txt').decode()
            except KeyError:abstract=''
            current_contexts[sid]={'case':c,'family_id':e['family_id'],'abstract':abstract,'documents':docs,
                                  'o1_doc_id':e['o1']['doc_id']}
assert all(r['family_root'] not in bench_f and r['app_id'] not in bench_a for r in index)

docmap={}
for p in (A/'apps').glob('*/text/*'):
    if p.is_file():docmap[str(p.relative_to(A))]=p
candidate_cache={};source_fail=[];policy_exclusions=[]
type_names={'allowance':'NOA (notice of allowance)','final_rejection':'CTFR (final action)',
            'nonfinal_rejection':'CTNF (non-final action)','advisory_action':'CTAV (advisory action)',
            'restriction':'CTRS (restriction)','quayle_action':'CTEQ (Quayle action)', 'abandonment':'abandonment notice'}

def build_episode(master):
    app=master['app_id'];eid=master['episode_id']
    if master['prior_signed']=='false':return None,'known_other_examiner_prior_OA'
    if master['next_signed']=='false':return None,'known_other_examiner_next_OA'
    prior=[]
    for did in filter(None,master['prior_doc_ids'].split(';')):
        p=source_file(app,did,True)
        if p:prior.append(p)
    replies=[]
    for p in filter(None,master['reply_text_paths'].split(';')):
        fp=A/p
        if fp.is_file() and fp.read_text().strip():replies.append(fp)
    # Preserve the D episode boundary; do not borrow a later supplemental response.
    ranking_text='\n'.join(scrub(p.read_text())[:6000] for p in prior)+'\n'+'\n'.join(scrub(p.read_text())[:6000] for p in replies)[:12000]
    if not ranking_text.strip():return None,'no_readable_pre_outcome_context'
    next_files=[]
    for did in filter(None,master['next_doc_ids'].split(';')):
        p=source_file(app,did,True)
        if p:next_files.append(p)
    rv=next((ex for p in sorted(replies,key=lambda p:('_REM_' not in p.name,p.name)) if (ex:=excerpt(p))),None)
    nv=next((ex for p in next_files if (ex:=excerpt(p))),None)
    allfiles=list(dict.fromkeys(prior+replies+next_files))
    source_dates=sorted({p.name[:10] for p in allfiles}|{master['prior_date'],master['reply_date'],master['next_date']})
    before_next=all(p.name[:10]<=master['next_date'] for p in prior+replies)
    if not before_next:return None,'pre_outcome_source_dated_after_next_notice'
    signature_flag=master['signature_basis']
    next_date=master['next_date'];types=type_names.get(master['next_type'],master['next_type'])
    if rv:
        reply_line=f"Reply {master['reply_date']} [doc {Path(rv['path']).name.split('_')[-1].replace('.txt','')}]: {rv['quote']}"
    else:reply_line=f"Reply recorded {master['reply_date']} [transaction {master['reply_codes']}]. No readable reply body is supplied; its arguments or strategy are unknown."
    attrib='signature verified in A actions.csv' if signature_flag=='actions_csv_verified' else 'assigned-examiner attribution; signature unverified'
    next_line=f"Next recorded communication {next_date}: {types}; {master['next_days']} days after reply; {attrib}."
    if nv:next_line+=f" {nv['quote']}"
    else:next_line+=' Notice text is unavailable; only the recorded event type and date are supported.'
    proof={'path':f'apps/{app}/transactions.csv','sha1':sha(A/'apps'/app/'transactions.csv'),
           'event_date':next_date,'event_code':master['next_code']}
    catalog={'path':f'apps/{app}/catalog.csv','sha1':sha(A/'apps'/app/'catalog.csv')}
    raw_verified=[]
    for p in prior+next_files:
        did=p.name.split('_')[-1].replace('.substantive.txt','').replace('.txt','')
        ar=act.get((app,did))
        if ar and ar['signed_by_this_examiner']=='true':
            raw=source_file(app,did,False)
            if raw:raw_verified.append(signer_hash_match(raw.read_text(),master['examiner_id']) is True)
    return {'episode_id':eid,'app_id':app,'family_root':master['family_root'],'examiner_id':master['examiner_id'],
            'prior_date':master['prior_date'],'reply_date':master['reply_date'],'next_date':next_date,
            'next_code':master['next_code'],'next_type':master['next_type'],'elapsed_days':int(master['next_days']),
            'reply_text_status':'available' if rv else 'unavailable','signature_basis':signature_flag,
            'source_dates':source_dates,'source_sha1':{str(p.relative_to(A)):sha(p) for p in allfiles},
            'source_paths':[str(p.relative_to(A)) for p in allfiles],
            'evidence':{'reply':rv,'next':nv,'next_transaction':proof,'catalog':catalog},
            'summary_lines':[reply_line,next_line],'retrieval_text':ranking_text,
            'summary_method':'deterministic_extractive_D_episode_C_v1','raw_OA_name_hash_checks':raw_verified},''

def percent(v):return 'not estimable' if v is None else f'{100*v:.0f}%'
def days(v):return 'not reached' if v is None else f'{v:g} days'
def stat_text(card):
    s=card['stats'];nl=s['next_letter'];fr=s['first_reply'];g=s['grounds']
    scope='the reference examiner' if card['variant']!='artunit' else 'the available art-unit reference pool'
    ls=[f"Reference sample for {scope}: {s['n_applications']} applications, strictly before {card['cutoff']}.",
        f"Raw statistics: {nl['n_episodes']} replies after a recorded non-final action; {nl['n_observed']} observed next communications and {nl['n_waiting_at_cutoff']} still waiting at the cutoff."]
    if nl['n_observed']:
        t=nl['type_shares']
        ls.append(f"Observed next communication (denominator {nl['n_observed']}): NOA {percent(t['allowance'])}, CTFR {percent(t['final_rejection'])}, CTNF {percent(t['nonfinal_rejection'])}, other {percent(t['other'])}.")
        m=nl['median_days_observed']
        ls.append(f"Time to next communication: KM median {days(nl['median_days_km'])}; observed subgroup upper medians: NOA {days(m['allowance'])}, CTNF/CTFR {days(m['rejection'])}.")
    if fr['n_episodes']:
        rd=fr['rounds_dist_km']
        ls.append(f"First-reply applications (n={fr['n_episodes']}): {fr['n_allowed']} allowance events, {fr['n_abandoned']} abandonment events, {fr['n_pending_at_cutoff']} pending at cutoff. Survival estimates: allowance by 12/24 months {percent(fr['allowed_by_12m'])}/{percent(fr['allowed_by_24m'])}; abandonment by 24 months {percent(fr['abandoned_by_24m'])}.")
        ls.append(f"Further CTNF/CTFR communications (censor-aware estimates): 0 {percent(rd['0'])}, 1 {percent(rd['1'])}, 2 {percent(rd['2'])}, 3+ {percent(rd['3']+rd['4+'])}; RCE filed {percent(fr['rce_rate'])}.")
    if g['n_signed_rejections']:
        ls.append(f"Approximate ground frequencies in {g['n_signed_rejections']} signature-verified CTNF/CTFR texts: 103 {percent(g['share_103'])}, 102 {percent(g['share_102'])}, 112 {percent(g['share_112'])}, 101 {percent(g['share_101'])}. Grounds may co-occur.")
    sh=card['shrunk']
    if sh:
        ls.append(f"Selected adjusted estimates toward the available art-unit pool (k=5; rate weight n={nl['n_observed']}, time weight n={nl['n_episodes']}, first-reply weight n={fr['n_episodes']}): next NOA {percent(sh['next_allowance_share'])}, next CTFR {percent(sh['next_final_rejection_share'])}, next-time median {days(sh['median_days_next_letter'])} (log adjustment), allowance/abandonment by 24 months {percent(sh['allowed_by_24m'])}/{percent(sh['abandoned_by_24m'])}, no further CTNF/CTFR {percent(sh['p_no_more_rejections'])}, RCE {percent(sh['rce_rate'])}.")
    group=cut_by[card['sample_id'],card['variant']]
    sig=Counter(r['signature_basis'] for r in group if good(r['next_signed_ok']) and good(r['next_observed']))
    ls.append(f"Attribution among all observed eligible episodes: {sig['actions_csv_verified']} next actions signature-verified; {sig['assigned_examiner_unverified']+sig['no_uspto_text_unverified']} notices assignment-attributed without a verified signature. Next actions flagged as signed by another examiner are excluded from these next-action statistics. Later outcome and rounds statistics describe the application trajectory, rather than verifying authorship of every event.")
    if fr['n_episodes']<10:ls.append('Few first-reply cases: treat these estimates as imprecise.')
    if case_by[card['sample_id']]['signer_source']=='o1_signer_not_in_odp':ls.append('Target examiner identity uses a documented fallback; attribution to the O1 signer is uncertain.')
    return '\n'.join(ls)

profile_rows=[];retrieval_rows=[];review_data=[];seen_sources={};all_source_checks=[]
for c in cases:
    sid=c['sample_id']
    for variant in ['own','mismatched','artunit']:
        card=cards[sid,variant];eligible=[]
        for cut in cut_by[sid,variant]:
            if not good(cut['next_observed']) or not good(cut['next_signed_ok']):continue
            eid=cut['episode_id'];master=episodes[eid]
            if eid not in candidate_cache:
                candidate_cache[eid]=build_episode(master)
            item,reason=candidate_cache[eid]
            if item is None:
                policy_exclusions.append({'sample_id':sid,'variant':variant,'episode_id':eid,'reason':reason});continue
            if not all(d<c['cutoff'] for d in item['source_dates']):
                policy_exclusions.append({'sample_id':sid,'variant':variant,'episode_id':eid,'reason':'source_not_strictly_before_case_cutoff'});continue
            if item['family_root'] in bench_f or item['app_id'] in bench_a:raise ValueError('Family/application overlap')
            assert idx_by_app[item['app_id']]['first_signed_action']<c['cutoff']
            expected_date=(date.fromisoformat(cut['reply_date'])+__import__('datetime').timedelta(days=int(cut['next_days_cut']))).isoformat()
            assert item['next_date']==expected_date and item['elapsed_days']==int(cut['next_days_cut'])
            eligible.append(item)
        if eligible:
            tf=TfidfVectorizer(lowercase=True,stop_words='english',ngram_range=(1,2),sublinear_tf=True,max_features=40000)
            mat=tf.fit_transform([e['retrieval_text'] for e in eligible]);ss=(mat@tf.transform([query_by[sid]]).T).toarray().ravel()
            order=sorted(range(len(eligible)),key=lambda i:(-ss[i],eligible[i]['episode_id']))
            selected=[];used_apps=set();used_families=set()
            for i in order:
                e=eligible[i]
                if e['app_id'] in used_apps or e['family_root'] in used_families:continue
                selected.append({k:v for k,v in e.items() if k!='retrieval_text'}|{'similarity':float(ss[i])})
                used_apps.add(e['app_id']);used_families.add(e['family_root'])
                if len(selected)==3:break
        else:selected=[]
        statistics_text=stat_text(card)
        blocks=[f"Example {i}: application {e['app_id']} (other family).\n"+'\n'.join(e['summary_lines']) for i,e in enumerate(selected,1)]
        if len(selected)<3:blocks.insert(0,f'Only {len(selected)} eligible distinct-application/family examples are available; no replacement or invented example is supplied.')
        profile_text=template.format(cutoff=c['cutoff'],D_verified_statistics_with_denominators=statistics_text,
                                     three_retrieved_two_line_case_summaries_with_sources='\n'.join(blocks))
        # A UTF-8-byte bound is conservative for both byte-level BPE tokenizers.
        # It is explicitly not claimed to be an exact o200k/Qwen token count.
        if len(profile_text.encode())>8000:raise ValueError(f'Conservative profile token cap exceeded: {sid}/{variant}')
        assert not re.search(r'\bex_[a-f0-9]{10}\b|mismatched|wrong examiner',profile_text,re.I)
        profile={'schema_version':'C-phase1-integrated-candidate-v1','sample_id':sid,'prediction_sample_id':sid+'_t1',
                 'cutoff':c['cutoff'],'setting':variant,'target_examiner_id':c['examiner_id'],
                 'profile_examiner_ids':card['examiner_ids'],'control_art_unit':c['control_art_unit'],
                 'signer_source':c['signer_source'],'statistics':card['stats'],'shrunk_statistics':card['shrunk'],
                 'D_card_sha1':card['card_sha1'],'D_original_card_text':card['card_text'],
                 'statistics_text':statistics_text,'statistics_text_sha1':textsha(statistics_text),
                 'statistics_render_version':'C-defined-labels-and-raw-plus-adjusted-v1',
                 'D_episode_status':'D_verified_v1; reproduced byte-for-byte from A v2',
                 'C_review_status':'human_review_pending','freeze_status':'candidate_not_frozen',
                 'requested_k':3,'retrieved_k':len(selected),'candidate_episode_n':len(eligible),
                 'retrieved_cases':selected,'profile_text':profile_text,'profile_text_sha1':textsha(profile_text),
                 'profile_block_sha1':textsha(template),'query_sha1':textsha(query_by[sid]),
                 'token_count_upper_bound_utf8_bytes':len(profile_text.encode()),'max_profile_tokens':8000,
                 'retrieval_method':'B TF-IDF unigram/bigram cosine on D-observed eligible pre-outcome contexts; episode_id tie-break; distinct application/family',
                 'additional_source_gate':'Exclude known other-examiner prior CTNF/CTFR as required by A rule 3',
                 'artunit_pool_scope':'Available historical-art-unit own/control examiner pool; target examiner excluded; not a representative population',
                 'limitations':['Assignment-attributed unsigned notices remain explicitly qualified.',
                                'D original conditional medians are upper medians, explicitly labeled.',
                                'C rendering adds already-delivered adjusted estimates; original D numbers and card hash are retained.',
                                'Human review and team adoption of this shared integration are pending.']}
        if len(selected)<3:profile['limitations'].append('Incomplete k=3; actual retrieval coverage must be reported.')
        if c['signer_source']=='o1_signer_not_in_odp':profile['limitations'].append('O1 signer could not be matched to available examiner history; target identity is a fallback.')
        path=OUT/'candidate_profiles'/variant/(sid+'.json');path.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n')
        pr={'sample_id':sid,'setting':variant,'profile_path':str(path.relative_to(OUT)), 'profile_sha1':sha(path),
            'profile_text_sha1':profile['profile_text_sha1'],'D_card_sha1':card['card_sha1'],
            'statistics_text_sha1':profile['statistics_text_sha1'],'cutoff':c['cutoff'],'retrieved_k':len(selected),
            'candidate_episode_n':len(eligible),'max_profile_token_upper_bound':len(profile_text.encode()),
            'dates_ok':all(d<c['cutoff'] for e in selected for d in e['source_dates']),
            'families_ok':all(e['family_root'] not in bench_f and e['app_id'] not in bench_a for e in selected),
            'status':'candidate_not_frozen'}
        profile_rows.append(pr)
        for rank,e in enumerate(selected,1):
            retrieval_rows.append({'sample_id':sid,'setting':variant,'rank':rank,'episode_id':e['episode_id'],
                                   'app_id':e['app_id'],'family_root':e['family_root'],'reply_date':e['reply_date'],
                                   'next_date':e['next_date'],'next_type':e['next_type'],'signature_basis':e['signature_basis'],
                                   'similarity':e['similarity'],'reply_text_status':e['reply_text_status']})
        if sid in review_ids:
            source_context=[]
            for e in selected:
                for rel in e['source_paths']:
                    full=A/rel
                    source_context.append({'episode_id':e['episode_id'],'path':rel,'sha1':sha(full),'date':full.name[:10],
                                           'text':full.read_text()})
            review_data.append({'meta':pr,'profile':profile,'case':c,'current_context':current_contexts[sid],
                                'sources':source_context,'D_card':card})

writecsv(OUT/'profile_manifest.csv',profile_rows);writecsv(OUT/'retrieval_audit.csv',retrieval_rows)
writecsv(OUT/'audit/candidate_exclusions.csv',policy_exclusions)
writecsv(OUT/'audit/target_O1_identity_check.csv',target_identity)
review_rows=[]
for old in review_old:
    pr=next(r for r in profile_rows if r['sample_id']==old['sample_id'] and r['setting']==old['setting'])
    review_rows.append({'sample_id':old['sample_id'],'setting':old['setting'],'profile_path':pr['profile_path'],
                       'profile_sha1':pr['profile_sha1'],'cutoff':pr['cutoff'],
                       'dates_ok':'','families_ok':'','identity_ok':'','summary_faithful':'','rank_relevant':'',
                       'statistics_status_ok':'','verdict':'pending','reviewer':'','notes':''})
writecsv(OUT/'profile_review_C.csv',review_rows)
summary={'cases':len(cases),'candidate_profiles':len(profile_rows),'fixed_review_cases':review_ids,'review_rows':len(review_rows),
         'k3_profiles':sum(r['retrieved_k']==3 for r in profile_rows),
         'short_profiles':[r for r in profile_rows if r['retrieved_k']<3],
         'max_token_upper_bound_utf8_bytes':max(r['max_profile_token_upper_bound'] for r in profile_rows),
         'all_profile_dates_ok':all(r['dates_ok'] for r in profile_rows),'all_declared_families_ok':all(r['families_ok'] for r in profile_rows),
         'human_review_completed':False,'frozen':False,'new_model_calls':0,
         'retrieved_next_types':dict(Counter(r['next_type'] for r in retrieval_rows)),
         'source_gate_exclusions':dict(Counter(r['reason'] for r in policy_exclusions)),
         'profile_block_sha1':textsha(template)}
(OUT/'build_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(WORK/'candidate_review_data.json').write_text(json.dumps(review_data,ensure_ascii=False))
print(json.dumps(summary,indent=2))
