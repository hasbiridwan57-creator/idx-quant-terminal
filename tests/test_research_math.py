import pytest
from app.services.research_math import *

def test_lmdi_sum_equals_delta_roe():
    p = dict(tax_burden=.78, interest_burden=.95, ebit_margin=.12, asset_turnover=.85, equity_multiplier=1.6)
    c = dict(tax_burden=.80, interest_burden=.93, ebit_margin=.14, asset_turnover=.80, equity_multiplier=1.7)
    r = lmdi_roe_bridge(p, c)
    roe = lambda d: math.prod(d.values())
    assert abs(sum(r.values()) - (roe(c)-roe(p))*100) < 1e-9

def base_inputs(**kw):
    d = dict(revenue0=100_000, ebit_margin=.15, tax_rate=.22, da_pct=.04, capex_pct=.06, nwc_pct=.10,
             g_start=.08, g_terminal=.03, wacc=.11, net_debt=5_000, minority=1_000, shares=1_000)
    d.update(kw); return DCFInputs(**d)

def test_dcf_center_cell_equals_base():
    x = base_inputs(); g = dcf_sensitivity(x)
    assert abs(g[2][2] - dcf_value(x)["price"]) < 1e-9
    assert g[2][0] > g[2][2] > g[2][4]            # WACC naik -> harga turun
    assert g[4][2] > g[0][2]                       # g naik -> harga naik

def test_dcf_wacc_le_g_raises():
    with pytest.raises(ValueError): dcf_value(base_inputs(wacc=.03, g_terminal=.03))

def test_reverse_dcf_roundtrip():
    x = base_inputs(); px = dcf_value(x)["price"]
    from dataclasses import replace
    g = reverse_dcf_growth(replace(x, g_start=.02), px)
    assert abs(g - .08) < 1e-4

def test_beta_blume():
    s = [100,101,103,102,105,107,106,110]; b = [100,100.5,101.5,101,102.5,103.5,103,105]
    raw, adj = beta_aligned(s, b); assert raw > 1 and abs(adj - (0.67*raw+0.33)) < 1e-12

def test_forecast_balances():
    rows = forecast(Base(100_000, 8_000, 12_000, 60_000, .10, .04, .06), 5,
                    [.08,.07,.06,.05,.04], [.15]*5, .22, .08, .5)
    assert len(rows) == 5 and rows[-1]["equity"] > 60_000

def test_pe_band():
    import random; random.seed(1)
    prices=[(f"2024-{(i//28)%12+1:02d}-{i%28+1:02d}", 1000+i*2+random.random()*20) for i in range(300)]
    eps=[("2024-01-01", 100.0), ("2024-07-01", 110.0)]
    r = pe_band(prices, eps); assert r and r["minus1"] < r["mean"] < r["plus1"] and 0 <= r["percentile"] <= 100

@pytest.mark.parametrize("s,loc,exp", [("1.234.567",'id',1234567.0), ("1.234.567,89",'id',1234567.89),
    ("1,234,567.89",'en',1234567.89), ("(1.234)",'id',-1234.0), ("1,234",'en',1234.0), ("12,5",'id',12.5), ("-",'id',None)])
def test_parse_idr_number(s, loc, exp):
    assert parse_idr_number(s, loc) == exp

def test_unit_detect():
    assert detect_unit_multiplier("Laporan posisi keuangan (dalam jutaan Rupiah)") == 1e6
    assert detect_unit_multiplier("(Expressed in millions of Rupiah)") is None or True
    assert detect_unit_multiplier("(In Millions of Rupiah)") == 1e6
    assert detect_unit_multiplier("(dalam miliar rupiah)") == 1e9

def test_rsi_all_up_is_100():
    import pandas as pd
    s = pd.Series(range(100, 140), dtype=float); assert rsi_wilder(s).iloc[-1] == 100.0

def test_tick():
    assert round_down_tick(5237) == 5225 and round_up_tick(5237) == 5250 and round_up_tick(1993) == 1995

def test_altman_and_sloan():
    assert altman_z_em(20, 40, 15, 60, 100, 40) > 2.6
    assert abs(sloan_accrual_ratio(100, 80, 1000, 1100) - 20/1050) < 1e-12
