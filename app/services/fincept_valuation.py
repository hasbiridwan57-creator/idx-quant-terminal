"""
app/services/fincept_valuation.py
DCF Valuation Engine — Port dari FinceptTerminal:
  fincept-qt/scripts/Analytics/corporateFinance/valuation/dcf_model.py

Fitur:
  - WACC calculator (CAPM + Cost of Debt)
  - Unlevered / Relevered Beta
  - Free Cash Flow projection
  - Gordon Growth / Terminal Value
  - Enterprise Value → Equity Value → Price per Share
  - Sensitivity Analysis (2D matrix)
  - Scenario Analysis (Bull/Base/Bear)
  - Python-native, zero external dependency

Digunakan untuk valuasi intrinsik saham BEI.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import math

# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class WACCInputs:
    risk_free_rate: float        # SBN 10Y yield (%)
    market_risk_premium: float   # MRP (%)
    levered_beta: float          # βL (from Yahoo Finance)
    cost_of_debt_pre_tax: float  # Kd (%)
    tax_rate: float              # corporate tax (%)
    target_debt_ratio: float     # D/(D+E) target (%)

@dataclass
class DCFResult:
    wacc: float
    enterprise_value: float
    equity_value: float
    price_per_share: float
    terminal_value: float
    fcf_projections: List[float]
    sensitivity: Optional[Dict[str, List[List[float]]]]
    scenario: Optional[Dict[str, Any]]


# ─── WACC / Beta ──────────────────────────────────────────────────────────────

class DCFModel:
    def __init__(self, company_name: str):
        self.company_name = company_name

    def calculate_wacc(
        self,
        risk_free_rate: float,
        market_risk_premium: float,
        levered_beta: float,
        cost_of_debt_pre_tax: float,
        tax_rate: float,
        target_debt_ratio: float,
    ) -> float:
        """WACC = Ke × (1-D%) + Kd × (1-t) × D%"""
        ke = risk_free_rate + levered_beta * market_risk_premium
        kd = cost_of_debt_pre_tax * (1 - tax_rate)
        wacc = ke * (1 - target_debt_ratio) + kd * target_debt_ratio
        return wacc / 100  # convert to decimal for projection

    def unlever_beta(self, levered_beta: float, tax_rate: float, debt_ratio: float) -> float:
        """Remove financial leverage: βU = βL / (1 + (1-t) × D/E)"""
        if debt_ratio <= 0 or debt_ratio >= 1:
            return levered_beta
        de_ratio = debt_ratio / (1 - debt_ratio)
        return levered_beta / (1 + (1 - tax_rate) * de_ratio)

    def relever_beta(self, unlevered_beta: float, tax_rate: float, debt_ratio: float) -> float:
        """Add financial leverage: βL = βU × (1 + (1-t) × D/E)"""
        if debt_ratio <= 0 or debt_ratio >= 1:
            return unlevered_beta
        de_ratio = debt_ratio / (1 - debt_ratio)
        return unlevered_beta * (1 + (1 - tax_rate) * de_ratio)

    def calculate_free_cash_flow(
        self,
        ebit: float,
        tax_rate: float,
        depreciation: float,
        capex: float,
        change_in_working_capital: float,
    ) -> float:
        """FCF = EBIT × (1-t) + D&A - Capex - ΔWC"""
        ebit_after_tax = ebit * (1 - tax_rate)
        return ebit_after_tax + depreciation - capex - change_in_working_capital

    def project_cash_flows(
        self,
        base_year_fcf: float,
        growth_rate: float,
        years: int,
    ) -> List[float]:
        """Project FCF dengan growth rate konstan."""
        return [base_year_fcf * (1 + growth_rate) ** (i + 1) for i in range(years)]

    def calculate_terminal_value(
        self,
        final_year_fcf: float,
        terminal_growth_rate: float,
        wacc: float,
    ) -> float:
        """Gordon Growth Model: TV = FCF_{n+1} / (WACC - g)"""
        if wacc <= terminal_growth_rate:
            return 0.0
        return final_year_fcf * (1 + terminal_growth_rate) / (wacc - terminal_growth_rate)

    def calculate_enterprise_value(
        self,
        fcf_projections: List[float],
        terminal_value: float,
        wacc: float,
    ) -> float:
        """PV of FCF + PV of Terminal Value"""
        ev = 0.0
        for i, fcf in enumerate(fcf_projections):
            ev += fcf / (1 + wacc) ** (i + 1)
        ev += terminal_value / (1 + wacc) ** len(fcf_projections)
        return ev

    def calculate_equity_value(
        self,
        enterprise_value: float,
        total_debt: float,
        cash_and_equivalents: float,
        minority_interest: float,
    ) -> float:
        """Equity Value = EV - Total Debt + Cash - Minority Interest
        (minority interest is a claim by 3rd parties and must be subtracted from EV)"""
        return enterprise_value - total_debt + cash_and_equivalents - minority_interest

    def calculate_price_per_share(
        self,
        equity_value: float,
        shares_outstanding: float,
    ) -> float:
        """Harga per saham = Equity Value / Saham Beredar"""
        if shares_outstanding <= 0:
            return 0.0
        return equity_value / shares_outstanding

    def comprehensive_dcf(
        self,
        wacc_inputs: Dict[str, float],
        fcf_inputs: Dict[str, float],
        terminal_inputs: Dict[str, float],
        balance_sheet: Dict[str, float],
        shares_outstanding: float,
        projection_years: int = 5,
    ) -> DCFResult:
        """Full DCF calculation pipeline."""
        # Unlever beta untuk D/E target
        beta = wacc_inputs.get("levered_beta", 1.0)
        tax = wacc_inputs.get("tax_rate", 0.25)
        d_ratio = wacc_inputs.get("target_debt_ratio", 0.3)

        # WACC OVERRIDE: bila pemanggil sudah menghitung WACC lewat
        # cost_of_capital.compute_wacc (sumber tunggal untuk tab Peers, EVA,
        # dan halaman utama), pakai angka itu apa adanya. Tanpa ini DCF
        # meng-unlever lalu me-relever beta dan memakai ERP 6,5% sendiri,
        # menghasilkan ASII 10,54% vs 11,64% untuk emiten yang sama.
        _wacc_override = wacc_inputs.get("wacc_override")
        if _wacc_override:
            wacc = float(_wacc_override) / 100.0
        else:
            u_beta = self.unlever_beta(beta, tax, d_ratio)
            r_beta = self.relever_beta(u_beta, tax, d_ratio)
            wacc = self.calculate_wacc(
                wacc_inputs["risk_free_rate"],
                wacc_inputs["market_risk_premium"],
                r_beta,
                wacc_inputs["cost_of_debt_pre_tax"],
                tax,
                d_ratio,
            )

        base_fcf = self.calculate_free_cash_flow(
            fcf_inputs["ebit"],
            tax,
            fcf_inputs.get("depreciation", 0),
            fcf_inputs.get("capex", 0),
            fcf_inputs.get("change_in_working_capital", 0),
        )

        fcf_projections = self.project_cash_flows(
            base_fcf, wacc_inputs.get("fcf_growth_rate", 0.05), projection_years
        )

        terminal_value = self.calculate_terminal_value(
            fcf_projections[-1],
            terminal_inputs["terminal_growth_rate"],
            wacc,
        )

        ev = self.calculate_enterprise_value(fcf_projections, terminal_value, wacc)
        eq = self.calculate_equity_value(
            ev,
            balance_sheet.get("total_debt", 0),
            balance_sheet.get("cash", 0),
            balance_sheet.get("minority_interest", 0),
        )
        price = self.calculate_price_per_share(eq, shares_outstanding)

        return DCFResult(
            wacc=wacc,
            enterprise_value=ev,
            equity_value=eq,
            price_per_share=price,
            terminal_value=terminal_value,
            fcf_projections=fcf_projections,
            sensitivity=None,
            scenario=None,
        )

    def sensitivity_analysis(
        self,
        base_fcf: float,
        wacc: float,
        terminal_growth: float,
        years: int = 5,
    ) -> Dict[str, List[List[float]]]:
        """2D sensitivity: WACC (columns) × Terminal Growth (rows) → EV in Trillion IDR"""
        wacc_range = [wacc + d for d in [-0.02, -0.01, 0.0, 0.01, 0.02]]
        tg_range   = [terminal_growth + d for d in [-0.015, -0.0075, 0.0, 0.0075, 0.015]]

        projections = self.project_cash_flows(base_fcf, 0.03, years)
        rows = []
        for tg in tg_range:
            row = []
            for w in wacc_range:
                tv = self.calculate_terminal_value(projections[-1], tg, w)
                ev = self.calculate_enterprise_value(projections, tv, w)
                # ev is already in Billion IDR; divide by 1000 → Trillion IDR
                row.append(round(ev / 1000.0, 2))
            rows.append(row)

        return {
            "wacc_range": [f"{w*100:.1f}%" for w in wacc_range],
            "tg_range":   [f"{t*100:.2f}%" for t in tg_range],
            "ev_matrix":  rows,
        }

    def scenario_analysis(
        self,
        wacc_inputs: Dict[str, float],
        fcf_inputs: Dict[str, float],
        terminal_inputs: Dict[str, float],
        balance_sheet: Dict[str, float],
        shares_outstanding: float,
        projection_years: int = 5,
    ) -> Dict[str, DCFResult]:
        """Bull / Base / Bear scenario."""
        scenarios = {
            "BULL":  {
                "fcf_growth_rate": 0.08, "terminal_growth_rate": 0.035,
                "cost_of_debt_pre_tax": wacc_inputs["cost_of_debt_pre_tax"] * 0.9,
                "target_debt_ratio": max(0, wacc_inputs["target_debt_ratio"] - 0.1),
            },
            "BASE":  {
                "fcf_growth_rate": 0.05, "terminal_growth_rate": 0.025,
                "cost_of_debt_pre_tax": wacc_inputs["cost_of_debt_pre_tax"],
                "target_debt_ratio": wacc_inputs["target_debt_ratio"],
            },
            "BEAR":  {
                "fcf_growth_rate": 0.02, "terminal_growth_rate": 0.015,
                "cost_of_debt_pre_tax": wacc_inputs["cost_of_debt_pre_tax"] * 1.2,
                "target_debt_ratio": min(0.6, wacc_inputs["target_debt_ratio"] + 0.1),
            },
        }
        results = {}
        for name, overrides in scenarios.items():
            inp = {**wacc_inputs, **overrides}
            r = self.comprehensive_dcf(inp, fcf_inputs, terminal_inputs, balance_sheet, shares_outstanding, projection_years)
            results[name] = r
        return results


# ─── Convenience function ───────────────────────────────────────────────────────

def quick_dcf_valuation(
    ticker: str,
    # WACC inputs
    risk_free_rate: float = 7.0,       # SBN 10Y yield (%)
    market_risk_premium: float = 7.5, # MRP (%)

    # Balance sheet (dalam miliar IDR = 10^9)
    total_assets: float = 100_000,
    total_debt: float = 50_000,
    cash: float = 10_000,
    shares_outstanding_m: float = 10_000,  # juta lembar (10^6)
    # FCF inputs
    ebit: float = 20_000,
    depreciation: float = 5_000,
    capex: float = 3_000,
    wc_change: float = 1_000,
    # Valuation assumptions
    fcf_growth_rate: float = 0.05,
    terminal_growth_rate: float = 0.025,
    levered_beta: float = 1.0,
    cost_of_debt_pre_tax: float = 8.5,
    tax_rate: float = 0.25,
    target_debt_ratio: float = 0.35,
    # WACC yang sudah dihitung sumber lain (cost_of_capital.compute_wacc).
    # Bila diisi, model memakainya apa adanya agar DCF dan tab Peers/EVA
    # menyebut angka yang sama.
    wacc_override: Optional[float] = None,
    projection_years: int = 5,
    # Current market price (optional, dalam IDR per lembar)
    current_market_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Quick DCF valuation untuk saham BEI.
    Semua angka dalam miliar IDR (10^9), kecuali stated otherwise.
    shares_outstanding_m dalam juta lembar (10^6).
    """
    model = DCFModel(ticker)

    wacc_inputs = dict(
        risk_free_rate=risk_free_rate,
        market_risk_premium=market_risk_premium,
        levered_beta=levered_beta,
        cost_of_debt_pre_tax=cost_of_debt_pre_tax,
        tax_rate=tax_rate,
        target_debt_ratio=target_debt_ratio,
        fcf_growth_rate=fcf_growth_rate,
        wacc_override=wacc_override,
    )

    fcf_inp = dict(
        ebit=ebit,
        depreciation=depreciation,
        capex=capex,
        change_in_working_capital=wc_change,
    )

    term_inp = dict(terminal_growth_rate=terminal_growth_rate)

    bs = dict(
        total_debt=total_debt,
        cash=cash,
        minority_interest=0,
    )

    # Convert shares: juta → miliar = bagi 1000
    shares_in_bn = shares_outstanding_m / 1000.0

    result = model.comprehensive_dcf(
        wacc_inputs, fcf_inp, term_inp, bs, shares_in_bn, projection_years
    )
    sensitivity = model.sensitivity_analysis(
        model.calculate_free_cash_flow(ebit, tax_rate, depreciation, capex, wc_change),
        result.wacc,
        terminal_growth_rate,
        projection_years,
    )
    scenarios = model.scenario_analysis(
        wacc_inputs, fcf_inp, term_inp, bs, shares_in_bn, projection_years
    )

    # price_per_share from comprehensive_dcf is already in IDR (EV in bn IDR / shares in bn)
    price_per_share = max(0.0, round(result.price_per_share, 0))

    # Base case values in Billion IDR (raw values from DCF, no extra /1e9)
    enterprise_value_bn = result.enterprise_value
    equity_value_bn = result.equity_value
    terminal_value_bn = result.terminal_value

    # Trillion IDR versions
    enterprise_value_trn = round(enterprise_value_bn / 1000.0, 2)
    equity_value_trn = round(equity_value_bn / 1000.0, 2)
    terminal_value_trn = round(terminal_value_bn / 1000.0, 2)

    ret = {
        "ticker": ticker,
        "wacc_pct": round(result.wacc * 100, 2),
        "enterprise_value_bn": round(enterprise_value_bn, 2),
        "equity_value_bn": round(equity_value_bn, 2),
        "price_per_share": price_per_share,
        "terminal_value_bn": round(terminal_value_bn, 2),
        # Trillion IDR aliases
        "enterprise_value_trn": enterprise_value_trn,
        "equity_value_trn": equity_value_trn,
        "terminal_value_trn": terminal_value_trn,
        # FCF projections in Billion IDR
        "fcf_projections_bn": [round(f, 2) for f in result.fcf_projections],
        "sensitivity": sensitivity,
        "scenarios": {
            s: {"price": max(0.0, round(r.price_per_share, 0)), "wacc": round(r.wacc * 100, 2)}
            for s, r in scenarios.items()
        },
    }

    # Upside/downside analysis if current market price provided
    if current_market_price is not None and current_market_price > 0:
        upside_pct = round((price_per_share - current_market_price) / current_market_price * 100, 2)
        if upside_pct > 20:
            valuation_status = "UNDERVALUED"
        elif upside_pct < -20:
            valuation_status = "OVERVALUED"
        else:
            valuation_status = "FAIR VALUE"
        ret["current_price"] = current_market_price
        ret["upside_pct"] = upside_pct
        ret["valuation_status"] = valuation_status

    return ret


