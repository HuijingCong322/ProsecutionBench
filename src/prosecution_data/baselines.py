"""Leakage-checked Majority/LR pilot baselines with fixed date-interval features."""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import warnings

from .pilot import read_rows, score_predictions

FEATURES = ('days_filing_to_o1', 'days_o1_to_reply')


def _indexed(rows):
    result = {}
    for row in rows:
        key = row.get('sample_id', '').strip()
        if not key or key in result:
            raise ValueError('Empty or duplicate sample_id: ' + key)
        result[key] = row
    return result


def _eligible(row):
    return str(row.get('eligible_cls', '')).lower() in ('true', 'yes', '1')


def validate_split(labels, splits, train_observation_end):
    """Validate an explicit split; never generate or tune it from test outcomes."""
    end = date.fromisoformat(train_observation_end)
    indexed = _indexed(labels)
    eligible = {k:r for k,r in indexed.items() if _eligible(r)}
    manifest = _indexed(splits)
    if not eligible or set(eligible) != set(manifest):
        raise ValueError('Split must cover exactly all classification-eligible label IDs')
    groups = {'train':[], 'test':[]}
    family_partition = {}
    application_partition = {}
    for key, row in eligible.items():
        entry = manifest[key]
        partition = entry.get('split')
        if partition not in groups:
            raise ValueError('Only explicit train/test partitions are supported')
        if row.get('scope') != 'main' or row.get('label_status') != 'document_verified':
            raise ValueError('Only document-verified main labels may enter this experiment')
        family = row.get('family_id', '').strip()
        if not family or family.lower() in ('unknown', 'unavailable', 'pending'):
            raise ValueError('Verified family_id is required: ' + key)
        if family != entry.get('family_id') or row['cutoff'] != entry.get('cutoff'):
            raise ValueError('Split family/cutoff does not match labels: ' + key)
        app = row.get('app_id', '').strip()
        if not app:
            raise ValueError('app_id is required')
        for identity, assignments in [(family, family_partition), (app, application_partition)]:
            previous = assignments.setdefault(identity, partition)
            if previous != partition:
                raise ValueError('Family or application overlaps train and test')
        cutoff = date.fromisoformat(row['cutoff'])
        available = date.fromisoformat(row['label_available_date'])
        if available <= cutoff:
            raise ValueError('Next-event label must become available after cutoff')
        if row.get('occurrence') not in ('0','1',0,1):
            raise ValueError('Only binary labels are supported')
        if partition == 'train' and (cutoff > end or available > end):
            raise ValueError('Training input or label exceeds training observation end')
        if partition == 'test' and cutoff <= end:
            raise ValueError('Test cutoff must follow training observation end')
        groups[partition].append(key)
    if not groups['train'] or not groups['test']:
        raise ValueError('Both train and test must be nonempty')
    return {name: sorted(keys) for name, keys in groups.items()}


def build_features(labels, filing_dates):
    """Use only filing date and source-verified O1/reply dates, never snapshot status."""
    _indexed(labels)
    result = []
    for row in labels:
        cutoff = date.fromisoformat(row['cutoff'])
        o1 = date.fromisoformat(row['o1_mail_date'])
        if o1 > cutoff:
            raise ValueError('O1 is later than reply cutoff')
        filed = filing_dates.get(row['app_id'], '')
        interval = ''
        if filed:
            filed = date.fromisoformat(filed)
            if filed > o1:
                raise ValueError('Filing date is later than O1')
            interval = str((o1-filed).days)
        result.append(dict(sample_id=row['sample_id'],days_filing_to_o1=interval,
                           days_o1_to_reply=str((cutoff-o1).days)))
    return result


