"""V4: consistent contact/handling-examiner attribution; co-signing is not a one-off exclusion."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import csv
import hashlib
import html
import json
import os
from pathlib import Path
from b_prediction import atomic_json, csvfile

B=Path(__file__).resolve().parent

def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def digest(text):return hashlib.sha1(text.encode()).hexdigest()
def filehash(path):return hashlib.sha1(Path(path).read_bytes()).hexdigest()

def verify_c_sources(root,manifest):
    missing=[]
    for r in manifest['files']:
        path=root/r['path']
        if not path.is_file():
            if r['path']=='review/index.html':
                missing.append(r['path']);continue
            raise ValueError('Missing required C source: '+r['path'])
        data=path.read_bytes()
        if len(data)!=r['bytes'] or hashlib.sha256(data).hexdigest()!=r['sha256']:
            raise ValueError('C source package changed: '+r['path'])
    return missing

def eligible_case_rows(episodes,sample_id,variant):
    return [r for r in episodes if r['sample_id']==sample_id and r['variant']==variant
            and str(r['next_observed']).lower()=='true' and str(r['next_signed_ok']).lower()=='true']

def attribution_text(text):
    substitutions={
        'signature verified in A actions.csv':'examiner of record verified (contact paragraph; may be co-signed by a primary/SPE)',
        'assigned-examiner attribution; signature unverified':'application-assignment attribution only; handling examiner not verified from a contact paragraph',
        'signature-verified CTNF/CTFR':'A-verified handling-examiner CTNF/CTFR',
        'signature-verified action':'A-verified handling-examiner action',
        'next actions signature-verified':'next actions with contact-paragraph verified handling examiner',
        'without a verified signature':'without contact-paragraph verification of the handling examiner',
        'signed rejections':'rejections attributed by A to the handling examiner (contact paragraph; primary/SPE co-signing possible)',
    }
    for old,new in substitutions.items():text=text.replace(old,new)
    return text

def statistics_text(card):
    payload={k:v for k,v in card.items() if k!='card_sha1'}
    if digest(json.dumps(payload,sort_keys=True))!=card['card_sha1']:
        raise ValueError('D card_sha1 mismatch')
    note=('Reading convention (proposed; D confirmation pending): the percentages above are raw; '
          'stored shrinkage-adjusted estimates are not displayed in this block. The overall time median is a KM median; '
          'allowance/rejection subgroup values use the upper median of observed times. Pending outcomes remain unknown; '
          'zero observed allowance estimates do not imply eventual allowance is impossible. Grounds are approximate text rules. '
          "A verifies the handling examiner using the contact paragraph, not the physical signatory. "
          'The action may be co-signed by a primary examiner or SPE. Notices without contact-paragraph verification '
          'are attributed through application assignment only. Outcome and rounds statistics describe application trajectories; '
          'they do not verify the physical signatory of every later event.')
    return attribution_text(card['card_text'])+'\n\n'+note

def revise(profile,card,template,quarantine_ids,reject_block=False):
    template=attribution_text(template)
    if profile['sample_id']!=card['sample_id'] or profile['setting']!=card['variant']:
        raise ValueError('Card/case/variant mismatch')
    p=copy.deepcopy(profile)
    p['C_proposed_statistics_text']=p.get('statistics_text')
    original=p['retrieved_cases']
    for e in original:
        e['summary_lines']=[attribution_text(line) for line in e['summary_lines']]
        e['examiner_attribution_basis']=('contact_paragraph_handling_examiner_verified_by_A' if e.get('signature_basis')=='actions_csv_verified' else 'application_assignment_handling_examiner_unverified')
        e['physical_signatory_verified']=False
        e['attribution_label_version']='A_contact_rule_v4'
    p['attribution_definition']='handling examiner identified by contact paragraph; physical signature may be primary/SPE'
    p['legacy_field_semantics']={
        'signature_basis':'Unchanged D source enum. actions_csv_verified denotes A contact-paragraph handling-examiner verification, not physical-signatory verification.',
        'next_signed_ok':'Unchanged D eligibility flag under the handling-examiner definition; true can also include assignment-attributed notices.',
        'signer_source':'Unchanged A source enum; interpret using the clarified A extraction rule and retain documented fallback limits.',
        'raw_OA_name_hash_checks':'Unchanged C parser observations, not a determination of the physical signatory.'}
    p['coverage_policy_status']='user_accepted_partial_k_and_statistics_only'
    p['C_proposed_statistics_text']=attribution_text(p.get('C_proposed_statistics_text') or '')
    retained=[] if reject_block else [e for e in original if e['episode_id'] not in quarantine_ids]
    p['quarantined_episode_ids']=[e['episode_id'] for e in original if e not in retained]
    p['retrieved_cases']=retained;p['retrieved_k']=len(retained)
    p['statistics']=copy.deepcopy(card['stats']);p['shrunk_statistics']=copy.deepcopy(card['shrunk'])
    p['D_original_card_text']=card['card_text'];p['card_sha1']=p['D_card_sha1']=card['card_sha1']
    p['statistics_text']=statistics_text(card);p['statistics_text_sha1']=digest(p['statistics_text'])
    p['statistics_render_version']='D_card_values_preserved_contact_labels_v4_pending_D_confirmation'
    p['statistics_confirmation_status']='pending_D'
    blocks=[f"Example {i}: application {e['app_id']} (other family).\n"+'\n'.join(e['summary_lines']) for i,e in enumerate(retained,1)]
    if not retained:
        blocks=['No reviewed comparable examples are supplied in this candidate block; do not infer a case-specific analogy from missing examples.']
    elif len(retained)<3:
        blocks.insert(0,f'Only {len(retained)} eligible distinct-application/family examples are supplied; no duplicate or hand-picked replacement is added.')
    p['profile_text']=template.format(cutoff=card['cutoff'],D_verified_statistics_with_denominators=p['statistics_text'],
                                     three_retrieved_two_line_case_summaries_with_sources='\n'.join(blocks))
    p['profile_text_sha1']=digest(p['profile_text']);p['profile_block_sha1']=digest(template)
    p['schema_version']='B-D-C-integration-candidate-v4'
    p['C_review_status']='pending_re_review_new_hash';p['freeze_status']='candidate_pending_D_C_team'
    p['retrieval_review_action']='entire_block_withheld_for_C_relevance_failure' if reject_block else 'source_attribution_quarantine' if len(retained)!=len(original) else 'unchanged_D_pool_TFIDF_selection'
    p['profile_mode']='statistics_only_pending_retrieval_resolution' if not retained else 'statistics_plus_retrieved_examples'
    p['limitations']=[attribution_text(s) for s in p.get('limitations',[])]+[
        'Original D card text and card_sha1 are retained in metadata; displayed attribution wording follows the clarified handling-examiner rule, with no numeric changes.',
        'New file hashes invalidate human judgments on the prior candidate; C re-review pending.',
        'User accepted reporting actual retrieved_k, including statistics-only variants; C relevance quarantine remains, and no hand-picked replacements are used.',
        'Handling-examiner attribution does not imply the handling examiner physically signed the action.']
    return p

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,default=B/'outputs/profile_phase1_D_integrated_replay')
    parser.add_argument('--reviewed-root',type=Path,default=B.parent/'shared/C_Examiner_RAG_Phase1/C_Examiner_RAG_Phase1')
    parser.add_argument('--review',type=Path,default=B.parent/'shared/C_Examiner_RAG_Phase1/profile_review_C_done.csv')
    parser.add_argument('--d',type=Path,default=B.parent/'shared/D_phase1_v1_handoff/D_phase1_v1')
    parser.add_argument('--output',type=Path,default=B/'outputs/profile_phase1_v4_candidate')
    a=parser.parse_args();out=a.output.resolve()
    if out.exists():raise ValueError('New output directory required')
    os.environ.setdefault('TIKTOKEN_CACHE_DIR',str(B/'outputs/profile_phase1_v2_support/tokenizer'))
    import tiktoken
    enc=tiktoken.get_encoding('o200k_base')
    manifest=json.loads((a.reviewed_root/'DELIVERY_MANIFEST_SHA256.json').read_text())
    missing_c_files=verify_c_sources(a.reviewed_root,manifest)
    for r in rows(a.d/'MANIFEST.csv'):
        p=a.d/r['path']
        if filehash(p)!=r['sha1'] or p.stat().st_size!=int(r['bytes']):raise ValueError('D source manifest mismatch')
    reviews=rows(a.review);review_by={(r['sample_id'],r['setting']):r for r in reviews}
    if len(reviews)!=30 or len(review_by)!=30:raise ValueError('Expected original 30 review rows')
    for r in reviews:
        if filehash(a.reviewed_root/r['profile_path'])!=r['profile_sha1']:
            raise ValueError('Review hash mismatch')
    cards={(r['sample_id'],r['variant']):r for r in [json.loads(s) for s in (a.d/'stats_cards.jsonl').read_text().splitlines()]}
    episodes=rows(a.d/'case_episodes.csv');masters={r['episode_id']:r for r in rows(a.d/'episodes.csv')}
    # User clarified that A verifies contact/handling examiner, not the physical
    # signatory; co-signing is a corpus-wide convention, not a reason to exclude
    # the original TF-IDF episode in this one case.
    quarantine=set()
    rejected={key for key,r in review_by.items() if r['rank_relevant']=='no'}
    expected={('14482153','mismatched'),('13773735','mismatched'),('13773735','artunit'),
              ('13577408','mismatched'),('13577408','artunit')}
    if rejected!=expected:raise ValueError('C review scope changed; re-evaluate remediation')
    template=attribution_text((a.reviewed_root/'prompts/profile_block.txt').read_text())
    out.mkdir(parents=True);(out/'prompts').mkdir();(out/'prompts/profile_block.txt').write_text(template)
    audit=[];review_queue=[];quarantine_rows=[];man=[];matched_selection=0;matched_text=0
    for src in sorted((a.candidate/'candidate_profiles').glob('*/*.json')):
        p=json.loads(src.read_text());key=(p['sample_id'],p['setting']);reviewed=a.reviewed_root/'candidate_profiles'/p['setting']/src.name
        previous=json.loads(reviewed.read_text())
        if [e['episode_id'] for e in p['retrieved_cases']]!=[e['episode_id'] for e in previous['retrieved_cases']]:
            raise ValueError('Replayed C selection changed')
        matched_selection+=1;matched_text+=p['profile_text']==previous['profile_text']
        pool={r['episode_id']:r for r in eligible_case_rows(episodes,*key)}
        for e in p['retrieved_cases']:
            if e['episode_id'] not in pool or masters[e['episode_id']]['prior_signed']=='false':
                raise ValueError('Selected source violates D or prior-signature policy')
            if not all(v<p['cutoff'] for v in e['source_dates']):raise ValueError('Future source')
        new=revise(p,cards[key],template,quarantine,reject_block=key in rejected)
        new['previous_reviewed_profile_sha1']=filehash(reviewed)
        new['candidate_episode_n_before_review_quarantine']=p['candidate_episode_n']
        new['review_quarantine_policy']='withhold C-rejected relevance blocks only; contact-attributed co-signed actions retained uniformly; no replacement or ranking retuning'
        new['token_count']=len(enc.encode(new['profile_text'],disallowed_special=()))
        new['tokenizer']='o200k_base';new['token_count_upper_bound_utf8_bytes']=len(new['profile_text'].encode())
        assert new['token_count']<=8000 and len(new['profile_text'].encode())<=8000
        assert attribution_text(cards[key]['card_text']) in new['profile_text']
        path=out/'candidate_profiles'/new['setting']/src.name;atomic_json(path,new)
        m={'sample_id':key[0],'setting':key[1],'profile_path':str(path.relative_to(out)),
           'profile_sha1':filehash(path),'profile_text_sha1':new['profile_text_sha1'],
           'card_sha1':new['card_sha1'],'D_card_sha1':new['D_card_sha1'],'statistics_text_sha1':new['statistics_text_sha1'],
           'cutoff':new['cutoff'],'retrieved_k':new['retrieved_k'],'token_count':new['token_count'],
           'previous_profile_sha1':new['previous_reviewed_profile_sha1'],'status':'candidate_pending_D_C_team'}
        man.append(m)
        audit.append({**m,'C_previous_verdict':review_by.get(key,{}).get('verdict','outside_original_10_case_review'),
                      'action':new['retrieval_review_action'],'previous_k':p['retrieved_k'],
                      'quarantined_episode_ids':';'.join(new['quarantined_episode_ids']),
                      'statistics_note_changed':True,'C_re_review_required':True,'D_confirmation_required':True})
        for eid in new['quarantined_episode_ids']:
            quarantine_rows.append({'sample_id':key[0],'setting':key[1],'episode_id':eid,
                                    'reason':'C_relevance_no_entire_block' if key in rejected else 'C_signature_attribution_unknown'})
        if key in review_by:
            old=review_by[key]
            review_queue.append({'sample_id':key[0],'setting':key[1],'profile_path':m['profile_path'],
                                 'profile_sha1':m['profile_sha1'],'cutoff':m['cutoff'],'dates_ok':'','families_ok':'',
                                 'identity_ok':'','summary_faithful':'','rank_relevant':'','statistics_status_ok':'',
                                 'verdict':'pending','reviewer':'','notes':'',
                                 'previous_profile_sha1':old['profile_sha1'],'previous_verdict':old['verdict'],
                                 'previous_notes':old['notes'],'revision_action':new['retrieval_review_action']})
    csvfile(out/'profile_manifest.csv',man);csvfile(out/'change_ledger.csv',audit)
    csvfile(out/'quarantine_ledger.csv',quarantine_rows);csvfile(out/'profile_review_C.csv',review_queue)
    (out/'source_review').mkdir();(out/'source_review/profile_review_C_done.csv').write_bytes(a.review.read_bytes())
    (out/'source_review/C_PHASE1_FINDINGS.md').write_bytes((a.reviewed_root/'C_PHASE1_FINDINGS.md').read_bytes())
    rd=out/'C_re_review';rd.mkdir();links=[]
    for r in review_queue:
        key=(r['sample_id'],r['setting']);p=json.loads((out/r['profile_path']).read_text())
        name='_'.join(key)+'.html';links.append('<li><a href="'+name+'">'+'/'.join(key)+'</a></li>')
        body='<h1>'+html.escape('/'.join(key))+'</h1><p>New candidate; re-review pending. D wording and team adoption pending.</p>'
        body+='<h2>Prior human finding</h2><p>'+html.escape(r['previous_verdict']+': '+r['previous_notes'])+'</p>'
        body+='<h2>B action</h2><p>'+html.escape(r['revision_action'])+'</p><h2>New model-facing block</h2><pre>'+html.escape(p['profile_text'])+'</pre>'
        for e in p['retrieved_cases']:
            body+='<h3>'+html.escape(e['episode_id'])+'</h3><pre>'+html.escape(json.dumps(e['evidence'],ensure_ascii=False,indent=2))+'</pre>'
        (rd/name).write_text('<!doctype html><meta charset="utf-8"><style>body{max-width:1100px;margin:30px auto;font:16px/1.5 sans-serif}pre{white-space:pre-wrap}</style>'+body)
    (rd/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>C re-review of changed candidates</h1><p>Fill profile_review_C.csv using NEW hashes. Original findings are preserved separately.</p><ul>'+''.join(links)+'</ul>')
    summary={'profiles':len(man),'D_cards_verified':len(cards),'C_selections_replayed':matched_selection,
             'C_source_package_missing_files':missing_c_files,
             'C_profile_texts_reproduced':matched_text,'C_original_review_rows_verified':len(reviews),
             'C_original_unresolved_rows':len(rejected)+1,'new_review_rows_pending':len(review_queue),
             'retrieval_blocks_withheld':sum(r['action']!='unchanged_D_pool_TFIDF_selection' for r in audit),
             'quarantined_retrieval_slots':len(quarantine_rows),'k3_profiles':sum(r['retrieved_k']==3 for r in man),
             'short_profiles':[{'sample_id':r['sample_id'],'setting':r['setting'],'retrieved_k':r['retrieved_k']} for r in man if r['retrieved_k']<3],
             'statistics_only_profiles':sum(r['retrieved_k']==0 for r in man),'max_tokens':max(r['token_count'] for r in man),
             'api_calls':0,'frozen':False,'phase2_started':False,
             'coverage_policy_status':'user_accepted_partial_k_and_statistics_only',
             'attribution_policy_status':'user_clarified_A_contact_paragraph_handling_examiner_rule',
             'restored_episode_id':'ex_2acc44e527:13482424:2014-11-25:I5XVMRV0PXXIFW4',
             'pending':['D confirmation that source statistics need no numerical change','C re-review of global attribution labels and restored example','team release and fallback decision'],
             'source_files_sha1':{'D_case_episodes':filehash(a.d/'case_episodes.csv'),'D_cards':filehash(a.d/'stats_cards.jsonl'),
                                  'C_review':filehash(a.review),'C_prompt':digest(template),'builder':filehash(Path(__file__))}}
    atomic_json(out/'build_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
