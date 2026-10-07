from prosecution_data.family_audit import classify_invalid, affected_families
from prosecution_data.cohort import FamilyGraph


def test_invalid_classification_does_not_guess_typos():
    assert classify_invalid('12000001','')['reason']=='missing_relative'
    row=classify_invalid('12000001','PCT/FR/89/0030')
    assert row['reason']=='pct_separator_variant'
    assert row['suggested_relative']=='PCT/FR89/0030'
    row=classify_invalid('12000001','PCT/USOA/05690')
    assert row['suggested_relative']==''
    assert row['reason']=='unrecognized_pct'


def test_indirect_family_is_flagged_by_invalid_edge():
    graph=FamilyGraph();graph.link('12000001','11000000')
    risks=affected_families(graph,[{'app_id':'11000000','relative_id':''}],['12000001','13000001'])
    assert risks['12000001']==1
    assert risks['13000001']==0
