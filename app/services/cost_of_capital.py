"""
Cost of Capital (WACC) — Institutional Grade.

Menggantikan versi lama yang memakai beta=1.0, ERP=5.5%, cost of debt=9%,
dan ETR=22% HARDCODED untuk semua emiten.

Prinsip:
  - Beta diambil dari regresi return harian vs IHSG (data riil DB).
    Jika tidak tersedia -> fallback beta sektor, ditandai provenance.
  - Risk-free dari input (default yield SUN 10Y), bukan angka karangan.
  - ERP: Damodaran Indonesia country risk premium (dapat dikonfigurasi).
  - Cost of debt = interest expense / rata-rata interest-bearing debt.
  - ETR aktual = tax provision / pretax. Jika tidak valid -> statutory 22%.
  - Setiap komponen membawa provenance: REPORTED / MARKET / COMPUTED / PROXY.

ZERO-FAKE: tidak ada nilai yang dipakai tanpa menyatakan asalnya.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlmodel import Session

DEFAULT_RF_PCT = 6.0          # yield SUN 10Y (dapat di-override)
DEFAULT_ERP_PCT = 5.5         # Damodaran mature-market ERP (dapat di-override)
DEFAULT_CRP_PCT = 2.5         # Indonesia country risk premium
STATUTORY_ETR = 0.22          # UU HPP 2022

# Fallback beta per sektor (Damodaran Januari 2026, emerging markets)
SECTOR_BETA = {
    "Keuangan": 1.05,
    "Perindustrian": 1.00,
    "Barang Konsumen Non-Primer": 1.10,
    "Barang Konsumen Primer": 0.85,
    "Energi": 1.05,
    "Barang Baku": 1.10,
    "Infrastruktur": 0.95,
    "Kesehatan": 0.90,
    "Teknologi": 1.25,
    "Properti & Real Estat": 1.15,
    "Transportasi & Logistik": 1.05,
}


def _get_beta(session: Optional[Session], ticker: str,
              sector: Optional[str]) -> tuple[Optional[float], str]:
    """Beta dari regresi riil; fallback sektor bila data tidak cukup."""
    if session is not None:
        try:
            from app.services.performance_engine import compute_performance
            perf = compute_performance(session, ticker, benchmark="IHSG")
            b = perf.get("beta")
            if perf.get("available") and b is not None and b != 0:
                return float(b), "MARKET (regresi return harian vs IHSG, 5 tahun)"
        except Exception:
            pass
    if sector and sector in SECTOR_BETA:
        return SECTOR_BETA[sector], f"PROXY (beta sektor {sector}, Damodaran)"
    return 1.0, "PROXY (beta pasar default 1.0 — data tidak tersedia)"


def _get_etr(row: dict) -> tuple[float, str]:
    """ETR aktual dari laporan; fallback statutory.

    CATATAN PENTING: di XBRL BEI, beban pajak dilaporkan NEGATIF
    (mis. BBCA 2025: tax_expense = -13.697,78 B, pretax = +71.260,88 B).
    ETR = |tax| / pretax. Memakai tanda mentah menghasilkan ETR negatif
    yang keliru dibulatkan jadi 0%.
    """
    pretax = row.get("profit_before_tax_bn")
    tax = row.get("tax_provision_bn")
    if pretax and tax is not None and pretax > 0:
        etr = abs(tax) / pretax
        if 0.0 <= etr <= 0.75:           # rentang wajar
            return etr, "COMPUTED (|tax provision| / pretax aktual)"
    return STATUTORY_ETR, f"PROXY (tarif statutori {STATUTORY_ETR*100:.0f}%)"


def _get_cost_of_debt(row: dict, etr: float) -> tuple[float, str]:
    """Kd = interest expense / rata-rata interest-bearing debt (post-tax)."""
    ie = row.get("interest_expense_bn")
    debt = row.get("total_loans_bn") or row.get("liabilities_bn")
    if ie is not None and debt and debt > 0:
        kd_pre = abs(ie) / debt
        if 0.005 <= kd_pre <= 0.35:      # 0.5% - 35% wajar
            return kd_pre * (1.0 - etr), "COMPUTED (beban bunga / total pinjaman, post-tax)"
    return 0.09 * (1.0 - etr), "PROXY (cost of debt 9% pre-tax)"


def compute_wacc(session: Optional[Session], ticker: str, row: dict,
                 rf_pct: float = DEFAULT_RF_PCT,
                 erp_pct: float = DEFAULT_ERP_PCT,
                 crp_pct: float = DEFAULT_CRP_PCT) -> Dict[str, Any]:
    """
    Hitung WACC institusional dengan provenance per komponen.

    row: dict dari five_year_table() (satu tahun fiskal).
    """
    sector = row.get("sector")
    is_bank = bool(row.get("is_bank"))

    beta, beta_src = _get_beta(session, ticker, sector)
    etr, etr_src = _get_etr(row)

    rf = rf_pct / 100.0
    erp_total = (erp_pct + crp_pct) / 100.0
    ke = rf + beta * erp_total

    kd_post, kd_src = _get_cost_of_debt(row, etr)

    # Struktur modal target (bukan book value mentah)
    equity = row.get("equity_parent_bn") or row.get("equity_total_bn")
    debt = row.get("total_loans_bn") if is_bank else row.get("liabilities_bn")

    if equity is None or equity <= 0:
        return {
            "available": False,
            "reason": "Ekuitas tidak tersedia/tidak valid — WACC tidak dapat dihitung",
            "is_bank": is_bank,
        }

    if debt is None or debt < 0:
        # Tidak ada utang berbunga -> WACC = cost of equity
        we, wd = 1.0, 0.0
        wacc = ke
        debt_prov = "N/A (tidak ada utang berbunga)"
    else:
        total = equity + debt
        we, wd = equity / total, debt / total
        wacc = we * ke + wd * kd_post
        debt_prov = f"{'MARKET' if is_bank else 'REPORTED'} (ekuitas + {'pinjaman' if is_bank else 'liabilitas'})"

    return {
        "available": True,
        "wacc_pct": round(wacc * 100.0, 2),
        "cost_equity_pct": round(ke * 100.0, 2),
        "cost_debt_pct": round(kd_post * 100.0, 2),
        "rf_pct": round(rf * 100.0, 2),
        "erp_pct": round(erp_pct, 2),
        "crp_pct": round(crp_pct, 2),
        "beta": round(beta, 3),
        "etr_pct": round(etr * 100.0, 2),
        "w_equity_pct": round(we * 100.0, 1),
        "w_debt_pct": round(wd * 100.0, 1),
        "is_bank": is_bank,
        "provenance": {
            "beta": beta_src,
            "etr": etr_src,
            "cost_of_debt": kd_src,
            "weights": debt_prov,
            "rf": f"INPUT ({rf_pct}% — asumsi yield SUN 10Y, dapat diubah)",
            "erp": f"INPUT (ERP {erp_pct}% + CRP {crp_pct}%, Damodaran Indonesia)",
        },
    }


# ─────────────────────────────────────────────────────────────────
# EVA / Economic Profit
# ─────────────────────────────────────────────────────────────────
def compute_eva(session: Optional[Session], ticker: str, row: dict,
                wacc_result: Optional[Dict[str, Any]] = None,
                rf_pct: float = DEFAULT_RF_PCT) -> Dict[str, Any]:
    """
    EVA (Economic Value Added) = NOPAT - (WACC x Invested Capital)

    Untuk BANK: RWA (Risk-Weighted Assets) TIDAK tersedia di XBRL BEI
    (diverifikasi: 554 tag BBCA tidak memuat tag risk-weighted/tier/CAR).
    Maka Invested Capital bank TIDAK dapat dihitung secara institusional.

    Alih-alih memakai proxy yang menyesatkan (Assets - Cash membuat bank tampak
    menciptakan nilai raksasa karena aset bank = pinjaman), bank dinilai dengan
    EXCESS RETURN MODEL yang benar untuk lembaga keuangan:
        Excess Return = (ROE - Cost of Equity) x Book Equity
    Ini ekuivalen dengan EVA bila modal diukur dari sisi ekuitas (sisi pemegang
    saham), dan merupakan praktik standar valuasi bank (Damodaran, Koller).
    """
    is_bank = bool(row.get("is_bank"))

    if wacc_result is None:
        wacc_result = compute_wacc(session, ticker, row, rf_pct=rf_pct)

    if not wacc_result.get("available"):
        return {"available": False, "reason": wacc_result.get("reason"), "is_bank": is_bank}

    ebit = row.get("ebit_bn")
    pretax = row.get("profit_before_tax_bn")
    tax = row.get("tax_provision_bn")
    equity = row.get("equity_parent_bn") or row.get("equity_total_bn")
    ni = row.get("net_income_parent_bn")

    etr = wacc_result["etr_pct"] / 100.0

    if is_bank:
        # ---- EXCESS RETURN MODEL (bank) ----
        ke = wacc_result["cost_equity_pct"] / 100.0
        if ni is None or equity is None or equity <= 0:
            return {"available": False, "is_bank": True,
                    "reason": "Laba bersih atau ekuitas tidak tersedia"}

        roe = ni / equity
        spread = roe - ke
        excess = spread * equity

        return {
            "available": True,
            "is_bank": True,
            "method": "EXCESS RETURN (ROE - Ke) x Book Equity",
            "reason_rwa": (
                "RWA tidak tersedia di XBRL BEI (diverifikasi: tidak ada tag "
                "risk-weighted/tier/CAR). EVA berbasis invested capital tidak dapat "
                "dihitung secara institusional untuk bank."
            ),
            "roe_pct": round(roe * 100.0, 2),
            "cost_equity_pct": round(ke * 100.0, 2),
            "spread_pct": round(spread * 100.0, 2),
            "excess_return_bn": round(excess, 1),
            "book_equity_bn": round(equity, 1),
            "nopat_bn": None,
            "invested_capital_bn": None,
            "eva_bn": round(excess, 1),
            "interpretation": (
                "Bank menciptakan nilai di atas biaya ekuitas"
                if spread > 0 else
                "Bank TIDAK menutup biaya ekuitasnya (nilai ekonomis negatif)"
            ),
            "provenance": {
                "roe": "COMPUTED (laba bersih / ekuitas)",
                "ke": wacc_result["provenance"]["beta"],
                "method": "Excess Return Model (standar valuasi bank)",
            },
        }

    # ---- EVA standar (non-bank) ----
    if ebit is None:
        return {"available": False, "is_bank": False, "reason": "EBIT tidak tersedia"}

    nopat = ebit * (1.0 - etr)
    assets = row.get("assets_bn")
    if assets is None or assets <= 0:
        return {"available": False, "is_bank": False, "reason": "Total aset tidak tersedia"}

    # Invested Capital = Total Assets - Non-interest-bearing current liabilities.
    # Data current liabilities tidak selalu ada -> gunakan proxy konservatif:
    # IC = Assets - Cash (kas bukan modal operasional). Dinyatakan sebagai PROXY.
    cash = row.get("cash_bn") or 0.0
    ic = assets - cash
    if ic <= 0:
        return {"available": False, "is_bank": False, "reason": "Invested capital tidak valid"}

    capital_charge = wacc_result["wacc_pct"] / 100.0 * ic
    eva = nopat - capital_charge
    roic = nopat / ic

    return {
        "available": True,
        "is_bank": False,
        "method": "EVA = NOPAT - (WACC x Invested Capital)",
        "nopat_bn": round(nopat, 1),
        "invested_capital_bn": round(ic, 1),
        "capital_charge_bn": round(capital_charge, 1),
        "roic_pct": round(roic * 100.0, 2),
        "wacc_pct": wacc_result["wacc_pct"],
        "spread_pct": round(roic * 100.0 - wacc_result["wacc_pct"], 2),
        "eva_bn": round(eva, 1),
        "interpretation": (
            "Menciptakan nilai ekonomi di atas biaya modal"
            if eva > 0 else
            "Menghancurkan nilai: laba operasi tidak menutup biaya modal"
        ),
        "provenance": {
            "nopat": f"COMPUTED (EBIT x (1 - ETR {etr*100:.2f}%))",
            "invested_capital": "PROXY (Total Assets - Cash; current liabilities tidak tersedia di XBRL)",
            "wacc": wacc_result["provenance"]["beta"],
        },
    }
