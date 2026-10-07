"""Reproduce the fixed internal time holdout from committed inputs."""
import csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from prosecution_data.baselines import train_baselines
def read(path):
    with path.open(newline='') as f:return list(csv.DictReader(f))
source=ROOT/'results/week_2026_10_05'
config=json.loads((source/'run_config.json').read_text())
result=train_baselines(read(source/'experiment_labels.csv'),read(source/'split_manifest.csv'),read(source/'features.csv'),config['train_observation_end'])
expected=json.loads((source/'metrics.json').read_text())
for method,metrics in result['metrics'].items():
    for name,value in metrics.items():
        assert abs(value-expected[method][name])<1e-8,(method,name,value,expected[method][name])
out=ROOT/'outputs/reproduced_week';out.mkdir(parents=True,exist_ok=False)
(out/'metrics.json').write_text(json.dumps(result['metrics'],indent=2)+'\n')
for method,probs in result['predictions'].items():
    with (out/(method+'_predictions.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['sample_id','p_second_oa']);w.writeheader()
        w.writerows(dict(sample_id=k,p_second_oa=p) for k,p in probs.items())
print(json.dumps(result['metrics'],indent=2))
