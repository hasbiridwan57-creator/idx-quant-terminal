"""Satu sumber kebenaran untuk harga DCF pada WACC/terminal growth tertentu.

Sebelumnya ada dua model DCF terpisah:
  * halaman utama & endpoint revaluasi memakai quick_dcf_valuation (FCF dari
    EBIT, D&A, capex, perubahan modal kerja),
  * grid sensitivitas di research_paper_engine memakai DCFInputs dengan
    asumsi sendiri (D&A 3% revenue, capex = D&A, NWC 5%).
Untuk ASII keduanya menghasilkan Rp12.373 vs Rp5.149 pada WACC yang sama.
Dua angka berbeda untuk emiten yang sama tidak dapat dipertanggungjawabkan.

Modul ini menghitung DCF dari komponen yang SAMA dengan valuasi utama, supaya
slider, grid, dan target harga selalu konsisten.
"""
from __future__ import annotations
from typing import Optional, Dict


def dcf_price_at(raw: Dict[str, float], wacc_pct: float,
                 tg_pct: float) -> Optional[Dict[str, float]]:
    """Hitung harga wajar per saham pada WACC & terminal growth tertentu.

    `raw` adalah input DCF yang sama dengan valuasi utama (lihat
    `_build_dcf_raw_inputs` di app/main.py). Mengembalikan None bila
    kombinasi parameter tidak terdefinisi (WACC <= g) atau input tidak lengkap.
    """
    if not raw:
        return None
    w = wacc_pct / 100.0
    g = tg_pct / 100.0
    if w <= g:
        return None
    try:
        from app.services.fincept_valuation import DCFModel
        model = DCFModel(raw.get("ticker", "NA"))
        base_fcf = model.calculate_free_cash_flow(
            raw["ebit"],
            raw.get("tax_rate", 0.22),
            raw.get("depreciation", 0.0),
            raw.get("capex", 0.0),
            raw.get("wc_change", 0.0),
        )
        proj = model.project_cash_flows(base_fcf, raw.get("fcf_growth_rate", 0.05), 5)
        tv = model.calculate_terminal_value(proj[-1], g, w)
        ev = model.calculate_enterprise_value(proj, tv, w)
        eq = model.calculate_equity_value(
            ev, raw.get("total_debt", 0.0), raw.get("cash", 0.0), 0.0)
        price = model.calculate_price_per_share(eq, raw.get("shares_bn", 0.0))
        return {
            "price": round(max(0.0, price), 1),
            "ev_bn": round(ev, 2),
            "equity_bn": round(eq, 2),
        }
    except (KeyError, ValueError, ZeroDivisionError, OverflowError):
        return None
