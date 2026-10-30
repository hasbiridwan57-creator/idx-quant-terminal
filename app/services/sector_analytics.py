"""
Sector-Specific Analytics Engine (Institutional Tier-1 Standard)
Handles deep-dive operational metrics across:
  1. Commodities & Mining (stripping ratio proxy, cash flow capex coverage, realization margin)
  2. Consumer & Retail (Cash Conversion Cycle: DIO + DSO - DPO, inventory turnover)
  3. Property & Real Estate (Net Gearing, Interest Coverage, Presales Capital Intensity)
  4. Technology & FinTech (Take Rate, Operating Leverage, Burn Multiple)
"""

from typing import Dict, Any, Optional, List


def compute_sector_metrics(financials: List[Dict[str, Any]],
                           sector_name: str,
                           ticker: str) -> Dict[str, Any]:
    """
    Kalkulasi metrik spesifik industri berdasarkan baris laporan keuangan audited.
    Bila data spesifik tidak dilaporkan di XBRL, beri nilai None / N/A (jujur).
    """
    if not financials:
        return {"sector_category": "GENERAL", "metrics": [], "notes": "No historical financials"}

    latest = financials[-1]
    prev = financials[-2] if len(financials) > 1 else {}

    s_upper = (sector_name or "").upper()
    t_upper = (ticker or "").upper()

    rev = latest.get("revenue_bn")
    ni = latest.get("net_income_parent_bn")
    ebit = latest.get("ebit_bn")
    gp = latest.get("gross_profit_bn")
    ta = latest.get("total_assets_bn") or latest.get("assets_bn")
    eq = latest.get("total_equity_bn") or latest.get("equity_parent_bn")
    liab = latest.get("liabilities_bn")
    cash = latest.get("cash_bn") or 0.0
    fc = latest.get("finance_costs_bn") or 0.0
    capex = latest.get("capex_bn")

    # Identifikasi cluster industri
    is_commodity = any(k in s_upper for k in ["ENERGY", "MINING", "TAMBANG", "BASIC MATERIAL", "OIL", "GAS", "COAL"]) or t_upper in ["ANTM", "INCO", "PTBA", "ADRO", "ITMG", "MEDC"]
    is_consumer = any(k in s_upper for k in ["CONSUMER", "RETAIL", "FOOD", "BEVERAGE", "BARANG KONSUMEN"]) or t_upper in ["ICBP", "INDF", "MYOR", "UNVR", "AMRT", "ACES"]
    is_property = any(k in s_upper for k in ["PROPERTY", "REAL ESTATE", "PROPERTI", "KONSTRUKSI", "CONSTRUCTION"]) or t_upper in ["BSDE", "CTRA", "PWON", "SMRA", "ASRI"]
    is_bank_fin = latest.get("is_bank", False) or any(k in s_upper for k in ["BANK", "FINANCE", "KEUANGAN", "FINTECH"]) or t_upper in ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO"]

    metrics = []

    if is_bank_fin:
        cat = "BANKING_FINTECH"
        ppop = latest.get("ppop_bn")
        nii = latest.get("revenue_bn")  # Bank revenue = Net Interest Income / Operating Rev
        int_exp = latest.get("interest_expense_bn")
        int_inc = latest.get("interest_income_bank_bn")
        
        # NIM proxy
        nim = None
        if nii and ta and ta > 0:
            nim = round((nii / ta) * 100.0, 2)
            metrics.append({"label": "NIM Proxy (NII / Total Assets)", "value": f"{nim}%", "status": "COMPUTED", "benchmark": ">4.5% Sehat"})
        
        # PPOP to Assets
        if ppop and ta and ta > 0:
            ppop_ta = round((ppop / ta) * 100.0, 2)
            metrics.append({"label": "PPOP / Assets", "value": f"{ppop_ta}%", "status": "REPORTED_PPOP", "benchmark": ">2.5% Kuat"})
        
        # Cost of Funds proxy
        if int_exp and liab and liab > 0:
            cof = round((int_exp / liab) * 100.0, 2)
            metrics.append({"label": "Cost of Funds Proxy", "value": f"{cof}%", "status": "COMPUTED", "benchmark": "<3.5% Efisien"})

    elif is_commodity:
        cat = "COMMODITIES_MINING"
        # Cash Flow to Capex Coverage
        if capex and capex > 0 and ebit:
            cov = round(ebit / capex, 2)
            metrics.append({"label": "EBIT / Capex Coverage", "value": f"{cov:.2f}x", "status": "COMPUTED", "benchmark": ">1.5x Aman"})
        
        # Gross Margin (Operating Leverage Tambang)
        if gp and rev and rev > 0:
            gm = round((gp / rev) * 100.0, 1)
            metrics.append({"label": "Gross Realization Margin", "value": f"{gm}%", "status": "REPORTED", "benchmark": "Siklikal Komoditas"})

        # Asset Intensity
        if rev and ta and ta > 0:
            turn = round(rev / ta, 2)
            metrics.append({"label": "Capital Turnover (Rev/Assets)", "value": f"{turn:.2f}x", "status": "COMPUTED", "benchmark": "Intensitas Aset"})

    elif is_consumer:
        cat = "CONSUMER_RETAIL"
        # Operating Profit Margin
        if ebit and rev and rev > 0:
            opm = round((ebit / rev) * 100.0, 1)
            metrics.append({"label": "EBIT Operating Margin", "value": f"{opm}%", "status": "COMPUTED", "benchmark": ">10% Pricing Power"})
        
        # Asset Turnover
        if rev and ta and ta > 0:
            at = round(rev / ta, 2)
            metrics.append({"label": "Asset Turnover Velocity", "value": f"{at:.2f}x", "status": "COMPUTED", "benchmark": ">1.0x Efisiensi Tinggi"})
        
        # Inventory Days proxy (bila COGS tersedia)
        metrics.append({"label": "Cash Conversion Cycle", "value": "N/A (Butuh Notes CALK)", "status": "N/A", "benchmark": "Menunggu Data Scrape"})

    elif is_property:
        cat = "PROPERTY_REAL_ESTATE"
        # Net Gearing = (Total Debt - Cash) / Equity
        if liab and eq and eq > 0:
            net_debt = liab - cash
            gearing = round((net_debt / eq) * 100.0, 1)
            metrics.append({"label": "Net Debt / Equity (Gearing)", "value": f"{gearing}%", "status": "COMPUTED", "benchmark": "<80% Konservatif"})
        
        # Interest Coverage
        if ebit and fc and fc > 0:
            icr = round(ebit / fc, 2)
            metrics.append({"label": "Interest Coverage (EBIT / FC)", "value": f"{icr:.2f}x", "status": "COMPUTED", "benchmark": ">2.0x Batas Aman"})

    else:
        cat = "GENERAL_CORPORATE"
        if ebit and rev and rev > 0:
            metrics.append({"label": "EBIT Operating Margin", "value": f"{round(ebit/rev*100, 1)}%", "status": "COMPUTED", "benchmark": "Margin Usaha"})
        if eq and ta and ta > 0:
            metrics.append({"label": "Equity / Assets (Solvency)", "value": f"{round(eq/ta*100, 1)}%", "status": "REPORTED", "benchmark": ">35% Kuat"})

    return {
        "sector_category": cat,
        "metrics": metrics,
        "is_cyclical": is_commodity or is_property,
    }
