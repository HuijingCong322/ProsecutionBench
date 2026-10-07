"""Audit rejected continuity edges without correcting ambiguous identifiers."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import re
from .cohort import FamilyGraph, write_csv


def classify_invalid(app, relative):
    result={'reason':'','suggested_relative':''}
    try:FamilyGraph.normalize(app)
    except ValueError:
        result['reason']='invalid_application';return result
    text=relative.strip().upper()
    if not text:result['reason']='missing_relative'
    elif re.fullmatch(r'PCT/[A-Z]{2}/\d{2,4}/\d+',text):
        result['reason']='pct_separator_variant'
        result['suggested_relative']=re.sub(r'^PCT/([A-Z]{2})/',r'PCT/\1',text)
    elif text.startswith('PCT/'):result['reason']='unrecognized_pct'
    else:result['reason']='unrecognized_relative'
    return result


def affected_families(graph, invalid_rows, selected):
    counts=Counter()
    for row in invalid_rows:
        families=set()
        for value in [row['app_id'],row['relative_id']]:
            try:families.add(graph.family(value))
            except ValueError:pass
        counts.update(families)
    return {app:counts[graph.family(app)] for app in selected}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',required=True)
    parser.add_argument('--family-map',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();raw=Path(args.raw_dir);out=Path(args.output_dir)
    if out.exists():raise ValueError('Use a new output directory')
    with Path(args.family_map).open() as f:selected=list(csv.DictReader(f))
    graph=FamilyGraph();invalid=[];valid=0
    for name,column in [('continuity_parents.csv','parent_application_number'),('continuity_children.csv','child_application_number')]:
        print('Auditing '+name,flush=True)
        with (raw/name).open() as f:
            for number,row in enumerate(csv.DictReader(f),2):
                app,relative=row['application_number'],row[column]
                try:graph.link(app,relative);valid+=1
                except ValueError:
                    invalid.append(dict(source_file=name,csv_row=number,app_id=app,relative_id=relative,**classify_invalid(app,relative)))
    risks=affected_families(graph,invalid,[r['app_id'] for r in selected])
    rows=[]
    for row in selected:
        family=graph.family(row['app_id'])
        if family!=row['family_id']:raise ValueError('Existing family mapping does not match rebuilt graph')
        rows.append({**row,'invalid_edges_touching_component':risks[row['app_id']],
                     'family_review_status':'review_required' if risks[row['app_id']] else 'no_rejected_edge_touches_known_component'})
    out.mkdir(parents=True)
    write_csv(out/'invalid_edges.csv',invalid,['source_file','csv_row','app_id','relative_id','reason','suggested_relative'])
    write_csv(out/'family_review.csv',rows,list(rows[0]))
    summary=dict(valid_edges=valid,invalid_edges=len(invalid),invalid_by_reason=dict(Counter(r['reason'] for r in invalid)),
                 selected_applications=len(rows),affected_applications=sum(r['invalid_edges_touching_component']>0 for r in rows),
                 family_ids_match_prior_output=True,normalization_changes_applied=0,
                 limitations=['Risk detection uses recognized endpoints and known graph components. Unknown endpoints can hide additional links.',
                              'Suggestions are review aids, not automatically applied corrections.',
                              'Local continuity audit does not establish source snapshot or global family completeness.'])
    (out/'audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
