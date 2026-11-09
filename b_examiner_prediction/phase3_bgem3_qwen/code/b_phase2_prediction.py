"""B-only phase 2: immutable release, original adapters, private local artifacts.

prepare/offline require no credentials. dev must pass on the actual endpoint
before core. No generation task, no retrieval rebuilding, no automatic publishing.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

import b_prediction as bp
import b_qwen as bq
from b_run_paced import paced_transport

B = Path(__file__).resolve().parent
RELEASE = B/'outputs/profile_phase1_v4_reviewed'
ROOT = B/'outputs/phase2_prediction_v4_reviewed'
PROMPT = B/'prompts/examiner_prediction.FROZEN.txt'
CORE = B/'prepared/inputs/prediction_core.jsonl'
DEV = B/'prepared_dev/inputs/prediction_dev.jsonl'
MANIFEST = B.parent/'shared/data_package/data_v1_share/sample_manifest.csv'
CASES = B.parent/'shared/profile_corpus_v2/profile_corpus/cases.csv'
D_CARDS = B.parent/'shared/D_phase1_v1_handoff/D_phase1_v1/stats_cards.jsonl'
TEAM_ZIP = B/'outputs/B_D_C_phase1_v4_reviewed.zip'
TYPE_GOLD = B/'prepared/gold/action_type_gold.core.draft.csv'
RAW_GROUND = B/'prepared/gold/claim_ground_gold.core.draft.jsonl'
SCORING_GROUND = B/'outputs/core/claim_ground_gold.scoring.draft.jsonl'
TAXONOMY_ISSUES = B/'outputs/core/gold_taxonomy_issues.json'
PROFILE_HEADER = '\n\nEXAMINER PROFILE (past, other families):\n'
MODELS = ('gpt', 'qwen')
VARIANTS = ('own', 'mismatched')
RELEASE_ID = 'B_D_C_v4_reviewed_2026_11_02'


def sha1(text):
    return hashlib.sha1(text.encode()).hexdigest()


def fh(path, algorithm='sha256'):
    return hashlib.new(algorithm, Path(path).read_bytes()).hexdigest()


def csvrows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def append_profile(base, profile, provenance, variant):
    require(profile['prediction_sample_id'] == base['sample_id'] and profile['cutoff'] == base['cutoff'],
            'Profile identity/cutoff mismatch')
    text = profile['profile_text']
    require(sha1(text) == provenance.get('profile_text_sha1'), 'Profile text hash mismatch')
    # Only profile_text enters messages. All control/review/identity fields stay outside.
    return {**base, 'input_setting': variant,
            'base_user_message_hash': hashlib.sha256(base['user_message'].encode()).hexdigest(),
            'profile_hash': hashlib.sha256(text.encode()).hexdigest(),
            'profile_provenance': provenance,
            'user_message': base['user_message'] + PROFILE_HEADER + text}


def scoring_gold():
    types=csvrows(TYPE_GOLD); raw=bp.index(bp.read_jsonl(RAW_GROUND))
    grounds=bp.read_jsonl(SCORING_GROUND); issues=json.loads(TAXONOMY_ISSUES.read_text())
    require(issues['protocol_changed'] is False, 'Scoring taxonomy changed')
    conflicts={r['sample_id']:r for r in issues['issues']}
    require(set(conflicts)=={'14012315_t1'}, 'Unexpected historical taxonomy exclusions')
    require(set(bp.index(grounds))==set(raw), 'Scoring/raw ground IDs mismatch')
    for row in grounds:
        sample=row['sample_id']; original=raw[sample]
        if sample in conflicts:
            invalid=[pair for pair in original['pairs'] if pair[1] not in bp.GROUNDS]
            require(invalid==conflicts[sample]['invalid_pairs'] and row['pairs'] is None
                    and row['review_status']=='taxonomy_conflict_pending_review', 'Taxonomy exclusion changed')
        else:
            require(row==original, 'Scoring gold differs from raw outside documented exclusion')
    return types,grounds


def eligibility(types, grounds, families):
    ground_index = bp.index(grounds)
    require(set(ground_index) == {r['sample_id'] for r in types}, 'Gold IDs differ')
    out = []
    for r in types:
        s = r['sample_id']; valid = bp.flag(r['eligible']); pairs = ground_index[s]['pairs']
        reason = '' if valid else ('out_of_scope:'+r['next_type'] if r['next_type'] not in bp.TYPE_MAP else 'uncertain_or_censored')
        out.append({'sample_id':s, 'family_id':families[s], 'type_eligible':valid,
                    'type_exclusion':reason, 'ground_eligible':valid and pairs is not None,
                    'ground_exclusion':reason or (('taxonomy_conflict:112d' if ground_index[s].get('review_status')=='taxonomy_conflict_pending_review' else 'unknown_ground_label') if pairs is None else ''),
                    'ground_label_status':ground_index[s].get('ground_label_status','unknown' if pairs is None else 'parsed'),
                    'next_type':r['next_type'], 'occurrence':r['occurrence']})
    return out


def baseline_path(model):
    return B/('outputs/core/examiner_prediction.jsonl' if model=='gpt' else 'outputs/qwen36_27b/core/examiner_prediction.jsonl')


def frozen_path(model):
    return B/('frozen_setting.json' if model=='gpt' else 'outputs/qwen36_27b/frozen_setting.json')


def adapter_hash(model):
    return fh(B/'b_prediction.py') if model=='gpt' else bq.implementation_hash()


def audit_baseline(model, inputs):
    rows = bp.read_jsonl(baseline_path(model)); ri = bp.index(rows); ii = bp.index(inputs)
    require(set(ri)==set(ii), model+': baseline IDs mismatch')
    frozen = json.loads(frozen_path(model).read_text()); ph = fh(PROMPT)
    require(ph==frozen['prompt_hash'], 'Frozen prompt changed')
    configs = {bp.canonical(r['configuration']) for r in rows}
    require(len(configs)==1, model+': heterogeneous baseline configuration')
    configuration = rows[0]['configuration']
    require(configuration['implementation_hash']==adapter_hash(model), 'Original adapter changed')
    for key,value in frozen['config'].items():
        require(configuration.get(key)==value, model+': frozen config mismatch '+key)
    for s,row in ii.items():
        r=ri[s]
        require(r['status']=='success' and r['finish_reason']=='stop', model+': incomplete baseline '+s)
        require(r['model']==frozen['config']['expected_model'], 'Baseline model mismatch')
        require(r['input_setting']=='no_profile' and r['profile_hash'] is None, 'Profile baseline contaminates control')
        require(r['prompt_hash']==ph, 'Baseline prompt mismatch')
        for k in ('app_id','cutoff','input_hash','state_hash','state_input_hash','state_prompt_hash','missing_doc_ids'):
            require(r[k]==row[k], model+': baseline provenance mismatch '+s+'/'+k)
        require(r['base_user_message_hash']==hashlib.sha256(row['user_message'].encode()).hexdigest(), 'Base message changed')
        request=bp.digest({'messages':messages(row),'config':configuration,
                           'provenance':{k:v for k,v in row.items() if k!='user_message'}})
        require(request==r['request_hash'], model+': baseline request mismatch '+s)
        bp.validate_prediction(r['prediction'])
    return {'model':model,'verified_success_n':len(rows),'baseline_path':str(baseline_path(model)),
            'baseline_sha256':fh(baseline_path(model)),'configuration':configuration,
            'frozen_sha256':fh(frozen_path(model))}


def messages(row):
    return [{'role':'system','content':PROMPT.read_text()}, {'role':'user','content':row['user_message']}]


def check_release():
    release=json.loads((RELEASE/'RELEASE_MANIFEST.json').read_text())
    require(release['release_id']==RELEASE_ID, 'Unexpected release')
    manifest=json.loads((RELEASE/'HANDOFF_MANIFEST_SHA256.json').read_text())
    for entry in manifest['files']:
        p=bp.safe_path(RELEASE,entry['path'])
        require(p.is_file() and p.stat().st_size==entry['bytes'] and fh(p)==entry['sha256'], 'Snapshot changed: '+entry['path'])
    require(fh(RELEASE/'profile_manifest.csv')==release['profile_manifest_sha256'], 'Release manifest changed')
    require(fh(RELEASE/'prompts/profile_block.txt','sha1')==release['prompt_sha1'], 'Shared block template changed')
    require(fh(D_CARDS,'sha1')==release['D_source_cards_sha1'], 'D source card file changed')
    cards={(r['sample_id'],r['variant']):r for r in bp.read_jsonl(D_CARDS)}
    with zipfile.ZipFile(TEAM_ZIP) as archive:
        prefix='B_D_C_phase1_v4_reviewed/'
        for entry in manifest['files']:
            require(hashlib.sha256(archive.read(prefix+entry['path'])).hexdigest()==entry['sha256'], 'Team ZIP differs from locked directory')
        require(archive.read(prefix+'HANDOFF_MANIFEST_SHA256.json')==(RELEASE/'HANDOFF_MANIFEST_SHA256.json').read_bytes(), 'ZIP manifest changed')
    case_index=bp.index(csvrows(CASES)); profiles={}; coverage=Counter()
    for r in csvrows(RELEASE/'profile_manifest.csv'):
        p=bp.safe_path(RELEASE,r['profile_path']); v=json.loads(p.read_text()); key=(r['sample_id'],r['setting'])
        require(key not in profiles, 'Duplicate profile')
        require(fh(p,'sha1')==r['profile_sha1'], 'Profile file changed')
        require(sha1(v['profile_text'])==r['profile_text_sha1']==v['profile_text_sha1'], 'Profile text changed')
        card=cards[key]
        require(v['card_sha1']==v['D_card_sha1']==r['card_sha1']==r['D_card_sha1']==card['card_sha1'], 'Card hash mismatch')
        require(v['statistics']==card['stats'] and v['shrunk_statistics']==card['shrunk'] and v['D_original_card_text']==card['card_text'], 'D source content changed')
        require(v['cutoff']==r['cutoff']==case_index[r['sample_id']]['cutoff'], 'A cutoff mismatch')
        require(v['target_examiner_id']==case_index[r['sample_id']]['examiner_id'], 'A examiner mismatch')
        require(v['setting']==r['setting'] and v['sample_id']==r['sample_id'], 'Profile mapping mismatch')
        require(v['retrieved_k']==int(r['retrieved_k'])==len(v['retrieved_cases']), 'Actual k mismatch')
        profiles[key]=(v,r); coverage[str(v['retrieved_k'])]+=1
    require(len(profiles)==300 and dict(coverage)==release['actual_k_counts'], 'Profile coverage changed')
    return profiles, {'release_id':RELEASE_ID, 'snapshot_files_verified':len(manifest['files']),
                      'profiles_verified':len(profiles),'actual_k_counts':dict(coverage),
                      'release_manifest_sha256':fh(RELEASE/'RELEASE_MANIFEST.json'),
                      'handoff_manifest_sha256':fh(RELEASE/'HANDOFF_MANIFEST_SHA256.json'),
                      'team_zip_sha256':fh(TEAM_ZIP),'team_zip_matches_snapshot':True}


def dev_rows():
    rows=bp.read_jsonl(DEV); require(len(rows)==3, 'Expected three original dev inputs')
    out=[]
    for i,row in enumerate(rows):
        text=('FORMAT CHECK ONLY: empty examiner history; no qualified historical profile supplied.' if i==0 else
              'SYNTHETIC FORMAT EXAMPLE ONLY. This is invented placeholder text, not empirical examiner history. '
              'Historical statistics: unavailable. Retrieved historical episodes: none. '
              'No claims, grounds, frequencies or examiner tendencies may be inferred from this placeholder.')
        profile={'prediction_sample_id':row['sample_id'],'cutoff':row['cutoff'],'profile_text':text}
        out.append(append_profile(row,profile,{'profile_sha1':None,'profile_text_sha1':sha1(text),
                    'card_sha1':None,'dev_fixture_kind':'empty' if i==0 else 'synthetic',
                    'empirical_history':False}, 'dev_format_only'))
    return out


def prepare():
    profiles,release=check_release(); core=bp.read_jsonl(CORE); ii=bp.index(core)
    manifest=bp.index(csvrows(MANIFEST)); selected={s for s,r in manifest.items() if bp.flag(r['test_core'])}
    require(set(ii)==selected and len(core)==100,'test_core differs from A manifest')
    families={s:manifest[s]['family_id'] for s in ii}
    require(all(families.values()), 'Missing family IDs; never fall back to sample IDs')
    types,grounds=scoring_gold()
    require(set(bp.index(types))==set(ii),'Gold/core IDs mismatch')
    eligible=eligibility(types,grounds,families)
    audits={m:audit_baseline(m,core) for m in MODELS}
    for variant in VARIANTS:
        rows=[]
        for row in core:
            p,r=profiles[(row['app_id'],variant)]
            require(row['sample_id']==p['prediction_sample_id'], 'Prediction/profile ID mismatch')
            provenance={k:r[k] for k in ('profile_path','profile_sha1','profile_text_sha1','card_sha1','retrieved_k')}
            provenance.update(release_id=RELEASE_ID,profile_root=str(RELEASE))
            rows.append(append_profile(row,p,provenance,variant))
        bp.jsonl(ROOT/'inputs'/f'{variant}.jsonl',rows)
    bp.jsonl(ROOT/'inputs/dev.jsonl',dev_rows())
    bp.csvfile(ROOT/'eligibility.csv',eligible)
    bp.atomic_json(ROOT/'baseline_reuse.json',audits)
    ground_index=bp.index(grounds)
    gold=[{**r,'pairs':ground_index[r['sample_id']]['pairs'],
           'ground_review_status':ground_index[r['sample_id']].get('review_status','automatic_unreviewed')} for r in types]
    bp.atomic_json(ROOT/'baseline_scores.json',{m:bp.score(gold,bp.read_jsonl(baseline_path(m))) for m in MODELS})
    locks={str(p):fh(p) for p in [CORE,DEV,PROMPT,MANIFEST,CASES,D_CARDS,TEAM_ZIP,
          ROOT/'baseline_reuse.json', ROOT/'eligibility.csv',
          TYPE_GOLD, RAW_GROUND, SCORING_GROUND, TAXONOMY_ISSUES,Path(__file__),
          B/'b_prediction.py',B/'b_qwen.py',B/'b_run_paced.py',*[frozen_path(m) for m in MODELS],
          *[baseline_path(m) for m in MODELS],*sorted((ROOT/'inputs').glob('*.jsonl'))]}
    summary={**release,'scope':['no_profile','own','mismatched'],'artunit':'deferred_optional_not_run',
             'core_input_n':len(core),'type_eligible_n':sum(r['type_eligible'] for r in eligible),
             'ground_eligible_n':sum(r['ground_eligible'] for r in eligible),
             'type_exclusions':{r['sample_id']:r['type_exclusion'] for r in eligible if not r['type_eligible']},
             'unknown_ground_ids':[r['sample_id'] for r in eligible if r['ground_exclusion']=='unknown_ground_label'],
             'ground_exclusions':{r['sample_id']:r['ground_exclusion'] for r in eligible if not r['ground_eligible']},
             'family_n':len(set(families.values())), 'family_source':str(MANIFEST),
             'family_limit':'A manifest family coverage only; not independently exhaustive',
             'dev_n':3,'dev_history':'empty/synthetic; no empirical retrieval efficacy check; no dev scoring',
             'bootstrap':{'n':1000,'seed':20261010,'unit':'family_id','paired':True,'ci':'percentile_95'},
             'budget_matching':'not claimed; original model-specific inference settings preserved',
             'production_started':False,'locks':locks}
    bp.atomic_json(ROOT/'preflight.json',summary)
    return {k:v for k,v in summary.items() if k!='locks'}


def check_locks():
    summary=json.loads((ROOT/'preflight.json').read_text())
    for path,h in summary['locks'].items():
        require(fh(path)==h,'Prepared dependency changed; inspect and re-prepare: '+path)
    check_release()
    return summary


def invoke(model, inputs, output, transport=None):
    config=json.loads(frozen_path(model).read_text())['config']
    runner=bp.run if model=='gpt' else bq.run_qwen
    # Pin provenance before API call; interrupted attempts can always be joined.
    audit=json.loads((ROOT/'baseline_reuse.json').read_text())[model]
    config_record=audit['configuration']; source=bp.read_jsonl(inputs)
    provenance=[]
    for row in source:
        request=bp.digest({'messages':messages(row),'config':config_record,
                           'provenance':{k:v for k,v in row.items() if k!='user_message'}})
        provenance.append({'sample_id':row['sample_id'],'request_hash':request,
                           'profile_provenance':row['profile_provenance'],
                           'base_user_message_hash':row['base_user_message_hash'],
                           'profile_hash':row['profile_hash'], 'wrapper_sha256':fh(__file__),
                           'inputs_sha256':fh(inputs), 'configuration':config_record})
    output=Path(output); bp.jsonl(output/'request_provenance.jsonl',provenance)
    summary=runner(inputs,PROMPT,output,config,transport=transport)
    pi=bp.index(provenance); rows=bp.read_jsonl(output/'examiner_prediction.jsonl')
    for row in rows:
        prov=pi[row['sample_id']]
        require(row['request_hash']==prov['request_hash'],'Adapter request configuration drift')
        row.update(profile_provenance=prov['profile_provenance'],wrapper_sha256=prov['wrapper_sha256'])
    bp.jsonl(output/'examiner_prediction.with_provenance.jsonl',rows)
    return summary


def fixture_prediction():
    return {'p_second_oa':.7,'p_type':{'CTNF':.2,'CTFR':.5,'NOA':.3},
            'predicted_type':'CTFR','claim_ground_pairs':[[343,'103'],[344,'112b']]}


def offline():
    check_locks(); report=[]
    for model in MODELS:
        counts=Counter(); model_id=json.loads(frozen_path(model).read_text())['config']['expected_model']
        def send(payload):
            counts['calls']+=1
            sample=next(s for s in ('11968167','11968173','11968176') if 'Application '+s+'.' in payload['messages'][1]['content'])
            counts[sample]+=1; n=counts[sample]
            content=bp.canonical(fixture_prediction()); finish='stop'
            if sample=='11968173' and n==1:
                finish='length'; content='{"p_second_oa":'
            elif sample=='11968176':
                content='{"p_second_oa": 2}'
            return {'model':model_id,'choices':[{'finish_reason':finish,'message':{'content':content}}],
                    'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'simulated':True}}
        # New temporary output each time prevents prior mock cache hiding checks.
        with tempfile.TemporaryDirectory(prefix='b_phase2_mock_') as temporary:
            out=Path(temporary)
            invoke(model,ROOT/'inputs/dev.jsonl',out,send)
            rows=bp.read_jsonl(out/'examiner_prediction.with_provenance.jsonl')
            require([r['status'] for r in rows]==['success','success','failed'],'Unexpected fixture outcomes')
            budget_key='max_completion_tokens' if model=='gpt' else 'max_tokens'
            require(rows[1][budget_key]==16384,'Truncation did not increase retry budget')
            require(rows[2]['reason']=='invalid_json_or_schema_or_finish','Schema failure hidden')
            require(counts['calls']==5,'Unexpected mock retry count')
            before=counts['calls']; invoke(model,ROOT/'inputs/dev.jsonl',out,send)
            require(counts['calls']-before==2,'Successful results not reused on resume')
            # Verify exception paths without storing exception messages or credentials.
            def failed_send(payload):
                raise RuntimeError('simulated transport failure')
            error_out=out/'transport_failure'
            invoke(model,ROOT/'inputs/dev.jsonl',error_out,failed_send)
            errors=bp.read_jsonl(error_out/'examiner_prediction.with_provenance.jsonl')
            require(all(r['reason']=='api_error' and r['prediction'] is None for r in errors),'API failure not explicit')
            bp.jsonl(ROOT/'offline_checks'/model/'simulated_results.jsonl',rows)
            bp.jsonl(ROOT/'offline_checks'/model/'simulated_usage.jsonl',bp.read_jsonl(out/'usage_log.jsonl'))
            report.append({'model':model,'sample_ids':[r['sample_id'] for r in rows],
                           'dev_cases':3,'initial_simulated_calls':5,'resume_simulated_calls':2,
                           'checks':['exact_base_prefix','only_profile_text_appended','JSON_and_probability_validation',
                                     'high_claim_and_allowed_grounds','length_retry_16384','invalid_schema_failure',
                                     'api_failure','cache_resume','profile_and_request_hash_join'],
                           'status':'PASS_OFFLINE_SIMULATED','live_dev_passed':False})
    result={'api_calls':0,'scored':False,'real_model_outputs':False,'models':report,
            'limitation':'Empty/synthetic fixtures check plumbing only. Live endpoint/model behavior still requires dev.'}
    bp.atomic_json(ROOT/'offline_checks/report.json',result)
    return result


def live(model, stage, interval=65):
    check_locks()
    require((ROOT/'offline_checks/report.json').exists(),'Run offline checks first')
    config=json.loads(frozen_path(model).read_text())['config']
    key=os.environ.get('QWEN_API_KEY') if model=='qwen' else None
    key=key or os.environ.get('AZURE_OPENAI_API_KEY')
    require(bool(key),'Missing '+('QWEN_API_KEY or AZURE_OPENAI_API_KEY' if model=='qwen' else 'AZURE_OPENAI_API_KEY'))
    if stage=='core':
        gate=json.loads((ROOT/'runs'/model/'dev/live_gate.json').read_text())
        require(gate['wrapper_sha256']==fh(__file__) and gate['dev_inputs_sha256']==fh(ROOT/'inputs/dev.jsonl')
                and gate['success_n']==3 and gate['prompt_sha256']==fh(PROMPT), 'Live dev gate invalid')
    old=os.environ.get('AZURE_OPENAI_API_KEY');os.environ['AZURE_OPENAI_API_KEY']=key
    try:
        send=paced_transport(bp.azure_transport(config),interval)
        if stage=='dev':
            out=ROOT/'runs'/model/'dev'
            summary=invoke(model,ROOT/'inputs/dev.jsonl',out,send)
            if summary['success_n']==3:
                bp.atomic_json(out/'live_gate.json',{'success_n':3,'scored':False,
                     'wrapper_sha256':fh(__file__),'dev_inputs_sha256':fh(ROOT/'inputs/dev.jsonl'),
                     'prompt_sha256':fh(PROMPT),'run_id':summary['run_id']})
            return summary
        summaries={}
        for variant in VARIANTS:
            summaries[variant]=invoke(model,ROOT/'inputs'/f'{variant}.jsonl',ROOT/'runs'/model/variant,send)
        return summaries
    finally:
        if old is None:os.environ.pop('AZURE_OPENAI_API_KEY',None)
        else:os.environ['AZURE_OPENAI_API_KEY']=old


def paired_comparison(gold, left, right, n_boot=1000):
    import numpy as np
    from sklearn.metrics import roc_auc_score, f1_score
    gi=bp.index(gold)
    eligible=[s for s,r in gi.items() if bp.flag(r['eligible'])]
    common=[s for s in eligible if left.get(s,{}).get('status')=='success' and right.get(s,{}).get('status')=='success']
    for s in common:
        bp.validate_prediction(left[s]['prediction']); bp.validate_prediction(right[s]['prediction'])
    require(bool(common),'No paired eligible successful outputs')
    families=sorted({gi[s]['family_id'] for s in common}); fi={f:i for i,f in enumerate(families)}
    group=np.array([fi[gi[s]['family_id']] for s in common]); y=np.array([int(gi[s]['occurrence']) for s in common])
    true_types=np.array([bp.TYPE_MAP.get(gi[s]['next_type'],gi[s]['next_type']) for s in common])
    known=np.array([gi[s]['pairs'] is not None for s in common])
    def arrays(results):
        probs=[];types=[];counts=[]
        for s in common:
            r=results[s]['prediction']; probs.append(r['p_second_oa']);types.append(r['predicted_type'])
            truth=set(map(tuple,gi[s]['pairs'] or []));pred=set(map(tuple,r['claim_ground_pairs']))
            counts.append([len(truth&pred),len(pred-truth),len(truth-pred)])
        return np.array(probs),np.array(types),np.array(counts)
    la,ra=arrays(left),arrays(right)
    def metrics(a,w):
        mask=w>0; p,t,c=a
        occ=float(roc_auc_score(y[mask],p[mask],sample_weight=w[mask])) if len(set(y[mask]))==2 else None
        typ=float(f1_score(true_types[mask],t[mask],labels=list(bp.TYPES),average='macro',zero_division=0,sample_weight=w[mask])) if mask.any() else None
        tp,fp,fn=(c*w[:,None]*known[:,None]).sum(axis=0);denom=2*tp+fp+fn
        return {'Occ':occ,'Type':typ,'Grnd':float(2*tp/denom) if denom else None}
    lpoint,rpoint=metrics(la,np.ones(len(common))),metrics(ra,np.ones(len(common)))
    rng=np.random.default_rng(20261010); draws={k:[] for k in lpoint}
    for _ in range(n_boot):
        multiplicity=np.bincount(rng.integers(0,len(families),size=len(families)),minlength=len(families))
        w=multiplicity[group]; lm,rm=metrics(la,w),metrics(ra,w)
        for k in draws:
            if lm[k] is not None and rm[k] is not None:draws[k].append(rm[k]-lm[k])
    result={}
    for k in draws:
        delta=None if lpoint[k] is None or rpoint[k] is None else rpoint[k]-lpoint[k]
        result[k]={'left':lpoint[k],'right':rpoint[k],'delta':delta,
                   'ci95':np.quantile(draws[k],[.025,.975]).tolist() if delta is not None and draws[k] else None,
                   'valid_bootstrap_n':len(draws[k]),'undefined_bootstrap_n':n_boot-len(draws[k])}
    return {'paired_n':len(common),'paired_ground_n':int(known.sum()),'family_n':len(families),
            'paired_ids':common,'paired_ground_ids':[s for s,k in zip(common,known) if k],
            'failed_or_missing_ids':[s for s in eligible if s not in common],
            'bootstrap_n':n_boot,'seed':20261010,'unit':'family_id','ci_method':'paired_percentile_95',
            'delta_direction':'right_minus_left','metrics':result}


def compare():
    check_locks(); manifest=bp.index(csvrows(MANIFEST)); types,ground_rows=scoring_gold(); grounds=bp.index(ground_rows)
    gold=[{**r,'pairs':grounds[r['sample_id']]['pairs'],'family_id':manifest[r['sample_id']]['family_id']}
          for r in types]
    results={}
    for model in MODELS:
        conditions={'no_profile':bp.index(bp.read_jsonl(baseline_path(model)))}
        for v in VARIANTS:
            path=ROOT/'runs'/model/v/'examiner_prediction.with_provenance.jsonl'
            conditions[v]=bp.index(bp.read_jsonl(path))
            expected=bp.index(bp.read_jsonl(ROOT/'inputs'/f'{v}.jsonl'))
            require(set(conditions[v])==set(expected),'Output IDs must cover exactly 100 core inputs')
            provenance=bp.index(bp.read_jsonl(ROOT/'runs'/model/v/'request_provenance.jsonl'))
            for s,r in conditions[v].items():
                e=expected[s]; base=conditions['no_profile'][s]
                expected_request=bp.digest({'messages':messages(e),'config':base['configuration'],
                        'provenance':{k:value for k,value in e.items() if k!='user_message'}})
                require(r['profile_provenance']==e['profile_provenance'] and r['request_hash']==provenance[s]['request_hash']==expected_request, 'Profile provenance mismatch')
                require(r['profile_hash']==e['profile_hash'] and r['input_setting']==v,'Output condition/hash mismatch')
                require(r['configuration']==base['configuration'] and r['prompt_hash']==base['prompt_hash'], 'Paired configuration mismatch')
                for k in ('state_hash','state_input_hash','input_hash','base_user_message_hash'):
                    require(r[k]==base[k],'Paired base mismatch '+k)
                if r['status']=='success':require(r['model']==base['model'],'Paired model mismatch')
        # A single complete-case cohort across all three conditions prevents changing denominators by contrast.
        complete={s for s in conditions['no_profile'] if all(conditions[v][s]['status']=='success' for v in conditions)}
        shared_gold=[r for r in gold if r['sample_id'] in complete]
        contrasts={}
        for l,r in [('no_profile','own'),('no_profile','mismatched'),('mismatched','own')]:
            contrasts[r+'_minus_'+l]=paired_comparison(shared_gold,conditions[l],conditions[r])
        results[model]={'all_conditions_success_n':len(complete),'incomplete_ids':sorted(set(conditions['no_profile'])-complete),
                        'contrasts':contrasts,'gold_status':'automatic_unreviewed; existing scoring definition preserved'}
    bp.atomic_json(ROOT/'comparison.json',results)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','offline','dev','core','compare'])
    parser.add_argument('--model',choices=MODELS)
    parser.add_argument('--interval',type=float,default=65)
    args=parser.parse_args()
    if args.command in ('dev','core'):
        require(args.model is not None,'--model required for live calls')
        result=live(args.model,args.command,args.interval)
    else:result={'prepare':prepare,'offline':offline,'compare':compare}[args.command]()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
