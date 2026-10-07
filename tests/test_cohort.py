import pytest
from prosecution_data.cohort import FamilyGraph, candidate_round, select_applications


def test_family_keeps_excluded_and_pct_bridge_and_stable_ids():
    g=FamilyGraph()
    g.link('12000001','PCT/US2007/000001')
    g.link('12000002','PCT/US2007/000001')
    g.link('12000002','11000000')
    assert g.family('12000001')==g.family('12000002')=='11000000'
    assert g.family('13000000')=='13000000'
    assert g.component_size('12000001')==4


def test_normalization_preserves_leading_zero_and_rejects_scientific_notation():
    g=FamilyGraph()
    g.link('01/234,567','01234568')
    assert g.family('01234568')=='01234567'
    with pytest.raises(ValueError):g.link('1.234E7','01234568')


def test_candidate_stops_at_nina_and_is_unverified():
    r=candidate_round([('2011-08-01','MCTNF'),('2011-11-29','A...'),('2011-12-06','NINA'),('2011-12-13','A...'),('2012-02-17','MCTFR')],'2022-06-23')
    assert r['cutoff']=='2011-11-29'
    assert r['next_event']=='NINA'
    assert r['exclusion_reason']=='other'
    assert not r['eligible_cls']


def test_candidate_does_not_take_reply_after_second_action():
    r=candidate_round([('2011-08-01','MCTNF'),('2011-09-01','MCTFR'),('2011-11-29','A.NE')],'2022-06-23')
    assert r['exclusion_reason']=='no_reply_before_intervening_event'


def test_same_day_response_codes_need_source_verification():
    r=candidate_round([('2011-08-01','MCTNF'),('2011-11-29','A...'),('2011-11-29','A/RR'),('2012-02-17','MCTFR')],'2022-06-23')
    assert r['reply_group_uncertain']


def test_selection_is_deterministic_and_utility_public_only():
    rows=[dict(application_number=str(12000000+i),filing_date='2010-01-01',application_invention_type='Utility',earliest_pgpub_number='USX',patent_number='') for i in range(5)]
    rows += [dict(rows[0],application_number='14000000',application_invention_type='Design')]
    rows += [dict(rows[0],application_number='14000001',earliest_pgpub_number='')]
    a,_=select_applications(iter(rows),2,42,set())
    b,_=select_applications(iter(reversed(rows)),2,42,set())
    assert a==b
    assert len(a)==2
    assert all(r['app_id'] not in ['14000000','14000001'] for r in a)


def test_cli_builds_auditable_candidate_pool(tmp_path):
    import csv,json,subprocess,sys
    raw=tmp_path/'raw';raw.mkdir()
    (raw/'application_data.csv').write_text('application_number,filing_date,application_invention_type,earliest_pgpub_number,patent_number\n12000001,2010-01-01,Utility,USX,\n')
    (raw/'transactions.csv').write_text('application_number,event_code,recorded_date\n12000001,MCTNF,2010-02-01\n12000001,A...,2010-03-01\n12000001,MCTFR,2010-04-01\n')
    (raw/'continuity_parents.csv').write_text('application_number,parent_application_number\n12000001,PCT/US2007/000001\n11000001,PCT/US2007/000001\n')
    (raw/'continuity_children.csv').write_text('application_number,child_application_number\n')
    pilot=tmp_path/'pilot.csv';pilot.write_text('app_id\n11000001\n')
    out=tmp_path/'output'
    subprocess.run([sys.executable,'-m','prosecution_data.cohort','--raw-dir',str(raw),'--output-dir',str(out),'--limit','2','--observation-end','2022-06-23','--pilot-labels',str(pilot)],check=True)
    with (out/'training_candidates.csv').open() as f:rows=list(csv.DictReader(f))
    assert len(rows)==1 and rows[0]['occurrence']=='1'
    assert rows[0]['family_id']=='11000001'
    assert rows[0]['eligible_cls']=='False'
    audit=json.loads((out/'audit.json').read_text())
    assert audit['source_snapshot_date'] is None
    assert audit['transaction_rows_scanned']==3


def test_candidate_output_schema_is_identical_with_or_without_reply():
    missing=candidate_round([], '2022-06-23')
    observed=candidate_round([('2011-08-01','MCTNF'),('2011-11-29','A...'),('2012-02-17','MCTFR')], '2022-06-23')
    assert set(missing)==set(observed)
