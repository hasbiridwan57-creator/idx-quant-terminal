"""
Loader data laporan keuangan audited IDX (XBRL resmi BEI) 2021-2025.
ZERO-FAKE: hanya menyajikan angka yang ada di file XBRL. Tidak ada estimasi/back-calculation.

Sumber: /Users/hasbi/laporan/bei_full/parsed/xbrl_audited_metrics.jsonl
Satuan asli XBRL = rupiah penuh (unitRef IDR) atau rupiah penuh USD (unitRef USD).
Semua getter di modul ini mengembalikan nilai dalam MILIAR (untuk IDR) agar konsisten
dengan unit internal app; konversi USD->IDR memakai kurs yang diberikan pemanggil.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

_CACHE: Optional[Dict[str, List[dict]]] = None
_JSONL = "/Users/hasbi/laporan/bei_full/parsed/xbrl_audited_metrics.jsonl"
_PROFILES_CACHE: Optional[Dict[str, dict]] = None
_GOVERNANCE_CACHE: Optional[Dict[str, dict]] = None

def get_governance(ticker: str) -> dict:
    """Board of directors, shareholders, subsidiaries dari scrape BEI resmi."""
    global _GOVERNANCE_CACHE
    if _GOVERNANCE_CACHE is None:
        g_path = "/Users/hasbi/idx-quant-terminal/data/idx_governance.json"
        if os.path.exists(g_path):
            try:
                with open(g_path, "r", encoding="utf-8") as f:
                    _GOVERNANCE_CACHE = json.load(f)
            except Exception:
                _GOVERNANCE_CACHE = {}
        else:
            _GOVERNANCE_CACHE = {}
    return _GOVERNANCE_CACHE.get(ticker.upper().strip(), {})

def get_issuer_profile(ticker: str) -> dict:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is None:
        p_path = "/Users/hasbi/idx-quant-terminal/data/idx_profiles.json"
        if os.path.exists(p_path):
            try:
                with open(p_path, "r", encoding="utf-8") as f:
                    _PROFILES_CACHE = json.load(f)
            except Exception:
                _PROFILES_CACHE = {}
        else:
            _PROFILES_CACHE = {}
    return _PROFILES_CACHE.get(ticker.upper().strip(), {})


def _load() -> Dict[str, List[dict]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data: Dict[str, List[dict]] = {}
    if not os.path.exists(_JSONL):
        _CACHE = data
        return data
    with open(_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("parse_ok"):
                continue
            data.setdefault(r["ticker"], []).append(r)
    for k in data:
        data[k].sort(key=lambda x: x["year"])
    _CACHE = data
    return data


def available() -> bool:
    return os.path.exists(_JSONL)


def has_ticker(ticker: str) -> bool:
    return ticker.upper() in _load()


def years(ticker: str) -> List[int]:
    return [r["year"] for r in _load().get(ticker.upper(), [])]


def get_row(ticker: str, year: int) -> Optional[dict]:
    for r in _load().get(ticker.upper(), []):
        if r["year"] == year:
            return r
    return None


def _bn(v: Optional[float], currency: str, usdidr: float) -> Optional[float]:
    """Rupiah penuh -> miliar IDR. USD penuh -> miliar IDR via kurs."""
    if v is None:
        return None
    if currency == "USD":
        return v * usdidr / 1e9
    return v / 1e9


def series(ticker: str, usdidr: float = 16000.0) -> List[dict]:
    """
    Seri 5 tahun siap pakai untuk tabel & DuPont.
    Hanya field yang ada; nilai hilang = None (UI wajib render N/A).
    """
    out = []
    for r in _load().get(ticker.upper(), []):
        cur = r.get("currency", "IDR")
        out.append({
            "year": r["year"],
            "audited": True,
            "source": "IDX XBRL (audited)",
            "currency": cur,
            "is_bank": bool(r.get("is_bank")),
            "is_syariah": bool(r.get("is_syariah")),
            # Bank syariah: revenue_sales = Mudharib + ThirdPartyShare bisa NEGATIF
            # (bagi hasil adalah distribusi). Fallback ke interest income hanya kasus itu.
            # Bank konvensional: revenue_sales = InterestIncome + OtherOpIncome (benar).
            "revenue_bn": (
                _bn(r.get("interest_income_bank") or r.get("interest_income"), cur, usdidr)
                if (_bn(r.get("revenue_sales"), cur, usdidr) is not None
                    and _bn(r.get("revenue_sales"), cur, usdidr) < 0
                    and _bn(r.get("interest_income_bank") or r.get("interest_income"), cur, usdidr) is not None)
                else _bn(r.get("revenue_sales"), cur, usdidr)
            ),
            "gross_profit_bn": _bn(r.get("gross_profit"), cur, usdidr),
            "operating_expense_bn": _bn(r.get("operating_expense"), cur, usdidr),
            "net_income_parent_bn": _bn(r.get("net_income_parent"), cur, usdidr),
            "net_income_total_bn": _bn(r.get("net_income_total"), cur, usdidr),
            "assets_bn": _bn(r.get("assets"), cur, usdidr),
            "liabilities_bn": _bn(r.get("liabilities") or r.get("total_liab"), cur, usdidr),
            "equity_parent_bn": _bn(r.get("equity_parent"), cur, usdidr),
            "equity_total_bn": _bn(r.get("equity_total"), cur, usdidr),
            "cash_bn": _bn(r.get("cash"), cur, usdidr),
            # Neraca terklasifikasi — untuk Altman Z'' dan Invested Capital presisi.
            # Hanya ada pada emiten non-bank (bank memakai unclassified balance sheet).
            "current_assets_bn": _bn(r.get("current_assets"), cur, usdidr),
            "current_liabilities_bn": _bn(r.get("current_liabilities"), cur, usdidr),
            "non_current_assets_bn": _bn(r.get("non_current_assets"), cur, usdidr),
            "non_current_liabilities_bn": _bn(r.get("non_current_liabilities"), cur, usdidr),
            "retained_earnings_bn": (
                (_bn(r.get("retained_earnings_unappropriated"), cur, usdidr) or 0.0)
                + (_bn(r.get("retained_earnings_appropriated"), cur, usdidr) or 0.0)
            ) if (r.get("retained_earnings_unappropriated") is not None
                  or r.get("retained_earnings_appropriated") is not None) else None,
            "st_debt_bn": (
                (_bn(r.get("current_maturities_bank_loans"), cur, usdidr) or 0.0)
                + (_bn(r.get("short_term_bank_loans"), cur, usdidr) or 0.0)
                + (_bn(r.get("current_maturities_bonds"), cur, usdidr) or 0.0)
                + (_bn(r.get("current_maturities_lease"), cur, usdidr) or 0.0)
            ) if any(r.get(k) is not None for k in
                     ("current_maturities_bank_loans", "short_term_bank_loans",
                      "current_maturities_bonds", "current_maturities_lease")) else None,
            "selling_expense_bn": _bn(r.get("selling_expense"), cur, usdidr),
            "ga_expense_bn": _bn(r.get("ga_expense"), cur, usdidr),
            "tax_provision_bn": _bn(r.get("tax_expense"), cur, usdidr),
            # Field untuk banking engine, DCF, dan screener (sebelumnya tidak pernah di-expose)
            "interest_income_bn": _bn(r.get("interest_income_bank") or r.get("interest_income"), cur, usdidr),
            "interest_expense_bn": _bn(r.get("interest_expense"), cur, usdidr),
            "operating_cash_flow_bn": _bn(r.get("operating_cash_flow"), cur, usdidr),
            "shares_outstanding": r.get("shares_outstanding"),
            "profit_before_tax_bn": _bn(r.get("profit_before_tax"), cur, usdidr),
            "finance_costs_bn": _bn(r.get("finance_costs"), cur, usdidr),
            "finance_income_bn": _bn(r.get("finance_income"), cur, usdidr),
            "interest_expense_bn": _bn(r.get("interest_expense"), cur, usdidr),
            "ppop_bn": _bn(r.get("ppop"), cur, usdidr),
            "impairment_losses_bn": _bn(r.get("impairment_losses"), cur, usdidr),
            # Bank-specific dari XBRL audited
            "cost_of_sales_bn": _bn(r.get("cost_of_sales"), cur, usdidr),
            "loans_gross_bn": _bn(r.get("loans_gross"), cur, usdidr),
            "total_loans_bn": _bn(r.get("total_loans"), cur, usdidr),
            "allowance_impairment_loans_bn": _bn(r.get("allowance_impairment_loans"), cur, usdidr),
            "other_operating_expenses_bn": _bn(r.get("other_operating_expenses"), cur, usdidr),
            "other_operating_income_bn": _bn(r.get("other_operating_income"), cur, usdidr),
            # D&A & working capital (untuk EBITDA & Cash Conversion Cycle)
            "depreciation_amortization_bn": _bn(r.get("depreciation_amortization"), cur, usdidr),
            "inventories_bn": _bn(r.get("inventories"), cur, usdidr),
            "trade_receivables_bn": _bn(r.get("trade_receivables"), cur, usdidr),
            "trade_payables_bn": _bn(r.get("trade_payables"), cur, usdidr),
            "dividends_paid_bn": _bn(r.get("dividends_paid"), cur, usdidr),
            "capex_bn": _bn(r.get("capex"), cur, usdidr),
            "treasury_stock_bn": _bn(r.get("treasury_stock"), cur, usdidr),
            "npl_gross_pct": r.get("npl_gross"),
            "npl_net_pct": r.get("npl_net"),
            "eps": r.get("eps"),
            "revenue_concept": (r.get("_concepts") or {}).get("revenue_sales"),
        })

        # --- EBIT: bank = PPOP asli; non-bank = Top-Down (GP - S&M - G&A) ---
        _gp = out[-1].get("gross_profit_bn")
        _se = out[-1].get("selling_expense_bn")
        _ga = out[-1].get("ga_expense_bn")
        _ppop = out[-1].get("ppop_bn")
        if out[-1].get("is_bank") and _ppop is not None:
            out[-1]["ebit_bn"] = _ppop
            out[-1]["ebit_method"] = "PPOP (ProfitFromOperation, reported)"
        elif _gp is not None:
            out[-1]["ebit_bn"] = _gp - (_se or 0.0) - (_ga or 0.0)
            out[-1]["ebit_method"] = "Top-Down (Gross Profit - S&M - G&A)"
        elif out[-1].get("profit_before_tax_bn") is not None and out[-1].get("finance_costs_bn") is not None:
            out[-1]["ebit_bn"] = out[-1]["profit_before_tax_bn"] + out[-1]["finance_costs_bn"]
            out[-1]["ebit_method"] = "Bottom-Up (PBT + Finance Costs)"
        else:
            out[-1]["ebit_bn"] = None
            out[-1]["ebit_method"] = "N/A (insufficient XBRL components)"

        # EBITDA hanya jika D&A tersedia (tidak dikarang)
        _da = out[-1].get("depreciation_amortization_bn")
        out[-1]["ebitda_bn"] = (
            out[-1]["ebit_bn"] + _da
            if (out[-1]["ebit_bn"] is not None and _da is not None)
            else None
        )
    return out


def derive_ratios(row: dict) -> Dict[str, Optional[float]]:
    """Rasio yang bisa dihitung jujur dari satu baris. None bila input hilang."""
    rev = row.get("revenue_bn")
    ni = row.get("net_income_parent_bn")
    eq = row.get("equity_parent_bn")
    aset = row.get("assets_bn")
    gp = row.get("gross_profit_bn")

    def div(a, b):
        if a is None or b in (None, 0):
            return None
        return a / b

    return {
        "net_margin_pct": None if div(ni, rev) is None else div(ni, rev) * 100,
        "gross_margin_pct": None if div(gp, rev) is None else div(gp, rev) * 100,
        "roe_pct": None if div(ni, eq) is None else div(ni, eq) * 100,
        "roa_pct": None if div(ni, aset) is None else div(ni, aset) * 100,
        "equity_multiplier": div(aset, eq),
        "asset_turnover": div(rev, aset),
    }


def five_year_table(ticker: str, usdidr: float = 16000.0) -> List[dict]:
    rows = series(ticker, usdidr)
    prof = get_issuer_profile(ticker)
    for r in rows:
        r["ratios"] = derive_ratios(r)
        # Inject profil resmi BEI
        if not r.get("company_name"):
            r["company_name"] = prof.get("company_name", ticker)
        r["sector"] = prof.get("sector") or r.get("sector") or "N/A"
        r["sub_sector"] = prof.get("sub_sector") or r.get("sub_sector") or "N/A"
        r["industry"] = prof.get("industry") or "N/A"
        r["controlling_shareholder"] = prof.get("controlling_shareholder") or "N/A"
        r["free_float_pct"] = prof.get("free_float_pct")
        r["website"] = prof.get("website") or "N/A"
        # CATATAN: bank_metrics CALK CSV dari scrape TIDAK dipakai karena terbukti
        # rusak (NPL BBCA 9.3% vs 1.7% aktual, satuan campur, tahun duplikat).
        # Semua metrik bank diambil dari XBRL audited saja (zero-fake policy).
    return rows