def train_baselines(labels, splits, features, train_observation_end):
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    groups = validate_split(labels, splits, train_observation_end)
    indexed = _indexed(labels)
    feature_rows = _indexed(features)
    ids = set(groups['train'] + groups['test'])
    if ids != set(feature_rows):
        raise ValueError('Features must cover exactly train/test IDs')
    values = {}
    for key, row in feature_rows.items():
        if set(row) != {'sample_id', *FEATURES}:
            raise ValueError('Feature columns must match the fixed whitelist')
        vector = []
        for name in FEATURES:
            raw = row[name]
            value = float(raw) if str(raw).strip() else float('nan')
            if str(raw).strip() and (not math.isfinite(value) or value < 0):
                raise ValueError('Nonmissing intervals must be finite and nonnegative')
            vector.append(value)
        values[key] = vector
    train, test = groups['train'], groups['test']
    y_train = np.array([int(indexed[k]['occurrence']) for k in train])
    if set(y_train.tolist()) != {0,1}:
        raise ValueError('LR training requires both classes')
    x_train = np.array([values[k] for k in train], dtype=float)
    x_test = np.array([values[k] for k in test], dtype=float)
    if np.isnan(x_train).all():
        raise ValueError('Training has no observed feature values')
    model = make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),
                          StandardScaler(), LogisticRegression(C=1.0,solver='lbfgs',max_iter=1000,random_state=42))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(x_train,y_train)
    positive = list(model[-1].classes_).index(1)
    probabilities = model.predict_proba(x_test)[:,positive]
    prior = float(y_train.mean())
    predictions = {'majority':{k:prior for k in test},
                   'lr':{k:float(p) for k,p in zip(test,probabilities)}}
    truth = {k:int(indexed[k]['occurrence']) for k in test}
    metrics = {method:score_predictions(truth, probs) for method,probs in predictions.items()}
    preprocessing = {'imputer_medians':model[0].statistics_.tolist(),
                     'scaler_mean':model[1].mean_.tolist(), 'scaler_scale':model[1].scale_.tolist()}
    return dict(predictions=predictions,metrics=metrics,preprocessing=preprocessing,model=model,
                train_ids=train,test_ids=test,train_positive_prior=prior,
                train_counts={'N':len(train),'positive':int(y_train.sum()),'negative':int(len(train)-y_train.sum())},
                test_counts={'N':len(test),'positive':sum(truth.values()),'negative':len(test)-sum(truth.values())})


def _write_csv(path, rows, fields):
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    f=subs.add_parser('features');f.add_argument('--labels',required=True);f.add_argument('--application-data',required=True);f.add_argument('--output',required=True)
    t=subs.add_parser('train');t.add_argument('--labels',required=True);t.add_argument('--split',required=True);t.add_argument('--features',required=True);t.add_argument('--train-observation-end',required=True);t.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    labels=read_rows(args.labels)
    if args.command=='features':
        labels=[r for r in labels if _eligible(r)]
        if not labels:raise ValueError('No classification-eligible labels')
        target=Path(args.output)
        if target.exists():raise ValueError('Refusing to overwrite '+str(target))
        needed={r['app_id'] for r in labels};filing={}
        with Path(args.application_data).open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                app=row['application_number']
                if app in needed:
                    if app in filing and filing[app]!=row['filing_date']:
                        raise ValueError('Conflicting filing dates: '+app)
                    filing[app]=row['filing_date']
        rows=build_features(labels,filing)
        target.parent.mkdir(parents=True,exist_ok=True)
        _write_csv(target,rows,['sample_id',*FEATURES])
        print(target)
        return
    import joblib
    import sklearn
    target=Path(args.output_dir)
    if target.exists():raise ValueError('Output directory already exists; use a new run directory')
    result=train_baselines(labels,read_rows(args.split),read_rows(args.features),args.train_observation_end)
    target.mkdir(parents=True)
    for method, probs in result['predictions'].items():
        _write_csv(target/(method+'_predictions.csv'),[dict(sample_id=k,p_second_oa=p) for k,p in probs.items()],['sample_id','p_second_oa'])
    (target/'metrics.json').write_text(json.dumps(result['metrics'],indent=2)+'\n')
    joblib.dump(result['model'],target/'lr_model.joblib')
    config={k:v for k,v in result.items() if k not in ('predictions','metrics','model')}
    config.update(features=list(FEATURES),threshold=0.5,positive_class=1,
                  sklearn_version=sklearn.__version__,train_observation_end=args.train_observation_end,
                  lr_parameters={'C':1.0,'solver':'lbfgs','max_iter':1000,'random_state':42},
                  input_sha256={name:hashlib.sha256(Path(path).read_bytes()).hexdigest() for name,path in [('labels',args.labels),('split',args.split),('features',args.features)]},
                  limitations=['Family IDs and document verification are asserted by input manifests; independently audit their provenance.',
                               'Two date-interval features only; no model or feature selection from test results.',
                               'Small or single-class test sets do not support stable effectiveness conclusions.'])
    (target/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    print(target)


if __name__=='__main__':main()
