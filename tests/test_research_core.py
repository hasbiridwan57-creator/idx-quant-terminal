import pytest
from app.services.research_core import *
from types import SimpleNamespace as NS

def stmt(**kw):
    d = dict(unit_multiplier=1e9, annualization_factor=1.0, revenue=100.0, ebit=20.0, ebt=18.0, net_income_parent=14.0,
             total_assets=200.0, total_liabilities=90.0, total_equity_parent=100.0, interest_bearing_debt=0.0,
             cash_and_equivalents=30.0, current_assets=None, current_liabilities=None, interest_expense=2.0,
             operating_cash_flow=16.0, capex=-8.0, depreciation=5.0, minority_interest=None)
    d.update(kw); return NS(**d)

def test_zero_debt_is_data_not_missing():
    v = build_view(stmt()); assert v.get("interest_bearing_debt").v == 0.0 and v.get("interest_bearing_debt").ok
    assert "interest_bearing_debt" not in v.missing and "current_assets" in v.missing

def test_units_millions_to_bn():
    v = build_view(stmt(unit_multiplier=1e6, revenue=50_000.0)); assert abs(v.get("revenue").v - 50.0) < 1e-9

def test_capex_abs_and_interim_annualized_only_flows():
    v = build_view(stmt(annualization_factor=4.0, unit_multiplier=1e9))
    assert v.get("capex").v == 32.0 and v.get("revenue").v == 400.0 and v.get("total_assets").v == 200.0
    assert v.get("revenue").src == "ESTIMATED" and v.get("total_assets").src == "REPORTED"

def test_rating_policy():
    assert rate(1000, 1250, .03, .11, [1200,1300,1250], 90)["rating"] == "BUY"
    assert rate(1000, 1050, .03, .11, [1000,1100,1050], 90)["rating"] == "HOLD"
    assert rate(1000, 950, .0, .11, [900,1000,950], 90)["rating"] == "SELL"
    assert rate(1000, 1250, .03, .11, [1200,1300], 40)["rating"] == "NOT RATED"
    assert rate(1000, 1250, .03, .11, [600,1900,1250], 90)["confidence"] == "LOW"

def test_risk_matrix_levels_and_missing():
    r = {x["code"]: x for x in risk_matrix(dict(nd_ebitda=3.0, icr=10, current_ratio=0.8, cfo_ni=None, pe_z=2.2, vol=.25, days_to_exit=0.5))}
    assert r["R1"]["level"] == 4 and r["R2"]["level"] == 1 and r["R3"]["level"] == 5
    assert r["R4"]["level"] is None and r["R4"]["label"] == "Data tidak tersedia" and r["R5"]["level"] == 5

def test_football_filters_incomplete():
    f = football([dict(method="DCF", low=900, mid=1000, high=1100), dict(method="PE", low=None, mid=None, high=None)], 950)
    assert len(f["rows"]) == 1 and f["blended_mid"] == 1000
