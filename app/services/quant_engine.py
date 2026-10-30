from __future__ import annotations
import math
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select

from app.db.models import FinancialStatementCache, QuoteLatest
from app.services.dupont_engine import (
    FinancialStatementInput,
    PeriodType,
    compute_single_period_dupont,
    analyze_dupont_yoy,
)
from app.services.banking_engine import calculate_banking_ratios
from app.services.fincept_fixed_income import calculate_credit_metrics
from app.services.fincept_valuation import quick_dcf_valuation


def run_monte_carlo_gbm(
    current_price: float,
    annual_drift: float = 0.10,
    annual_vol: float = 0.24,
    days: int = 252,
    n_paths: int = 200,
    seed: int = 42,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Simulasikan Geometric Brownian Motion (GBM) pure-Python / standard math.
    St = St-1 * exp((mu - 0.5 * sigma^2)*dt + sigma * sqrt(dt) * Z)
    """
    # Toleransi kwarg nama lain dari iterasi sebelumnya
    if "volatility" in kwargs and kwargs["volatility"] is not None:
        annual_vol = float(kwargs["volatility"])
    if "drift" in kwargs and kwargs["drift"] is not None:
        annual_drift = float(kwargs["drift"])
    if "simulations" in kwargs and kwargs["simulations"] is not None:
        n_paths = int(kwargs["simulations"])
    if "years" in kwargs and kwargs["years"] is not None:
        days = int(kwargs["years"] * 252)

    s0 = float(current_price) if current_price and current_price > 0 else 1000.0
    dt = 1.0 / 252.0
    drift_step = (annual_drift - 0.5 * (annual_vol ** 2)) * dt
    vol_step = annual_vol * math.sqrt(dt)

    # Deterministic pseudo-random normal via Box-Muller with LCG seed
    def _lcg_generator(s: int):
        import random as _rnd
        _r = _rnd.Random(s)
        while True:
            yield _r.gauss(0.0, 1.0)

    rng = _lcg_generator(seed)

    # Step sampling interval (sampling 26 points across days)
    sample_interval = max(1, days // 25)
    sample_day_indices = list(range(0, days + 1, sample_interval))
    if sample_day_indices[-1] != days:
        sample_day_indices.append(days)

    all_trajectories: List[List[float]] = []
    final_prices: List[float] = []

    for path_idx in range(n_paths):
        path_sampled: List[float] = [s0]
        cur_p = s0
        for d in range(1, days + 1):
            z = next(rng)
            cur_p = cur_p * math.exp(drift_step + vol_step * z)
            if d in sample_day_indices:
                path_sampled.append(round(cur_p, 2))
        final_prices.append(cur_p)
        if path_idx < 5:
            all_trajectories.append(path_sampled)

    final_prices.sort()
    n = len(final_prices)

    def _pct(p: float) -> float:
        idx = int(p * n)
        idx = min(max(0, idx), n - 1)
        return final_prices[idx]

    p10 = _pct(0.10)
    p50 = _pct(0.50)
    p90 = _pct(0.90)
    mean_val = sum(final_prices) / n

    prob_profit = sum(1 for p in final_prices if p > s0) / n * 100.0
    prob_up20 = sum(1 for p in final_prices if p > s0 * 1.20) / n * 100.0
    prob_dd20 = sum(1 for p in final_prices if p < s0 * 0.80) / n * 100.0

    # Build percentile bands across sample days
    # Simple linear dispersion cone from S0 to percentiles for SVG chart
    n_pts = len(sample_day_indices)
    p10_band = []
    p50_band = []
    p90_band = []
    for idx, d in enumerate(sample_day_indices):
        ratio = d / float(days) if days > 0 else 0
        p10_band.append(round(s0 + (p10 - s0) * ratio, 2))
        p50_band.append(round(s0 + (p50 - s0) * ratio, 2))
        p90_band.append(round(s0 + (p90 - s0) * ratio, 2))

    return {
        "current_price": round(s0, 2),
        "annual_drift": annual_drift,
        "annual_vol": annual_vol,
        "days": days,
        "n_paths": n_paths,
        "p10_price": round(p10, 2),
        "p50_price": round(p50, 2),
        "p90_price": round(p90, 2),
        "mean_price": round(mean_val, 2),
        "mean_final": round(mean_val, 2),  # alias compat
        "percentiles": {"p5": round(_pct(0.05), 2), "p50": round(p50, 2), "p95": round(_pct(0.95), 2)},
        "prob_profit_pct": round(prob_profit, 1),
        "probability_price_above_initial": prob_profit / 100.0,
        "prob_upside_20_pct": round(prob_up20, 1),
        "prob_drawdown_20_pct": round(prob_dd20, 1),
        "sample_days": sample_day_indices,
        "sample_paths": all_trajectories,
        "p10_band": p10_band,
        "p50_band": p50_band,
        "p90_band": p90_band,
    }


def _record_to_stmt_input(rec: FinancialStatementCache) -> FinancialStatementInput:
    p_type = PeriodType.FY
    try:
        p_type = PeriodType(rec.period_type)
    except Exception:
        pass
    return FinancialStatementInput(
        ticker=rec.ticker,
        company_name=rec.company_name,
        year=rec.year,
        period_type=p_type,
        currency=rec.currency or "IDR",
        unit_multiplier=rec.unit_multiplier or 1.0,
        revenue=rec.revenue,
        ebit=rec.ebit,
        ebt=rec.ebt,
        net_income_parent=rec.net_income_parent,
        total_assets=rec.total_assets,
        total_liabilities=rec.total_liabilities,
        total_equity_parent=rec.total_equity_parent,
        total_equity_consolidated=rec.total_equity_consolidated,
        sector=rec.sector,
        shares_outstanding=rec.shares_outstanding,
        cash_and_equivalents=rec.cash_and_equivalents,
        interest_bearing_debt=rec.interest_bearing_debt,
        current_assets=rec.current_assets,
        current_liabilities=rec.current_liabilities,
        interest_income=rec.interest_income,
        interest_expense=rec.interest_expense,
        tax_provision=rec.tax_provision,
        operating_cash_flow=rec.operating_cash_flow,
        capex=rec.capex,
        depreciation=rec.depreciation,
        minority_interest=rec.minority_interest,
    )


def build_peer_screener_rows(session: Session, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """
    Ambil seluruh emiten unik dari FinancialStatementCache, ambil 2 tahun terbaru per emiten,
    hitung DuPont bundle, Credit Grade, dan Fair Value.
    """
    tickers = [str(t) for t in session.exec(select(FinancialStatementCache.ticker).distinct()).all()]
    if not tickers:
        return []

    rows: List[Dict[str, Any]] = []

    for t in sorted(tickers):
        stmts = session.exec(
            select(FinancialStatementCache)
            .where(FinancialStatementCache.ticker == t)
            .order_by(FinancialStatementCache.year.desc())
        ).all()
        if not stmts:
            continue

        curr_rec = stmts[0]
        prev_rec = stmts[1] if len(stmts) > 1 else None

        curr_in = _record_to_stmt_input(curr_rec)
        prev_in = _record_to_stmt_input(prev_rec) if prev_rec else None

        bundle = analyze_dupont_yoy(curr_in, prev_in)
        curr_m = bundle.current

        # Skala satuan untuk credit & valuation
        factor_to_bn = 1.0 if curr_in.revenue < 1e9 else ((curr_in.unit_multiplier or 1.0) / 1e9)
        ta_bn = curr_in.total_assets * factor_to_bn
        tl_bn = curr_in.total_liabilities * factor_to_bn
        te_bn = curr_in.total_equity_parent * factor_to_bn
        debt_bn = (curr_in.interest_bearing_debt * factor_to_bn) if curr_in.interest_bearing_debt else (tl_bn * 0.45)
        ca_bn = (curr_in.current_assets * factor_to_bn) if curr_in.current_assets else (ta_bn * 0.4)
        cl_bn = (curr_in.current_liabilities * factor_to_bn) if curr_in.current_liabilities else (tl_bn * 0.5)
        cash_bn = (curr_in.cash_and_equivalents * factor_to_bn) if curr_in.cash_and_equivalents else (ta_bn * 0.12)
        ebit_bn = curr_in.ebit * factor_to_bn
        int_exp_bn = (curr_in.interest_expense * factor_to_bn) if curr_in.interest_expense else (debt_bn * 0.07)
        ocf_bn = (curr_in.operating_cash_flow * factor_to_bn) if curr_in.operating_cash_flow else (ebit_bn * 1.0)
        dep_bn = (curr_in.depreciation * factor_to_bn) if curr_in.depreciation else (ebit_bn * 0.2)
        capex_bn = (curr_in.capex * factor_to_bn) if curr_in.capex else (ebit_bn * 0.35)

        # Banking check first
        banking_data = {
            "ticker": curr_in.ticker,
            "sector": curr_in.sector,
            "revenue": curr_in.revenue,
            "net_income": curr_in.net_income_parent,
            "total_assets": curr_in.total_assets,
            "total_equity": curr_in.total_equity_parent * (factor_to_bn * 1e9 if curr_in.revenue < 1e9 else 1.0),
            "total_debt": curr_in.total_liabilities,
            "ebit": curr_in.ebit,
            "ebt": curr_in.ebt,
            "interest_income": curr_in.interest_income or 0.0,
            "interest_expense": curr_in.interest_expense or 0.0,
            "tax_provision": curr_in.tax_provision or 0.0,
            "pretax_income": curr_in.ebt or 0.0,
            "shares_outstanding": curr_in.shares_outstanding or 0.0,
            "period": curr_in.year,
        }
        b_ratios = calculate_banking_ratios(banking_data)

        # Credit metrics
        credit = calculate_credit_metrics(
            total_assets=ta_bn,
            total_liabilities=tl_bn,
            total_debt=debt_bn,
            current_assets=ca_bn,
            current_liabilities=cl_bn,
            cash_and_equivalents=cash_bn,
            ebit=ebit_bn,
            interest_expense=int_exp_bn,
            cash_flow_from_operations=ocf_bn,
            net_income=curr_in.net_income_parent * factor_to_bn,
            is_bank=(b_ratios is not None),
        )

        fair_val: Optional[float] = None
        if b_ratios is not None and getattr(b_ratios, "fair_value_per_share", None):
            fair_val = round(b_ratios.fair_value_per_share, 0)
        else:
            shares_out = curr_in.shares_outstanding or 0.0
            shares_m = (shares_out / 1e6) if shares_out > 0 else max(100.0, te_bn * 1e9 / 5000 / 1e6)
            try:
                dcf_res = quick_dcf_valuation(
                    ticker=curr_in.ticker,
                    risk_free_rate=6.85,
                    market_risk_premium=6.5,
                    levered_beta=1.0,
                    cost_of_debt_pre_tax=7.5,
                    tax_rate=0.22,
                    target_debt_ratio=0.30,
                    ebit=ebit_bn,
                    depreciation=dep_bn,
                    capex=capex_bn,
                    wc_change=ebit_bn * 0.05,
                    fcf_growth_rate=0.05,
                    terminal_growth_rate=0.025,
                    total_assets=ta_bn,
                    total_debt=debt_bn,
                    cash=cash_bn,
                    shares_outstanding_m=shares_m,
                )
                if dcf_res and dcf_res.get("price_per_share"):
                    fair_val = round(dcf_res["price_per_share"], 0)
            except Exception:
                fair_val = None

        roe_val = curr_m.roe if curr_m.roe is not None else 0.0
        roe_bps = bundle.yoy_deltas.get("roe").bps_change if (bundle.yoy_deltas and bundle.yoy_deltas.get("roe")) else 0.0

        # Verdict ringkas
        verdict = "High Quality"
        if curr_m.accrual_anomaly_detected:
            verdict = "Accrual Alert"
        elif roe_val < 0.08:
            verdict = "Low Return"

        rows.append({
            "ticker": curr_in.ticker,
            "company_name": curr_in.company_name,
            "sector": curr_in.sector or ("Financials" if b_ratios else "Industrials"),
            "year": curr_in.year,
            "roe_pct": round(roe_val * 100.0, 2),
            "roe_yoy_bps": round(roe_bps or 0.0, 0),
            "npm_pct": round((curr_m.net_profit_margin or 0.0) * 100.0, 2),
            "ebit_margin_pct": round((curr_m.ebit_margin or 0.0) * 100.0, 2),
            "asset_turnover": round(curr_m.asset_turnover or 0.0, 3),
            "equity_multiplier": round(curr_m.equity_multiplier or 0.0, 2),
            "ocf_to_ni": round(curr_m.ocf_to_net_income, 2) if curr_m.ocf_to_net_income is not None else None,
            "credit_grade": credit.credit_grade,
            "credit_score": credit.credit_score,
            "fair_value": fair_val,
            "quality_verdict": verdict,
            "primary_driver": bundle.primary_driver.value,
        })

    rows.sort(key=lambda r: (r["roe_pct"] or -999.0), reverse=True)
    return rows
