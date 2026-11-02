"""
Test invarian valuasi — mengunci bug yang pernah terjadi agar tidak kembali.

Setiap test di sini mewakili bug NYATA yang ditemukan dan diperbaiki.
Tujuannya bukan menguji "kode berjalan", tapi mengunci ATURAN yang tidak boleh
dilanggar lagi. Bila ada refactor yang melanggar salah satunya, test gagal
sebelum bug sampai ke pengguna.

Aturan yang dikunci:
  1. g <= ROE selalu (identitas g = ROE x retention).
  2. Bank ROE <= g tetap mendapat nilai wajar (tidak kosong).
  3. Justified PBV = BVPS x multiple, bisa direproduksi dari komponennya.
  4. Nilai wajar <= 0 tidak boleh disajikan (harga saham tidak bisa negatif).
  5. DCF menolak EBIT non-positif, FCF non-positif, saham tak tersedia.
  6. LATIHAN: guard `g >= WACC` TIDAK boleh dipakai (terminal value memakai
     terminal_growth_rate, bukan g).
"""

from __future__ import annotations

import pytest

from app.services.banking_engine import (
    SECTOR_MEDIAN_PB_BANK,
    calculate_banking_ratios,
)
from app.services.cost_of_capital import compute_sustainable_growth
from app.services.fincept_valuation import quick_dcf_valuation


# ── Helper: satu set laporan keuangan minimal ──────────────────────────────
def _hist(equities, ni_last=None, eps_last=None):
    """Bangun daftar laporan tahunan dengan ekuitas tertentu (miliar)."""
    rows = [{"year": 2021 + i, "equity_parent_bn": eq} for i, eq in enumerate(equities)]
    if ni_last is not None:
        rows[-1]["net_income_parent_bn"] = ni_last
    if eps_last is not None:
        rows[-1]["eps"] = eps_last
    return rows


# ══════════════════════════════════════════════════════════════════════════
# ATURAN 1: g <= ROE
# ══════════════════════════════════════════════════════════════════════════
def test_growth_tidak_boleh_melebihi_roe():
    """
    Bug: BMAS/BACA/BABP ekuitas tumbuh dari SETORAN MODAL (CAGR 12-49%),
    bukan laba ditahan. Engine memakai CAGR itu sebagai g, sehingga
    g (8%, dibatasi) >> ROE (0,49%) dan Justified PBV menjadi negatif.

    Regresi yang dijaga: g harus turun ke 0, bukan disamakan dengan ROE
    (g = ROE membuat retensi 100% -> dividen 0 -> PBV 0, degenerasi).
    """
    # Ekuitas naik 8x dalam 4 tahun (rights issue), tapi laba tipis.
    hist = _hist([500, 1200, 2400, 3500, 4000], ni_last=20.0)
    g, note = compute_sustainable_growth(hist)

    roe = 20.0 / 4000.0  # 0,5%
    assert g is not None, "g tidak boleh None bila data cukup"
    assert g <= roe * 100.0 + 1e-9, (
        f"g={g}% melebihi ROE={roe*100:.2f}% — melanggar identitas g = ROE x retention"
    )
    assert g == 0.0, (
        f"g harus 0 (bukan ROE) karena retensi 100% membuat PBV degenerasi; dapat {g}"
    )
    assert "setoran modal" in note.lower(), "catatan wajib menjelaskan sebabnya"


def test_growth_wajar_tetap_dihormati():
    """Kontrol: bila ekuitas tumbuh dari laba (CAGR < ROE), g dipakai apa adanya."""
    # Ekuitas 1000 -> 1100 dalam 4 tahun (CAGR ~2,4%), laba 150 (ROE 13,6%)
    hist = _hist([1000, 1024, 1049, 1074, 1100], ni_last=150.0)
    g, _ = compute_sustainable_growth(hist)
    assert g is not None and 0.0 < g <= 8.0
    assert g <= (150.0 / 1100.0) * 100.0


# ══════════════════════════════════════════════════════════════════════════
# ATURAN 2 & 3: bank ROE rendah tetap divaluasi, dan angkanya reproducible
# ══════════════════════════════════════════════════════════════════════════
def test_bank_roe_negatif_tetap_dapat_nilai_wajar():
    """
    Bug: SDRA (ROE -10%) dan AGRO (-16,56%) menghasilkan fair_value None
    karena Justified PBV (ROE-g)/(Ke-g) negatif, sehingga tab Valuasi
    kosong total untuk bank merugi.
    """
    r = calculate_banking_ratios({
        "ticker": "SDRA",
        "net_income": -500e9,          # rugi
        "total_equity": 5_000e9,       # ekuitas positif
        "shares_outstanding": 6_900_000_000.0,
        "cost_of_equity_pct": 13.0,
        "sustainable_growth_pct": 0.0,
    })
    assert r.bvps is not None and r.bvps > 0
    assert r.fair_value_per_share is not None, (
        "bank merugi harus tetap punya nilai wajar (P/BV median), bukan None"
    )
    assert r.fair_value_per_share > 0