if __name__ == "__main__":
    # Demo: BBCA DCF valuation
    # All inputs in Billion IDR (10^9), shares in Million Shares (10^6)
    sample = quick_dcf_valuation(
        ticker="BBCA",
        ebit=81_690.531,           # 81.7T IDR → 81,690.531 Bn IDR
        depreciation=2_000,         # 2T
        capex=5_000,                 # 5T
        wc_change=500,               # 0.5T
        shares_outstanding_m=48_985, # ~48,985 M shares
        levered_beta=0.75,
        risk_free_rate=7.0,
        market_risk_premium=7.5,
        total_assets=1_586_828.536,  # 1,586,828.536 Bn IDR
        total_debt=2_395.446,        # 2,395.446 Bn IDR
        cash=200_000,                # 200,000 Bn IDR
        terminal_growth_rate=0.025,
        current_market_price=8_950,  # BBCA price ~ Rp 8,950
    )
    print(f"DCF for {sample['ticker']}")
    print(f"  WACC: {sample['wacc_pct']}%")
    print(f"  EV: Rp {sample['enterprise_value_trn']} T  ({sample['enterprise_value_bn']} Bn)")
    print(f"  Equity: Rp {sample['equity_value_trn']} T  ({sample['equity_value_bn']} Bn)")
    print(f"  Price: Rp {sample['price_per_share']}")
    if "upside_pct" in sample:
        print(f"  Current Price: Rp {sample['current_price']} | Upside: {sample['upside_pct']}% ({sample['valuation_status']})")
    print(f"  Scenarios:")
    for s, d in sample['scenarios'].items():
        print(f"    {s}: Rp {d['price']} @ WACC {d['wacc']}%")
