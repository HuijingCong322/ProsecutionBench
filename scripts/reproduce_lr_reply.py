"""Reproduce the current exploratory reply-informed LR from frozen features."""
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

FEATURES = ('days_filing_to_o1', 'days_o1_to_reply', 'a1_remarks_characters',
            'a1_claim_change_present', 'a1_canceled_status_present')


def claim_flags(text):
    """A1 listing status proxies; missing markup is unknown, never zero."""
    if text is None:
        return '', ''
    changed = bool(re.search(r'<(?:ins|del)\b|\((?:currently\s+amended|amended|new)\)', text, re.I))
    canceled = bool(re.search(r'\b\d+(?:\s*[-–]\s*\d+)?\s*[.)]?\s*\(\s*cancel(?:l)?ed\s*\)', text, re.I))
    return int(changed), int(canceled)


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def main():
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.exceptions import ConvergenceWarning
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/reproduced_lr_reply')
    args = parser.parse_args()
    source = ROOT/'results/week_2026_10_05'
    labels = read(source/'experiment_labels.csv')
    groups = validate_split(labels, read(source/'split_manifest.csv'), '2013-12-31')
    rows = read(source/'lr_reply/features.csv')
    features = {r['sample_id']: r for r in rows}
    assert len(features) == len(rows)
    assert set(features) == set(groups['train'] + groups['test'])
    assert all(set(r) == {'sample_id', *FEATURES} for r in rows)
    assert all(r[f] in ('0', '1', '') for r in rows for f in FEATURES[-2:])
    indexed = {r['sample_id']: r for r in labels}
    def matrix(ids):
        values = np.array([[float(features[k][f]) if features[k][f] else np.nan for f in FEATURES] for k in ids])
        observed = values[~np.isnan(values)]
        assert np.isfinite(observed).all() and (observed >= 0).all()
        return values
    train, test = groups['train'], groups['test']
    model = make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True),
                          StandardScaler(), LogisticRegression(C=1, solver='lbfgs', max_iter=1000, random_state=42))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(matrix(train), [int(indexed[k]['occurrence']) for k in train])
    probabilities = dict(zip(test, map(float, model.predict_proba(matrix(test))[:, list(model[-1].classes_).index(1)])))
    metrics = score_predictions({k:int(indexed[k]['occurrence']) for k in test}, probabilities)
    expected = json.loads((source/'lr_reply/metrics.json').read_text())['lr_reply']
    assert all(abs(metrics[k]-expected[k]) < 1e-12 for k in metrics)
    frozen = {r['sample_id']:float(r['p_second_oa']) for r in read(source/'lr_reply/lr_reply_predictions.csv')}
    assert set(frozen) == set(probabilities)
    assert all(abs(probabilities[k]-frozen[k]) < 1e-12 for k in frozen)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir/'predictions.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['sample_id', 'p_second_oa'], lineterminator='\n')
        writer.writeheader(); writer.writerows(dict(sample_id=k, p_second_oa=p) for k,p in probabilities.items())
    (args.output_dir/'metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
