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
            "revenue_bn": _bn(r.get("revenue_sales"), cur, usdidr),
            "gross_profit_bn": _bn(r.get("gross_profit"), cur, usdidr),
            "operating_expense_bn": _bn(r.get("operating_expense"), cur, usdidr),
            "net_income_parent_bn": _bn(r.get("net_income_parent"), cur, usdidr),
            "net_income_total_bn": _bn(r.get("net_income_total"), cur, usdidr),
            "assets_bn": _bn(r.get("assets"), cur, usdidr),
            "liabilities_bn": _bn(r.get("total_liab"), cur, usdidr),
            "equity_parent_bn": _bn(r.get("equity_parent"), cur, usdidr),
            "equity_total_bn": _bn(r.get("equity_total"), cur, usdidr),
            "cash_bn": _bn(r.get("cash"), cur, usdidr),
            "selling_expense_bn": _bn(r.get("selling_expense"), cur, usdidr),
            "ga_expense_bn": _bn(r.get("ga_expense"), cur, usdidr),
            "tax_provision_bn": _bn(r.get("tax_expense"), cur, usdidr),
            "profit_before_tax_bn": _bn(r.get("profit_before_tax"), cur, usdidr),
            "finance_costs_bn": _bn(r.get("finance_costs"), cur, usdidr),
            "finance_income_bn": _bn(r.get("finance_income"), cur, usdidr),
            "interest_expense_bn": _bn(r.get("interest_expense"), cur, usdidr),
            "ppop_bn": _bn(r.get("ppop"), cur, usdidr),
            "impairment_losses_bn": _bn(r.get("impairment_losses"), cur, usdidr),
            "dividends_paid_bn": _bn(r.get("dividends_paid"), cur, usdidr),
            "capex_bn": _bn(r.get("capex"), cur, usdidr),
            "treasury_stock_bn": _bn(r.get("treasury_stock"), cur, usdidr),
            "npl_gross_pct": r.get("npl_gross"),
            "npl_net_pct": r.get("npl_net"),
            "eps": r.get("eps"),
            "revenue_concept": (r.get("_concepts") or {}).get("revenue_sales"),
        })
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
    for r in rows:
        r["ratios"] = derive_ratios(r)
    return rows
