"""Test Altman Z'' dan Invested Capital — memastikan tidak ada angka karangan.

Prinsip yang diuji:
  1. Komponen hilang -> available=False, BUKAN angka pengganti.
  2. Bank -> tidak dihitung (unclassified balance sheet).
  3. Nilai benar secara aritmetika untuk input yang diketahui.
"""
import pytest

from app.services.cost_of_capital import compute_altman_z


def _row(**over):
    base = {
        "is_bank": False,
        "assets_bn": 1000.0,
        "current_assets_bn": 400.0,
        "current_liabilities_bn": 250.0,
        "retained_earnings_bn": 300.0,
        "ebit_bn": 120.0,
        "liabilities_bn": 600.0,
        "equity_parent_bn": 400.0,
    }
    base.update(over)
    return base


def test_altman_computes_expected_value():
    r = compute_altman_z(_row())
    assert r["available"] is True
    # X1 = (400-250)/1000 = 0.15 ; X2 = 0.30 ; X3 = 0.12 ; X4 = 400/600
    x1, x2, x3, x4 = 0.15, 0.30, 0.12, 400.0 / 600.0
    expected = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    assert abs(r["z_score"] - round(expected, 2)) < 0.02
    assert r["zone"] in ("SAFE", "GREY", "DISTRESS")


def test_altman_zone_safe():
    r = compute_altman_z(_row())
    assert r["z_score"] > 2.6
    assert r["zone"] == "SAFE"


def test_altman_zone_distress():
    r = compute_altman_z(_row(
        current_assets_bn=200.0, current_liabilities_bn=500.0,
        retained_earnings_bn=10.0, ebit_bn=5.0,
        liabilities_bn=950.0, equity_parent_bn=50.0,
    ))
    assert r["zone"] == "DISTRESS"


def test_altman_missing_component_returns_na():
    """Tidak boleh mengarang pengganti saat komponen hilang."""
    r = compute_altman_z(_row(current_assets_bn=None))
    assert r["available"] is False
    assert "Current Assets" in r["reason"]
    assert "z_score" not in r


def test_altman_missing_retained_earnings_returns_na():
    r = compute_altman_z(_row(retained_earnings_bn=None))
    assert r["available"] is False
    assert "Retained Earnings" in r["reason"]


def test_altman_skips_bank():
    r = compute_altman_z(_row(is_bank=True))
    assert r["available"] is False
    assert "unclassified" in r["reason"].lower()


def test_altman_working_capital_negative_allowed():
    """WC negatif itu nyata (banyak emiten ritel) — bukan error."""
    r = compute_altman_z(_row(current_assets_bn=100.0, current_liabilities_bn=180.0))
    assert r["available"] is True
    assert r["x1_wc_ta"] < 0
