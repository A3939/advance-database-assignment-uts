"""Independent calendar oracle: observed bounds cannot invent absent months."""
from datetime import date
from arsia_pipeline.coverage_policy import fill_complete_months, complete_intervals, covers
from arsia_pipeline.date_bounds import MIN_YEAR, MAX_YEAR


def test_complete_month_zero_and_unknown_month_are_separate():
    known = {'crash_count':True,'fatalities':False}
    rows = [{'year':2024,'month':1,'crash_count':3,'fatalities':None}]
    actual = fill_complete_months(rows,[{'from':'2024-01-01','to':'2024-02-29'}],date(2024,1,1),date(2024,4,30),known)
    assert actual == [rows[0],{'year':2024,'month':2,'crash_count':0,'fatalities':None}]
    assert fill_complete_months(rows,[],date(2024,1,1),date(2024,4,30),known) == rows


def test_adjacent_complete_intervals_are_covered_but_a_gap_is_not():
    a={'from':'2024-01-01','to':'2024-01-31'};b={'from':'2024-02-01','to':'2024-02-29'}
    assert covers([b,a],'2024-01-01','2024-02-29')
    assert not covers([a,{'from':'2024-02-02','to':'2024-02-29'}],'2024-01-01','2024-02-29')


def test_declared_span_snapshot_flag_and_all_layer_membership_are_not_temporal_completeness():
    assert complete_intervals({'source':{'coverage':{'from':'2024-01-01','to':'2024-12-31'}},
        'update':{'mode':'snapshot'},'coverage_intervals':[{'from':'2024-01-01','to':'2024-12-31'}],
        'admission':{'evidence':{'source_completeness':{'status':'verified','scope':'whole_current_layer'}}}}) == []
    assert (MIN_YEAR,MAX_YEAR)==(1800,2200)
