"""Prepare an unverified metadata pool and stable continuity-family groups."""
import argparse
import csv
from datetime import date
import hashlib
import heapq
import json
from pathlib import Path
import re
import time

from .pilot import MAIL, OTHER, PROCEDURE, next_event_candidate
from .schemas import normalize_application_number


class FamilyGraph:
    """Global connected components, including out-of-cohort and PCT nodes."""
    def __init__(self):
        self.parent={}
        self.sizes={}
        self.minimum={}

    @staticmethod
    def normalize(value):
        text=str(value).strip().upper()
        if re.fullmatch(r'PCT/[A-Z]{2}\d{2,4}/\d+', text):
            return text
        return normalize_application_number(text)

    def find(self, value):
        node=self.normalize(value)
        if node not in self.parent:
            self.parent[node]=node;self.sizes[node]=1;self.minimum[node]=node
        root=node
        while self.parent[root]!=root:root=self.parent[root]
        while node!=root:
            previous=self.parent[node];self.parent[node]=root;node=previous
        return root

    def link(self, left, right):
        # Normalize both before mutating, so invalid edges cannot partially join.
        left,right=self.normalize(left),self.normalize(right)
        a,b=self.find(left),self.find(right)
        if a==b:return
        if self.sizes[a]<self.sizes[b]:a,b=b,a
        self.parent[b]=a
        self.sizes[a]+=self.sizes.pop(b)
        self.minimum[a]=min(self.minimum[a],self.minimum.pop(b))

    def family(self, value):return self.minimum[self.find(value)]
    def component_size(self, value):return self.sizes[self.find(value)]


def select_applications(rows, limit, seed, excluded, date_from='2008-01-01',date_to='2015-12-31'):
    if limit<1:raise ValueError('limit must be positive')
    start,end=date.fromisoformat(date_from),date.fromisoformat(date_to)
    if start>end:raise ValueError('date range reversed')
    heap=[];counts={'application_rows':0,'eligible_rows':0,'invalid_rows':0}
    for row in rows:
        counts['application_rows']+=1
        try:
            app=normalize_application_number(row['application_number'])
            filed=date.fromisoformat(row['filing_date'])
        except (ValueError,KeyError):
            counts['invalid_rows']+=1;continue
        if app in excluded or not start<=filed<=end or row.get('application_invention_type')!='Utility':continue
        if not (row.get('earliest_pgpub_number','').strip() or row.get('patent_number','').strip()):continue
        counts['eligible_rows']+=1
        rank=int(hashlib.sha256(f'{seed}:{app}'.encode()).hexdigest(),16)
        item=(-rank,app,dict(app_id=app,filing_date=filed.isoformat(),public_evidence='publication_or_patent_id',application_type='Utility'))
        if len(heap)<limit:heapq.heappush(heap,item)
        elif item[:2]>heap[0][:2]:heapq.heapreplace(heap,item)
    selected=[item[2] for item in sorted(heap,key=lambda x:x[1])]
    if len({r['app_id'] for r in selected})!=len(selected):raise ValueError('Duplicate selected application IDs')
    return selected,counts


REPLIES={'A...','A/RR','A.NE','AAF.'}


def candidate_round(events, observation_end):
    end=date.fromisoformat(observation_end)
    ordered=sorted(set((d,c) for d,c in events if d and date.fromisoformat(d)<=end))
    result={'o1_mail_date':'','o1_type':'','cutoff':'','next_event_raw':'','next_event':'','next_event_date':'','occurrence':'',
            'eligible_cls':False,'label_status':'metadata_candidate','requires_document_verification':True,
            'reply_group_uncertain':False,'exclusion_reason':''}
    actions=[(d,c) for d,c in ordered if c in ('MCTNF','MCTFR')]
    if not actions:
        result['exclusion_reason']='no_mailed_o1';return result
    o1,code=actions[0]
    result.update(o1_mail_date=o1,o1_type=MAIL[code])
    if len({c for d,c in actions if d==o1})>1:
        result['exclusion_reason']='o1_ordering_uncertain';return result
    subsequent=[(d,c) for d,c in ordered if d>o1 and c in REPLIES|set(MAIL)|OTHER|PROCEDURE]
    if not subsequent:
        result['exclusion_reason']='no_observed_reply';return result
    first_date=subsequent[0][0]
    first_codes={c for d,c in subsequent if d==first_date}
    if not first_codes<=REPLIES:
        result['exclusion_reason']='no_reply_before_intervening_event';return result
    result.update(cutoff=first_date,reply_group_uncertain=len(first_codes)>1)
    next_result=next_event_candidate(ordered,first_date,observation_end)
    next_result.pop('source_snapshot_date')
    result.update(next_result)
    return result


