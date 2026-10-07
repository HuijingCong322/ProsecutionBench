"""Conservative metadata candidates and shared pilot classification scoring.

Cutoffs must be supplied from verified replies. This module never certifies
reply completeness or generation eligibility from transaction rows.
"""
import argparse
import csv
from datetime import date
import json
import math
from pathlib import Path

MAIL = {'MCTNF':'CTNF','MCTFR':'CTFR','MN/=.':'NOA'}
OTHER = {'NINA','MCTAV','CTAV','EPQ.','CTEQ','CTRS','MCTRS','REST','MC/N=','MC/NW','MSEPQ','MSFR.','MSRNF'}
PROCEDURE = {'RCEX','N/AP','AP.B','ABN2','NABN','ABN3','EABN','EABA','AFWC'}
PROCESSING = {'CTNF','CTFR','N/=.'}


def next_event_candidate(events, cutoff, snapshot):
    start, end = date.fromisoformat(cutoff), date.fromisoformat(snapshot)
    if start > end:
        raise ValueError('cutoff exceeds source snapshot')
    parsed = [(date.fromisoformat(d), c) for d,c in events if d]
    parsed = [(d,c) for d,c in parsed if start <= d <= end]
    relevant = sorted(set((d,c) for d,c in parsed if c in MAIL or c in OTHER or c in PROCEDURE))
    result = {'cutoff':cutoff,'source_snapshot_date':snapshot,'next_event_raw':'','next_event':'',
              'next_event_date':'','occurrence':'','eligible_cls':False,
              'label_status':'metadata_candidate','requires_document_verification':True,
              'exclusion_reason':''}
    if not relevant:
        result['exclusion_reason'] = 'missing_mailing_record' if any(c in PROCESSING for _,c in parsed) else 'censored_or_missing'
        return result
    first = relevant[0][0]
    same = [c for d,c in relevant if d==first]
    result.update(next_event_raw=';'.join(same),next_event_date=first.isoformat())
    if first == start or len(same)>1:
        result['exclusion_reason']='ordering_uncertain'
        return result
    code=same[0]
    if code in MAIL:
        result.update(next_event=MAIL[code],occurrence=int(MAIL[code]!='NOA'))
    else:
        result.update(next_event=code,exclusion_reason='out_of_scope' if code in PROCEDURE else 'other')
    return result


def score_predictions(labels, probabilities):
    if not labels or set(labels)!=set(probabilities):
        raise ValueError('Nonempty labels and predictions must have exactly the same IDs')
    if any(y not in (0,1) for y in labels.values()):raise ValueError('Labels must be binary')
    if any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities.values()):raise ValueError('Probabilities must be finite and in [0,1]')
    tp=fp=fn=correct=0
    for key,y in labels.items():
        pred=int(probabilities[key]>=0.5)
        correct+=pred==y;tp+=pred==y==1;fp+=pred==1 and y==0;fn+=pred==0 and y==1
    return {'N':len(labels),'Acc':correct/len(labels),'F1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,
            'Brier':sum((probabilities[k]-y)**2 for k,y in labels.items())/len(labels)}


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def unique_values(rows, id_column, value_column, convert):
    values={}
    for r in rows:
        key=r[id_column]
        if not key or key in values:raise ValueError('Empty or duplicate ID: '+key)
        values[key]=convert(r[value_column])
    return values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    c=subs.add_parser('candidates');c.add_argument('--seeds',required=True);c.add_argument('--transactions',required=True);c.add_argument('--snapshot',required=True);c.add_argument('--output',required=True)
    s=subs.add_parser('score');s.add_argument('--labels',required=True);s.add_argument('--predictions',required=True);s.add_argument('--output',required=True)
    args=parser.parse_args()
    output=Path(args.output)
    if output.exists():raise ValueError('Refusing to overwrite '+str(output))
    if args.command=='candidates':
        seeds=read_rows(args.seeds)
        unique_values(seeds,'sample_id','cutoff',date.fromisoformat)
        by_app={r['app_id']:[] for r in seeds}
        # Keep raw rows for audit, including processing and unknown event codes.
        audit=output.with_suffix('.transactions.csv')
        if audit.exists():raise ValueError('Refusing to overwrite '+str(audit))
        output.parent.mkdir(parents=True,exist_ok=True)
        with Path(args.transactions).open(newline='',encoding='utf-8-sig') as f,audit.open('w',newline='') as a:
            reader=csv.DictReader(f);writer=csv.DictWriter(a,fieldnames=['application_number','event_code','recorded_date']);writer.writeheader()
            for r in reader:
                app=r['application_number']
                if app in by_app:
                    writer.writerow({k:r[k] for k in writer.fieldnames})
                    by_app[app].append((r['recorded_date'],r['event_code']))
        rows=[{'sample_id':r['sample_id'],'app_id':r['app_id'],**next_event_candidate(by_app[r['app_id']],r['cutoff'],args.snapshot)} for r in seeds]
        with output.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    else:
        rows=[r for r in read_rows(args.labels) if r.get('eligible_cls','').lower() in ('true','1','yes')]
        labels=unique_values(rows,'sample_id','occurrence',int)
        predictions=unique_values(read_rows(args.predictions),'sample_id','p_second_oa',float)
        result=score_predictions(labels,predictions)
        result.update(threshold=0.5,positive_class=1,n_positive=sum(labels.values()),n_negative=len(labels)-sum(labels.values()))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
    print(output)


if __name__=='__main__':main()
