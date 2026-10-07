"""Reproduce the fixed exploratory content LR from frozen feature rows."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import re
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from prosecution_data.baselines import validate_split
from prosecution_data.pilot import score_predictions

FEATURES = ('days_filing_to_o1', 'days_o1_to_reply', 'o1_has_101',
            'o1_has_102', 'o1_has_103', 'o1_has_112', 'o1_body_characters')
USC = r'35\s*U\s*\.?\s*S\s*\.?\s*C\s*\.?(?:\s*[§:]+)?'
PATTERN = re.compile(r'(?:\brejected\s+under\b|\brejections?\s+(?:under\b|[-–—:]\s*))\s*(?:' + USC + r'\s*)?(?P<section>10[123]|112)(?!\d)', re.I)

def extract_content(text):
    clean = re.sub(r'\s+', ' ', text).strip()
    sections = {m.group('section') for m in PATTERN.finditer(clean)}
    return {**{'o1_has_' + str(n): int(str(n) in sections) for n in (101, 102, 103, 112)},
            'o1_body_characters': len(clean)}

def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def main():
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.exceptions import ConvergenceWarning
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/reproduced_lr_content')
    args = parser.parse_args()
    source = ROOT/'results/week_2026_10_05'
    labels = read(source/'experiment_labels.csv')
    splits = read(source/'split_manifest.csv')
    groups = validate_split(labels, splits, '2013-12-31')
    feature_rows = read(source/'lr_content/features.csv')
    features = {r['sample_id']: r for r in feature_rows}
    assert len(features) == len(feature_rows)
    assert set(features) == set(groups['train'] + groups['test'])
    assert all(set(r) == {'sample_id', *FEATURES} for r in feature_rows)
    assert all(r[f] in ('0', '1') for r in feature_rows for f in FEATURES[2:6])
    indexed = {r['sample_id']: r for r in labels}
    def matrix(ids):
        result = np.array([[float(features[k][f]) if features[k][f] else float('nan')
                            for f in FEATURES] for k in ids])
        assert np.isfinite(result).all() and (result >= 0).all()
        return result
    train, test = groups['train'], groups['test']
    model = make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True),
                          StandardScaler(), LogisticRegression(C=1, solver='lbfgs',
                          max_iter=1000, random_state=42))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(matrix(train), [int(indexed[k]['occurrence']) for k in train])
    probabilities = dict(zip(test, map(float, model.predict_proba(matrix(test))[:, list(model[-1].classes_).index(1)])))
    truth = {k: int(indexed[k]['occurrence']) for k in test}
    metrics = score_predictions(truth, probabilities)
    expected = json.loads((source/'lr_content/metrics.json').read_text())['lr_content']
    assert all(abs(metrics[k]-expected[k]) < 1e-12 for k in metrics)
    frozen = {r['sample_id']: float(r['p_second_oa']) for r in read(source/'lr_content/lr_content_predictions.csv')}
    assert set(frozen) == set(probabilities)
    assert all(abs(probabilities[k]-frozen[k]) < 1e-12 for k in frozen)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir/'predictions.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['sample_id', 'p_second_oa'], lineterminator='\n')
        w.writeheader(); w.writerows(dict(sample_id=k, p_second_oa=p) for k, p in probabilities.items())
    (args.output_dir/'metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
    print(json.dumps(metrics, indent=2))

if __name__ == '__main__':
    main()
