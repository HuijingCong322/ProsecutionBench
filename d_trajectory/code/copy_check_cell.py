# Copy check (no API): does the LLM just repeat a number it was shown?
#   full profile   -> compared with the card's median days (and the card's "allowed within 24 months")
#   examples only  -> compared with the median of the example days, and with "equals one of the example days"
import json, glob, os, numpy as np, pandas as pd
O = os.path.join(ROOT, 'outputs', 'D')
def rows(f):
    p = os.path.join(O, f)
    return {r['sample_id']: r for r in map(json.loads, open(p)) if r.get('status') == 'ok'} if os.path.exists(p) else {}
card, ex = {}, {}
for v in ['own', 'mismatched']:
    for p in glob.glob(f'{PKG}/candidate_profiles/{v}/*.json'):
        s = json.load(open(p)); st = s['statistics']
        card[(s['sample_id'], v)] = dict(med=st['next_letter']['median_days_km'], a24=st['first_reply']['allowed_by_24m'])
        ex[(s['sample_id'], v)] = [int(x['elapsed_days']) for x in s.get('retrieved_cases') or []]
gold = pd.read_csv(os.path.join(ROOT, 'gold', 'rounds_next_gold.csv'), dtype={'sample_id': str}).set_index('sample_id')
out = []
for M in ['gpt-5-mini', 'qwen3.6-27b']:
    for name, v, kind in [(f'{M}_state_profile_own', 'own', 'card'), (f'{M}_state_profile_mismatched', 'mismatched', 'card'),
                          (f'{M}_state_profile_own_exonly', 'own', 'examples'), (f'{M}_state_profile_mismatched_exonly', 'mismatched', 'examples'),
                          (f'{M}_state', 'own', 'card')]:
        Q, T = rows(f'rounds_next_predictions_{name}.jsonl'), rows(f'trajectory_predictions_{name}.jsonl')
        if not Q:
            continue
        recs = []
        for s, r in Q.items():
            days = ex.get((s, v), [])
            ref = card[(s, v)]['med'] if kind == 'card' else (round(float(np.median(days))) if days else None)
            if ref:
                recs.append(dict(pred=r['next_days_pred'], ref=ref, true=gold.loc[s, 'next_days'],
                                 any_example=r['next_days_pred'] in days))
        d = pd.DataFrame(recs)
        row = dict(method=name, compared_with=('card median' if kind == 'card' else 'median of example days'), n=len(d),
                   rank_corr_with_shown_number=round(d.pred.corr(d.ref, method='spearman'), 3),
                   share_within_3_days=round((abs(d.pred - d.ref) <= 3).mean(), 3),
                   share_exactly=round((d.pred == d.ref).mean(), 3),
                   share_equals_an_example_day=round(d.any_example.mean(), 3),
                   rank_corr_with_truth=round(d.pred.corr(d.true, method='spearman'), 3))
        if T and kind == 'card':
            t = pd.DataFrame([dict(F24=T[s]['F_allowance'][-1], c=card[(s, v)]['a24']) for s in T if (s, v) in card])
            row['allow24_rank_corr_with_card'] = round(t.F24.corr(t.c, method='spearman'), 3)
        out.append(row)
for name in ['prior_own', 'exlookup_own']:
    Q = rows(f'rounds_next_predictions_{name}.jsonl')
    if Q:
        d = pd.DataFrame([dict(pred=r['next_days_pred'], true=gold.loc[s, 'next_days']) for s, r in Q.items()])
        out.append(dict(method=name + ' (no LLM)', n=len(d), rank_corr_with_truth=round(d.pred.corr(d.true, method='spearman'), 3)))
display(pd.DataFrame(out))
for name in ['gpt-5-mini_state_profile_own', 'gpt-5-mini_state_profile_own_exonly']:
    R = rows(f'rounds_next_predictions_{name}.jsonl')
    if R:
        txt = pd.Series({s: (r.get('rationale') or '') for s, r in R.items()})
        print(f'\n{name}: rationales mentioning examiner / median / history / example:',
              round(txt.str.lower().str.contains('examiner|median|histor|example').mean(), 2))
        print(txt.sample(3, random_state=0).str[:300].to_string())