def write_csv(path, rows, fields):
    with Path(path).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--limit',type=int,default=1000)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--observation-end',required=True,help='Analysis bound; NOT a source snapshot assertion')
    parser.add_argument('--pilot-labels',required=True)
    args=parser.parse_args()
    date.fromisoformat(args.observation_end)
    raw=Path(args.raw_dir);out=Path(args.output_dir)
    if out.exists():raise ValueError('Use a new output directory')
    start=time.monotonic()
    with Path(args.pilot_labels).open() as f:pilot=list(csv.DictReader(f))
    pilot_ids={r['app_id'] for r in pilot}
    print('Selecting utility/public-record candidates...',flush=True)
    with (raw/'application_data.csv').open(newline='') as f:
        selected,counters=select_applications(csv.DictReader(f),args.limit,args.seed,pilot_ids)
    target={r['app_id'] for r in selected}|pilot_ids
    print(f'Selected {len(selected)} pool candidates; building global family graph...',flush=True)
    graph=FamilyGraph();edges=invalid=0
    for name,column in [('continuity_parents.csv','parent_application_number'),('continuity_children.csv','child_application_number')]:
        with (raw/name).open(newline='') as f:
            for r in csv.DictReader(f):
                try:graph.link(r['application_number'],r[column]);edges+=1
                except ValueError:invalid+=1
    family_rows=[dict(app_id=app,family_id=graph.family(app),component_nodes=graph.component_size(app),family_resolution='continuity_graph' if graph.component_size(app)>1 else 'singleton_in_local_continuity',scope='pilot' if app in pilot_ids else 'candidate_pool') for app in sorted(target)]
    out.mkdir(parents=True)
    write_csv(out/'family_map.csv',family_rows,list(family_rows[0]))
    families={r['app_id']:r['family_id'] for r in family_rows}
    del graph
    print('Scanning transactions for selected IDs...',flush=True)
    by_app={app:[] for app in target};n=matched=0
    with (raw/'transactions.csv').open('rb') as f,(out/'selected_transactions.csv').open('wb') as w:
        w.write(next(f))
        for line in f:
            n+=1
            app=line.split(b',',1)[0].decode('ascii')
            if app in target:
                w.write(line);matched+=1
                _,code,d=line.decode().rstrip().split(',')
                by_app[app].append((d,code))
    candidates=[{**r,'sample_id':r['app_id']+'_t1_candidate','family_id':families[r['app_id']],**candidate_round(by_app[r['app_id']],args.observation_end)} for r in selected]
    if candidates:write_csv(out/'training_candidates.csv',candidates,list(candidates[0]))
    histogram={}
    for r in candidates:
        status=r['exclusion_reason'] or 'binary_candidate_pending_verification'
        histogram[status]=histogram.get(status,0)+1
    report=dict(**counters,selected_applications=len(selected),continuity_edges_read=edges,invalid_continuity_edges=invalid,
                transaction_rows_scanned=n,selected_transaction_rows=matched,elapsed_seconds=round(time.monotonic()-start,2),
                observation_end=args.observation_end,source_snapshot_date=None,seed=args.seed,candidate_status_counts=histogram,
                limitations=['Not the shared evaluation sample; not stratified by technology center.',
                             'Reply groups, document completeness, event mappings and source version require verification.',
                             'Families use all valid edges from both local continuity files including PCT bridges; unrecognized IDs are counted.',
                             'Future shared sample families must be excluded from training after A provides its list.',
                             'No training, test split or model scores produced.'])
    (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
