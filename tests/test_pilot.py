import pytest
from prosecution_data.pilot import next_event_candidate, score_predictions


def test_nina_is_not_skipped():
    result = next_event_candidate([('2011-12-06','NINA'),('2012-02-17','MCTFR')], '2011-11-29', '2022-01-01')
    assert result['exclusion_reason'] == 'other'
    assert result['occurrence'] == ''


def test_processing_event_does_not_replace_mailing_date():
    result = next_event_candidate([('2010-05-06','CTFR'),('2010-05-07','MCTFR')], '2010-01-25', '2022-01-01')
    assert result['next_event_date'] == '2010-05-07'
    assert result['occurrence'] == 1


def test_no_mailing_record_requires_review():
    assert next_event_candidate([('2010-05-06','CTFR')], '2010-01-25', '2022-01-01')['exclusion_reason'] == 'missing_mailing_record'


def test_procedure_change_stops_search():
    assert next_event_candidate([('2010-02-01','RCEX'),('2010-03-01','MCTFR')], '2010-01-25', '2022-01-01')['exclusion_reason'] == 'out_of_scope'


def test_same_day_relevant_events_require_review():
    r=next_event_candidate([('2010-05-07','MCTFR'),('2010-05-07','MN/=.')], '2010-01-25', '2022-01-01')
    assert r['exclusion_reason']=='ordering_uncertain'


def test_scores_and_id_integrity():
    assert score_predictions({'a':1,'b':0}, {'a':0.8,'b':0.3}) == {'N':2,'Acc':1.0,'F1':1.0,'Brier':pytest.approx(0.065)}
    with pytest.raises(ValueError):score_predictions({'a':1,'b':0},{'a':0.8})
    with pytest.raises(ValueError):score_predictions({'a':1},{'a':float('nan')})


def test_cutoff_and_snapshot_validation():
    with pytest.raises(ValueError):next_event_candidate([], '2023-01-01','2022-01-01')


def test_real_three_cases_match_document_verification():
    import csv
    from pathlib import Path
    from collections import defaultdict
    grouped = defaultdict(list)
    fixture = Path(__file__).parent / 'fixtures/patex/three_verified_transactions.csv'
    with fixture.open() as f:
        for row in csv.DictReader(f):
            grouped[row['application_number']].append((row['recorded_date'], row['event_code']))
    expected = [
        ('11968167', '2010-01-25', 'CTFR', '2010-05-07', 1),
        ('11968176', '2008-06-16', 'NOA', '2008-07-03', 0),
        ('11968173', '2011-11-29', 'NINA', '2011-12-06', ''),
        ('11968173', '2011-12-13', 'CTFR', '2012-02-17', 1),
    ]
    for app, cutoff, event, event_date, occurrence in expected:
        result = next_event_candidate(grouped[app], cutoff, '2022-06-23')
        assert (result['next_event'], result['next_event_date'], result['occurrence']) == (event, event_date, occurrence)
