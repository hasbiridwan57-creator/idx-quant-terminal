"""
app/services/banking_engine.py
Mesin analisis khusus sektor perbankan (Bank Model)
Menghitung rasio-rasio kunci perbankan Indonesia (NIM, ROA, LDR proxy, CIR proxy, dll)
 serta valuasi fundamental: Justified PBV, BVPS, Fair Value Bank (CFA Excess Return model)
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel

# ── Constants ──────────────────────────────────────────────────────────────────
IDX_BANK_TICKERS: set = {
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BDMN", "BNGA", "NISP", "MEGA",
    "BBTN", "BJBR", "BJTM", "BTPS", "ARTO", "BBHI", "PNBN", "BNLI", "BNII",
    "AGRO", "BBKP", "BMAS", "BSIM", "MAYA", "MCOR", "SDRA", "BGTG", "AMAR",
    "BANK", "BABP", "BACA", "BINA", "BKSW", "BMND", "BVIC", "DNAR", "INPC",
    "MASB", "NOBU", "PKPK",
}

# CFA Excess-Return model constants for Indonesian banks
KE = 0.105   # Cost of equity = 10.5 %
G  = 0.050   # Long-term growth rate = 5.0 %


# ── Pydantic Models ─────────────────────────────────────────────────────────────
class BankingRatios(BaseModel):
    ticker: str
    year: int

    # ── Traditional banking ratios ──────────────────────────────────────────────
    net_interest_margin: Optional[float] = None       # NIM: Net Interest Income / Total Assets
    cost_to_income_ratio: Optional[float] = None      # CIR: Operating Expense / Total Revenue
    return_on_assets: Optional[float] = None          # ROA: Net Income / Total Assets
    return_on_equity: Optional[float] = None          # ROE: Net Income / Total Equity
    loans_to_assets_ratio: Optional[float] = None      # Net Loan / Total Assets
    debt_to_equity: Optional[float] = None            # Total Debt / Total Equity
    effective_tax_rate: Optional[float] = None        # Tax Provision / Pretax Income
    funding_cost_ratio: Optional[float] = None         # Interest Expense / Revenue
                                                       # (BUKAN CIR — dulu salah label)

    # ── CFA Excess-Return (Residual Income) valuation fields ───────────────────
    justified_pbv: Optional[float] = None             # (ROE - g) / (Ke - g)
    bvps: Optional[float] = None                      # total_equity / shares_outstanding (IDR/share)
    fair_value_per_share: Optional[float] = None        # BVPS × Justified PBV


# ── Helpers ─────────────────────────────────────────────────────────────────────
def is_banking_entity(ticker: str, sector: Optional[str] = None) -> bool:
    """Return True if ticker is a known IDX bank or sector contains 'bank'."""
    if ticker.upper() in IDX_BANK_TICKERS:
        return True
    if sector and "bank" in sector.lower():
        return True
    return False


def calculate_banking_ratios(data: Dict[str, Any]) -> Optional[BankingRatios]:
    """
    Hitung rasio perbankan dari dictionary laporan keuangan.

    Jika entitas BUKAN bank (bukan di IDX_BANK_TICKERS dan sector tidak
    mengandung 'bank'), return None — jangan hitung metrik perbankan
    untuk non-bank.
    """
    ticker = data.get("ticker", "")
    sector = data.get("sector")

    if not is_banking_entity(ticker, sector):
        return None

    # ── Pull raw fields ────────────────────────────────────────────────────────
    revenue      = data.get("revenue", 0.0) or 0.0
    net_income   = data.get("net_income", 0.0) or 0.0
    total_assets = data.get("total_assets", 0.0) or 0.0
    total_equity = data.get("total_equity", 0.0) or 0.0
    total_debt   = data.get("total_debt", 0.0) or 0.0
    int_inc      = data.get("interest_income", 0.0) or 0.0
    int_exp      = data.get("interest_expense", 0.0) or 0.0
    pretax       = data.get("pretax_income", 0.0) or 0.0
    tax          = data.get("tax_provision", 0.0) or 0.0
    shares_out   = data.get("shares_outstanding", 0.0) or 0.0

    # ── Net Interest Income = interest_income - interest_expense ───────────────
    # Fallback proxy when interest_income is missing: revenue - interest_expense
    if int_inc > 0 and int_exp > 0:
        net_int = int_inc - int_exp
    elif revenue > 0 and int_exp > 0:
        net_int = revenue - int_exp
    else:
        net_int = 0.0

    # ── Traditional banking ratios ─────────────────────────────────────────────
    # NIM = net_interest_income / total_assets
    nim = (net_int / total_assets) if (total_assets > 0 and net_int > 0) else None

    # ── CIR (Cost-to-Income Ratio) ─────────────────────────────────────────────
    # BUG lama: CIR dihitung sebagai interest_expense / revenue — itu
    # "funding cost ratio", BUKAN CIR. CIR baku = beban operasional dibagi
    # pendapatan operasional. Untuk bank di BEI, pendapatan operasional =
    # pendapatan bunga bersih + pendapatan operasional lainnya, dan beban
    # operasional dilaporkan terpisah (OperatingExpenses / GeneralAndAdministrative).
    # Bila komponennya tidak ada, CIR dikembalikan None (N/A) — bukan
    # disubstitusi rasio lain yang namanya berbeda.
    _opex = data.get("operating_expenses") or data.get("operating_expense")
    _oprev = data.get("operating_revenue")
    if _oprev is None and int_inc > 0:
        _oprev = int_inc          # pendapatan operasional bank = pendapatan bunga
    if _opex and _oprev and float(_oprev) > 0:
        cir = float(_opex) / float(_oprev)
    else:
        cir = None

    # Funding cost ratio dilaporkan TERPISAH dengan nama yang benar.
    funding_cost_ratio = (int_exp / revenue) if (revenue > 0 and int_exp > 0) else None

    roa = (net_income / total_assets) if total_assets > 0 else None
    roe = (net_income / total_equity) if total_equity > 0 else None
    dte = (total_debt / total_equity) if total_equity > 0 else None
    # Beban pajak di XBRL BEI dilaporkan NEGATIF -> pakai nilai absolut.
    # Versi lama `tax > 0` membuat ETR selalu None.
    etr = (abs(tax) / pretax) if (pretax > 0 and tax is not None and abs(tax) > 0) else None

    # ── CFA Excess-Return (Residual Income) valuation ─────────────────────────
    # Ke RIIL dari cost_of_capital (beta regresi vs IHSG), bukan konstanta 10.5%.
    # g = pertumbuhan berkelanjutan (sustainable growth) = ROE x (1 - payout ratio);
    # bila data dividen tidak tersedia, g = pertumbuhan ekuitas buku historis.
    justified_pbv = None
    bvps = None
    fair_value_per_share = None

    ke_used = data.get("cost_of_equity_pct")
    ke_used = (ke_used / 100.0) if isinstance(ke_used, (int, float)) and ke_used else KE
    g_used = data.get("sustainable_growth_pct")
    g_used = (g_used / 100.0) if isinstance(g_used, (int, float)) else G

    if roe is not None and (ke_used - g_used) > 0.005:
        # Justified PBV = (ROE - g) / (Ke - g).
        # Dihitung juga saat ROE < Ke: hasilnya < 1, yang berarti bank
        # mempertahankan laba di bawah biaya ekuitas (menghancurkan nilai).
        # Versi lama menyembunyikannya (roe > KE) sehingga PBV wajar hilang.
        justified_pbv = (roe - g_used) / (ke_used - g_used)
        justified_pbv = round(justified_pbv, 4)

    # BVPS = total_equity / shares_outstanding  (IDR per share)
    if total_equity > 0 and shares_out > 0:
        bvps = total_equity / shares_out
    elif total_equity > 0:
        # Shares outstanding tidak dilaporkan langsung di XBRL BEI. Diturunkan
        # dari identitas: EPS = Laba Bersih / Jumlah Saham  =>  Shares = NI / EPS.
        # Diverifikasi pada BBCA: NI Rp 54.486,5 B / EPS 467 = 116,67 miliar lembar
        # (sesuai 3,08 miliar lembar pasca stock split 1:5, Apr 2025).
        eps_val = data.get("eps")
        if isinstance(eps_val, (int, float)) and eps_val not in (0, None) and net_income:
            shares_derived = net_income / float(eps_val)
            if shares_derived > 0:
                bvps = total_equity / shares_derived

    # Fair Value Bank = BVPS × Justified PBV
    if bvps is not None and justified_pbv is not None:
        fair_value_per_share = bvps * justified_pbv

    return BankingRatios(
        ticker=ticker or "BANK",
        year=int(data.get("period", data.get("year", 2025))),
        net_interest_margin=nim,
        cost_to_income_ratio=cir,
        funding_cost_ratio=funding_cost_ratio,
        return_on_assets=roa,
        return_on_equity=roe,
        loans_to_assets_ratio=None,          # requires net_loan field — not always available
        debt_to_equity=dte,
        effective_tax_rate=etr,
        justified_pbv=justified_pbv,
        bvps=bvps,
        fair_value_per_share=fair_value_per_share,
    )
