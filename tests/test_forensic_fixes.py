"""Test Beneish M-Score & interpretasi CCC.

Regresi untuk bug nyata yang pernah terjadi:
  1. TATA dihitung dari ΔCash, bukan CFO -> M-Score meledak ke -16.884.
  2. Koefisien LVGI salah tanda & orde (0.0327 vs -0.327).
  3. CCC negatif selalu dilabeli "Excellent" meski DPO ekstrem (distress).
"""
import pytest

from app.services.forensic_accounting import compute_beneish_m_score
from app.services.working_capital import interpret_ccc


def _fy(**over):
    base = {
        "year": 2025,
        "revenue_bn": 1000.0,
        "net_income_parent_bn": 100.0,
        "cfo_bn": 120.0,
        "assets_bn": 2000.0,
        "liabilities_bn": 800.0,
        "cash_bn": 300.0,
        "trade_receivables_bn": 200.0,
        "cost_of_sales_bn": 600.0,
        "inventories_bn": 150.0,
        "selling_expense_bn": 50.0,
        "ga_expense_bn": 40.0,
        "depreciation_amortization_bn": 80.0,
    }
    base.update(over)
    return base


def test_beneish_uses_cfo_not_delta_cash():
    """TATA = (NI - CFO)/TA, bukan (NI - ΔCash)/TA."""
    cur = _fy(year=2025)
    prev = _fy(year=2024, net_income_parent_bn=90.0, cfo_bn=100.0, cash_bn=250.0)
    r = compute_beneish_m_score(cur, prev)
    expected_tata = (100.0 - 120.0) / 2000.0
    assert abs(r["components"]["tata"] - round(expected_tata, 3)) < 0.005


def test_beneish_score_in_plausible_range():
    """M-Score harus berada di rentang wajar (-6..+4), bukan -16.884."""
    cur = _fy(year=2025)
    prev = _fy(year=2024, net_income_parent_bn=90.0, cfo_bn=100.0)
    r = compute_beneish_m_score(cur, prev)
    assert -6.0 < r["m_score"] < 4.0


def test_beneish_lvgi_coefficient_is_negative():
    """LVGI harus MENGURANGI skor (koefisien -0.327), bukan menambah."""
    low = compute_beneish_m_score(
        _fy(year=2025, liabilities_bn=200.0),
        _fy(year=2024, liabilities_bn=200.0),
    )
    high = compute_beneish_m_score(
        _fy(year=2025, liabilities_bn=1900.0),
        _fy(year=2024, liabilities_bn=200.0),
    )
    # Leverage naik tajam -> M-Score harus LEBIH KECIL (lebih aman menurut Beneish)
    assert high["m_score"] < low["m_score"]


def test_beneish_na_cfo_does_not_explode():
    """Tanpa CFO, TATA netral 0.0 — skor tetap wajar, bukan meledak."""
    cur = _fy(year=2025, cfo_bn=None)
    prev = _fy(year=2024)
    r = compute_beneish_m_score(cur, prev)
    assert r["components"]["tata"] == 0.0
    assert -6.0 < r["m_score"] < 4.0


def test_ccc_negative_low_dpo_is_efficient():
    r = interpret_ccc(-20.0, dpo=45.0)
    assert "Efisien" in r["label"]
    assert r["tone"] == "good"


def test_ccc_negative_high_dpo_is_warning():
    """DPO 205 hari + CCC negatif = tunggakan, bukan efisiensi (kasus WSKT)."""
    r = interpret_ccc(-136.4, dpo=204.9)
    assert "Waspada" in r["label"]
    assert r["tone"] == "warn"
    assert "205" in r["note"]


def test_ccc_none_is_na():
    r = interpret_ccc(None)
    assert r["label"] == "N/A"
