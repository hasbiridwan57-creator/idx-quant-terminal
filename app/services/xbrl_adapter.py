"""
Adapter: XBRL audited IDX → FinancialStatementInput (dupont_engine schema).
Bisa dipakai untuk ticker yang TIDAK ada di FinancialStatementCache.
"""
from __future__ import annotations

from typing import Optional

from app.services import idx_audited_financials as _AF
from app.services.dupont_engine import FinancialStatementInput


def from_xbrl(ticker: str, usdidr: float = 16000.0) -> Optional[FinancialStatementInput]:
    """Return FinancialStatementInput dari XBRL audited FY terakhir, atau None."""
    if not _AF.available() or not _AF.has_ticker(ticker):
        return None
    rows = _AF.five_year_table(ticker, usdidr=usdidr)
    if not rows:
        return None
    r = rows[-1]  # FY terakhir
    rev = r.get("revenue_bn")
    ni = r.get("net_income_parent_bn")
    assets = r.get("assets_bn")
    eq = r.get("equity_parent_bn")
    liab = r.get("liabilities_bn")
    if rev is None or ni is None or assets is None or eq is None:
        return None
    return FinancialStatementInput(
        ticker=ticker.upper(),
        company_name=ticker.upper(),
        year=int(r["year"]),
        period_type="FY",
        currency=r.get("currency", "IDR"),
        unit_multiplier=1e9,  # value dalam miliar IDR
        revenue=float(rev),
        ebit=0.0,
        ebt=0.0,
        net_income_parent=float(ni),
        total_assets=float(assets),
        total_liabilities=float(liab) if liab is not None else 0.0,
        total_equity_parent=float(eq),
        total_equity_consolidated=None,
        shares_outstanding=None,
        cash_and_equivalents=None,
        interest_bearing_debt=None,
        current_assets=None,
        current_liabilities=None,
        interest_income=None,
        interest_expense=None,
        tax_provision=None,
        operating_cash_flow=None,
        capex=None,
        depreciation=None,
        minority_interest=None,
        sector=None,
    )
