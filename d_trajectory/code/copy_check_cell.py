# Copy check (no API): does the LLM just repeat a number it can read off its examiner block?
#   card runs    -> compared with the card's median days to the next letter (and its "allowed within 24 months")
#   history runs -> compared with the plain-math median of the same 3 past applications (history_math.py)
import json, glob, os, pandas as pd
O = os.path.join(ROOT, 'outputs', 'D')
def rows(f):
    p = os.path.join(O, f)
    return {r['sample_id']: r for r in map(json.loads, open(p)) if r.get('status') == 'ok'} if os.path.exists(p) else {}
gold = pd.read_csv(os.path.join(ROOT, 'gold', 'rounds_next_gold.csv'), dtype={'sample_id': str}).set_index('sample_id')
card = {}
for v in ['own', 'mismatched']:
    for p in glob.glob(f'{PKG}/candidate_profiles/{v}/*.json'):
        s = json.load(open(p)); st = s['statistics']
        card[(s['sample_id'], v)] = dict(days=st['next_letter']['median_days_km'], a24=st['first_reply']['allowed_by_24m'])
out = []
for M in ['gpt-5-mini', 'qwen3.6-27b']:
    for kind in ['profile', 'history']:
        for v in ['own', 'mismatched']:
            Q = rows(f'rounds_next_predictions_{M}_state_{kind}_{v}.jsonl')
            if not Q:
                continue
            if kind == 'profile':
                ref = {s: card[(s, v)]['days'] for s in Q if card.get((s, v), {}).get('days')}
                shown = 'card median days'
            else:
                H = rows(f'rounds_next_predictions_history_math_{v}.jsonl')
                ref = {s: H[s]['next_days_pred'] for s in Q if s in H and H[s].get('n_usable_apps')}
                shown = 'math median of the 3 histories'
            ids = list(ref)
            d = pd.DataFrame(dict(llm=[Q[s]['next_days_pred'] for s in ids], ref=[ref[s] for s in ids],
                                  true=[gold.loc[s, 'next_days'] for s in ids]))
            row = dict(method=f'{M} + {v} {"card" if kind == "profile" else "histories"}', compared_with=shown, n=len(d),
                       days_exactly_equal=round((d.llm == d.ref).mean(), 3),
                       days_within_3=round(((d.llm - d.ref).abs() <= 3).mean(), 3),
                       days_rank_corr_with_ref=round(d.llm.corr(d.ref, method='spearman'), 3),
                       days_rank_corr_with_truth=round(d.llm.corr(d.true, method='spearman'), 3))
            T = rows(f'trajectory_predictions_{M}_state_{kind}_{v}.jsonl')
            if kind == 'profile' and T:
                t = pd.DataFrame([dict(F24=T[s]['F_allowance'][-1], c=card[(s, v)]['a24']) for s in T if (s, v) in card])
                row['allow24_rank_corr_with_card'] = round(t.F24.corr(t.c, method='spearman'), 3)
            out.append(row)
for name in ['prior_own', 'history_math_own']:
    Q = rows(f'rounds_next_predictions_{name}.jsonl')
    if Q:
        d = pd.DataFrame([dict(p=r['next_days_pred'], t=gold.loc[s, 'next_days']) for s, r in Q.items()])
        out.append(dict(method=name + ' (no LLM)', n=len(d), days_rank_corr_with_truth=round(d.p.corr(d.t, method='spearman'), 3)))
display(pd.DataFrame(out))
R = rows('rounds_next_predictions_gpt-5-mini_state_history_own.jsonl')
if R:
    txt = pd.Series({s: (r.get('rationale') or '') for s, r in R.items()})
    print('GPT + own histories: share of rationales that mention the past applications:',
          round(txt.str.lower().str.contains('past application|examiner|histor').mean(), 2))
    print(txt.sample(3, random_state=0).str[:300].to_string())
