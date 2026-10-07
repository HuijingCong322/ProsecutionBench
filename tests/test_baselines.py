import copy
import pytest
from prosecution_data.baselines import validate_split, train_baselines, build_features


def dataset():
    rows=[];splits=[];features=[]
    for i,(y,x) in enumerate([(0,10),(0,20),(1,100),(1,120),(0,25),(1,110)]):
        key=str(i);test=i>=4
        cutoff='2012-01-01' if test else '2010-01-01'
        rows.append(dict(sample_id=key,app_id=key,family_id='f'+key,cutoff=cutoff,label_available_date='2012-02-01' if test else '2010-02-01',occurrence=str(y),eligible_cls='True',label_status='document_verified',scope='main'))
        splits.append(dict(sample_id=key,family_id='f'+key,cutoff=cutoff,split='test' if test else 'train'))
        features.append(dict(sample_id=key,days_filing_to_o1=str(x),days_o1_to_reply='10'))
    return rows,splits,features


def test_valid_split_and_train_probability():
    labels,splits,features=dataset()
    result=train_baselines(labels,splits,features,'2011-01-01')
    assert set(result['predictions']['majority'])=={'4','5'}
    assert set(result['predictions']['majority'].values())=={0.5}
    assert result['predictions']['lr']['5']>result['predictions']['lr']['4']
    assert result['metrics']['lr']['N']==2


@pytest.mark.parametrize('change', ['family','future_label','unknown_family','cutoff','missing_test','duplicate'])
def test_rejects_split_leakage_and_misalignment(change):
    labels,splits,_=dataset()
    if change=='family':labels[-1]['family_id']='f0';splits[-1]['family_id']='f0'
    if change=='future_label':labels[0]['label_available_date']='2012-01-01'
    if change=='unknown_family':labels[0]['family_id']='';splits[0]['family_id']=''
    if change=='cutoff':splits[0]['cutoff']='2010-01-02'
    if change=='missing_test':splits.pop()
    if change=='duplicate':splits.append(splits[0])
    with pytest.raises(ValueError):validate_split(labels,splits,'2011-01-01')


def test_rejects_future_feature_and_missing_ids():
    labels,splits,features=dataset()
    features[0]['patent_issue_date']='2015-01-01'
    with pytest.raises(ValueError):train_baselines(labels,splits,features,'2011-01-01')
    del features[0]['patent_issue_date'];features.pop()
    with pytest.raises(ValueError):train_baselines(labels,splits,features,'2011-01-01')


def test_single_class_training_is_rejected():
    labels,splits,features=dataset()
    for r in labels[:4]:r['occurrence']='0'
    with pytest.raises(ValueError):train_baselines(labels,splits,features,'2011-01-01')


def test_preprocessing_uses_training_values_only():
    labels,splits,features=dataset()
    features[0]['days_filing_to_o1']=''
    first=train_baselines(labels,splits,features,'2011-01-01')
    features[-1]['days_filing_to_o1']='10000'
    second=train_baselines(labels,splits,features,'2011-01-01')
    assert first['preprocessing']==second['preprocessing']


def test_features_are_date_intervals_only():
    labels=[dict(sample_id='a',app_id='1',o1_mail_date='2010-01-11',cutoff='2010-01-21')]
    assert build_features(labels,{'1':'2010-01-01'})==[dict(sample_id='a',days_filing_to_o1='10',days_o1_to_reply='10')]
    with pytest.raises(ValueError):build_features(labels,{'1':'2010-02-01'})


def test_cli_training_outputs_reproducible_predictions(tmp_path):
    import csv
    import json
    import subprocess
    import sys
    from pathlib import Path
    labels,splits,features=dataset()
    paths=[]
    for name,rows in [('labels',labels),('split',splits),('features',features)]:
        p=tmp_path/(name+'.csv')
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        paths.append(p)
    out=tmp_path/'run'
    subprocess.run([sys.executable,'-m','prosecution_data.baselines','train','--labels',str(paths[0]),'--split',str(paths[1]),'--features',str(paths[2]),'--train-observation-end','2011-01-01','--output-dir',str(out)],check=True)
    metrics=json.loads((out/'metrics.json').read_text())
    assert metrics['lr']['N']==2
    with (out/'lr_predictions.csv').open() as f:
        assert {r['sample_id'] for r in csv.DictReader(f)}=={'4','5'}
    config=json.loads((out/'run_config.json').read_text())
    assert set(config['input_sha256'])=={'labels','split','features'}
    assert (out/'lr_model.joblib').exists()


def test_cli_features_excludes_noneligible_labels(tmp_path):
    import csv
    import subprocess
    import sys
    labels=tmp_path/'labels.csv'
    labels.write_text('sample_id,app_id,o1_mail_date,cutoff,eligible_cls\na,1,2010-01-11,2010-01-21,True\nb,2,2010-01-11,2010-01-21,False\n')
    apps=tmp_path/'apps.csv';apps.write_text('application_number,filing_date\n1,2010-01-01\n2,2010-01-01\n')
    out=tmp_path/'features.csv'
    subprocess.run([sys.executable,'-m','prosecution_data.baselines','features','--labels',str(labels),'--application-data',str(apps),'--output',str(out)],check=True)
    with out.open() as f:
        assert [r['sample_id'] for r in csv.DictReader(f)]==['a']