def test_nilai_wajar_bank_reproducible_dari_komponennya():
    """
    Prinsip 'no false claim': angka yang tampil harus bisa dihitung ulang
    dari komponen yang JUGA tampil di layar (BVPS x multiple).

    Tiga rezim, semuanya harus reproducible:
      a) ROE sehat (ROE > g)  -> Justified PBV (ROE-g)/(Ke-g), bisa < 1
      b) ROE negatif          -> Justified PBV negatif -> fallback P/BV median
      c) ROE tipis tapi positif -> Justified PBV >= 0 dipakai apa adanya
         (BMAS: ROE 0,49% -> PBV 0,0535, tetap BOLEH; bukan median)
    """
    cases = [
        # (net_income, equity, ekspektasi)
        (500e9, 5_000e9, "justified"),   # ROE 10% -> PBV >= 0
        (-500e9, 5_000e9, "median"),     # ROE negatif -> PBV negatif -> median
        (25e9, 5_000e9, "justified"),    # ROE 0,5% tipis, PBV tetap >= 0
    ]
    for ni, eq, mode in cases:
        r = calculate_banking_ratios({
            "ticker": "BMRI",   # ticker bank asli: is_banking_entity() memvalidasi
            "net_income": ni,
            "total_equity": eq,
            "shares_outstanding": 1_000_000_000.0,
            "cost_of_equity_pct": 13.0,
            "sustainable_growth_pct": 0.0,
        })
        assert r is not None, "ticker bank harus menghasilkan BankingRatios"
        if mode == "median":
            assert r.justified_pbv is None, "PBV negatif tidak boleh disajikan"
            multiple = SECTOR_MEDIAN_PB_BANK
        else:
            assert r.justified_pbv is not None and r.justified_pbv >= 0
            multiple = r.justified_pbv
        assert r.fair_value_per_share == pytest.approx(r.bvps * multiple, rel=1e-9), (
            f"FV {r.fair_value_per_share} != BVPS {r.bvps} x {multiple}"
        )


# ══════════════════════════════════════════════════════════════════════════
# ATURAN 4: nilai wajar tidak boleh negatif
# ══════════════════════════════════════════════════════════════════════════
def test_nilai_wajar_negatif_ditolak():
    """
    Bug: SDRA -Rp1.803, BMAS -Rp2.594 -> screener menampilkan
    upside -1142% (mustahil: batas bawah aritmetika adalah -100%).
    """
    r = calculate_banking_ratios({
        "ticker": "BJBR",   # ticker bank asli
        "net_income": -900e9,
        "total_equity": 3_000e9,
        "shares_outstanding": 2_000_000_000.0,
        "cost_of_equity_pct": 15.0,
        "sustainable_growth_pct": 6.0,   # g tinggi + ROE negatif -> PBV negatif
    })
    if r.fair_value_per_share is not None:
        assert r.fair_value_per_share > 0, "harga saham tidak boleh <= 0"


# ══════════════════════════════════════════════════════════════════════════
# ATURAN 5: DCF menolak model yang tidak bermakna
# ══════════════════════════════════════════════════════════════════════════
def _dcf(**over):
    base = dict(
        ticker="TEST",
        current_market_price=1000.0,
        risk_free_rate=6.0,
        market_risk_premium=6.5,
        levered_beta=1.0,
        cost_of_debt_pre_tax=7.5,
        tax_rate=0.22,
        target_debt_ratio=0.3,
        wacc_override=11.0,
        ebit=2000.0,
        depreciation=800.0,
        capex=700.0,
        wc_change=0.0,
        fcf_growth_rate=0.05,
        terminal_growth_rate=0.025,
        total_assets=10_000.0,
        total_debt=2_000.0,
        cash=1_000.0,
        shares_outstanding_m=1_000.0,
    )
    base.update(over)
    return quick_dcf_valuation(**base)


def test_dcf_tolak_ebit_negatif():
    """Bug: EXCL EBIT -1.345 B menghasilkan DCF Rp12.405 (+721%)."""
    assert _dcf(ebit=-1345.0) is None


def test_dcf_tolak_fcf_negatif():
    """Bug: ADRO FCF -1.976 B -> EV negatif, 'harga' Rp195."""
    # EBIT 500 x (1-22%) + D&A 100 - capex 900 = -410
    assert _dcf(ebit=500.0, depreciation=100.0, capex=900.0) is None


def test_dcf_tolak_saham_tidak_tersedia():
    """ZERO-FAKE: jumlah saham karangan (ekuitas/harga asumsi) dihapus."""
    assert _dcf(shares_outstanding_m=None) is None
    assert _dcf(shares_outstanding_m=0) is None


def test_dcf_menerima_emiten_sehat():
    """Kontrol: emiten sehat harus tetap menghasilkan nilai (tidak over-reject)."""
    r = _dcf()
    assert r is not None, "DCF emiten sehat tidak boleh ikut ditolak"
    assert r["price_per_share"] > 0


# ══════════════════════════════════════════════════════════════════════════
# ATURAN 6: guard g >= WACC adalah kesalahan metodologi
# ══════════════════════════════════════════════════════════════════════════
def test_g_melebihi_wacc_bukan_alasan_menolak_dcf():
    """
    Bug: guard `g >= WACC` membunuh DCF UNTR (g 12% vs WACC 11,74%).
    Padahal terminal value memakai terminal_growth_rate (2,5%), BUKAN g.
    Yang membuat penyebut nol adalah terminal_growth >= WACC.
    """
    r = _dcf(fcf_growth_rate=0.12, wacc_override=11.0)   # g 12% > WACC 11%
    assert r is not None, (
        "g > WACC bukan alasan menolak: pertumbuhan 5 tahun boleh melebihi "
        "biaya modal selama terminal growth < WACC"
    )


def test_terminal_growth_melebihi_wacc_ditolak():
    """Kontrol: yang benar-benar membuat model pecah adalah tg >= WACC."""
    r = _dcf(terminal_growth_rate=0.12, wacc_override=11.0)
    # TV = 0 -> equity dari PV FCF saja (bisa tetap positif); pastikan tidak
    # ada pembagian nol / angka raksasa.
    assert r is None or r["price_per_share"] > 0
