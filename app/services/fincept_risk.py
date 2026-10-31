"""
app/services/fincept_risk.py
Risk Analytics — Port dari FinceptTerminal:
  fincept-qt/scripts/Analytics/alternateInvestment/risk_analyzer.py

Fitur:
  - Sharpe Ratio, Sortino Ratio, Calmar Ratio
  - Value at Risk (VaR) & CVaR / Expected Shortfall
  - Maximum Drawdown
  - Beta & CAPM Alpha
  - Information Ratio
  - Risk-adjusted returns

Python-native, zero external dependency.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class RiskMetrics:
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration: int  # days
    var_95: float
    cvar_95: float
    beta: float
    alpha_annualized: float
    information_ratio: float
    treynor_ratio: float
    # Ditambahkan: sebelumnya volatilitas & return tidak diekspos sama sekali
    # padahal sudah dihitung — UI tidak bisa menampilkan risiko absolut.
    volatility_annual: float = 0.0
    annualized_return: float = 0.0   # aritmetik (mean x 252), dasar Sharpe/alpha
    cagr: float = 0.0                # geometrik (majemuk), dasar Calmar

@dataclass
class ReturnStats:
    total_return: float
    annualized_return: float
    volatility: float
    downside_deviation: float
    avg_return: float


def _to_returns(prices: List[float]) -> List[float]:
    """Convert price series to return series."""
    if len(prices) < 2:
        return []
    return [(prices[i] / prices[i-1]) - 1 for i in range(1, len(prices))]


def _downside_returns(returns: List[float], target: float = 0.0) -> List[float]:
    """Returns below target (negative only)."""
    return [r for r in returns if r < target]


def calculate_risk_metrics(
    prices: List[float],
    benchmark_prices: Optional[List[float]] = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> RiskMetrics:
    """
    Full risk analytics dari return series.

    Args:
        prices: Harga penutupan harian (index harga)
        benchmark_prices: Harga benchmark untuk beta/alpha (misal: IHSG)
        risk_free_rate: Suku bunga bebas risiko annualized (default 0 = assume 0)
        periods_per_year: Hari trading per tahun (252 = harian Indonesia)
    """
    returns = _to_returns(prices)
    if not returns:
        return RiskMetrics(0,0,0,0,0,0,0,0,0,0,0)

    n = len(returns)
    avg_ret = sum(returns) / n

    # Volatilitas (annualized)
    variance = sum((r - avg_ret) ** 2 for r in returns) / (n - 1)
    volatility = math.sqrt(variance * periods_per_year)

    # Downside deviation (Sortino)
    down_returns = _downside_returns(returns)
    if down_returns:
        down_var = sum(r ** 2 for r in down_returns) / n
        downside_dev = math.sqrt(down_var * periods_per_year)
    else:
        downside_dev = 1e-9  # avoid div by zero

    # Annualized returns
    total_ret = (prices[-1] / prices[0]) - 1 if prices else 0
    ann_ret = (1 + total_ret) ** (periods_per_year / n) - 1 if n > 0 else 0

    # Risk-free
    rf_period = risk_free_rate / periods_per_year
    excess = [r - rf_period for r in returns]

    # Basis konsisten untuk seluruh rasio risk-adjusted:
    # - Sharpe/Sortino/Treynor/Alpha secara teori memakai return ARITMETIK
    #   annualized (mean harian x 252), bukan CAGR geometrik.
    # - Calmar memakai CAGR karena berpasangan dengan drawdown (keduanya
    #   tentang kekayaan akhir).
    ann_arith = avg_ret * periods_per_year
    cagr = ann_ret                      # ann_ret di atas = geometrik

    # Sharpe Ratio
    if volatility > 0:
        sharpe = (ann_arith - risk_free_rate) / volatility
    else:
        sharpe = 0.0

    # Sortino Ratio
    if downside_dev > 0:
        sortino = (ann_arith - risk_free_rate) / downside_dev
    else:
        sortino = 0.0

    # Calmar Ratio (annualized return / max drawdown)
    mdd, mdd_dur = max_drawdown(prices)
    if mdd > 0:
        calmar = ann_ret / mdd
    else:
        calmar = 0.0

    # VaR 95% (historical)
    sorted_ret = sorted(returns)
    var_idx = int(n * 0.05)
    var_95 = -sorted_ret[var_idx] if var_idx < n else 0.0
    # CVaR / Expected Shortfall
    cvar_95 = -sum(sorted_ret[:var_idx]) / var_idx if var_idx > 0 else 0.0

    # Beta & Alpha vs benchmark
    beta = 0.0
    alpha_annualized = 0.0
    if benchmark_prices:
        b_returns = _to_returns(benchmark_prices)
        min_len = min(len(returns), len(b_returns))
        if min_len >= 2:
            cr, cb = returns[:min_len], b_returns[:min_len]
            cov = sum((r - avg_ret) * (b - sum(cb)/min_len) for r, b in zip(cr, cb)) / (min_len - 1)
            b_var = sum((b - sum(cb)/min_len) ** 2 for b in cb) / (min_len - 1)
            beta = cov / b_var if b_var > 0 else 0.0
            # Alpha CAPM: return aktual - return yang diharapkan dari beta.
            # Sebelumnya memakai CAGR (geometrik) dikurangi beta x aritmetik —
            # dua basis berbeda dicampur, sehingga angkanya berbeda dari
            # engine performa (8,37% vs 3,85%) untuk saham yang sama.
            ann_b = sum(cb) / min_len * periods_per_year
            alpha_annualized = ann_arith - (risk_free_rate + beta * (ann_b - risk_free_rate))

    # Treynor Ratio
    if beta > 0:
        treynor = (ann_ret - risk_free_rate) / beta
    else:
        treynor = 0.0

    # Information Ratio (annualized return - benchmark annualized) / tracking error
    ir = 0.0
    if benchmark_prices:
        b_returns_full = _to_returns(benchmark_prices)
        min_len = min(len(returns), len(b_returns_full))
        if min_len >= 2:
            active = [returns[i] - b_returns_full[i] for i in range(min_len)]
            mean_active = sum(active) / min_len
            trk_error = math.sqrt(sum((a - mean_active)**2 for a in active) / (min_len - 1)) * math.sqrt(periods_per_year)
            b_total_ret = (benchmark_prices[-1] / benchmark_prices[0]) - 1 if benchmark_prices[0] > 0 else 0
            b_ann_ret = (1 + b_total_ret) ** (periods_per_year / len(benchmark_prices)) - 1 if len(benchmark_prices) > 0 else 0
            if trk_error > 1e-6:
                ir = (ann_ret - b_ann_ret) / trk_error

    return RiskMetrics(
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        calmar_ratio=round(calmar, 4),
        max_drawdown=round(mdd, 4),
        max_drawdown_duration=mdd_dur,
        var_95=round(var_95, 4),
        cvar_95=round(cvar_95, 4),
        beta=round(beta, 4),
        alpha_annualized=round(alpha_annualized, 4),
        information_ratio=round(ir, 4),
        treynor_ratio=round(treynor, 6),
        volatility_annual=round(volatility, 4),
        annualized_return=round(ann_arith, 4),
        cagr=round(cagr, 4),
    )


def max_drawdown(prices: List[float]) -> tuple[float, int]:
    """
    Calculate maximum drawdown and its duration.

    Returns: (max_drawdown_pct, duration_days)
    """
    if not prices:
        return 0.0, 0

    peak = prices[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_duration = 0

    for i, p in enumerate(prices):
        if p > peak:
            peak = p
            peak_idx = i
            current_dd_duration = 0
        dd = (peak - p) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_duration = i - peak_idx
            current_dd_duration = 0
        else:
            current_dd_duration += 1

    return max_dd, max_dd_duration


def var_historical(returns: List[float], confidence: float = 0.95) -> float:
    """Historical VaR at given confidence level."""
    if not returns:
        return 0.0
    sorted_ret = sorted(returns)
    idx = int(len(sorted_ret) * (1 - confidence))
    return -sorted_ret[min(idx, len(sorted_ret)-1)]


def cvar_historical(returns: List[float], confidence: float = 0.95) -> float:
    """Conditional VaR / Expected Shortfall."""
    if not returns:
        return 0.0
    sorted_ret = sorted(returns)
    idx = int(len(sorted_ret) * (1 - confidence))
    tail = sorted_ret[:max(1, idx)]
    return -(sum(tail) / len(tail)) if tail else 0.0


def risk_contribution(weights: List[float], cov_matrix: List[List[float]]) -> List[float]:
    """
    Calculate risk contribution per asset in a portfolio.
    Weights in decimals, covariance matrix annualized.
    """
    n = len(weights)
    if n == 0 or len(cov_matrix) != n:
        return []

    # Portfolio variance
    port_var = 0.0
    for i in range(n):
        for j in range(n):
            port_var += weights[i] * weights[j] * cov_matrix[i][j]

    port_vol = math.sqrt(port_var) if port_var > 0 else 1e-9
    contributions = []
    for i in range(n):
        rc = sum(weights[j] * cov_matrix[i][j] for j in range(n)) * weights[i] / port_vol
        contributions.append(rc)
    return contributions


def beta_from_prices(prices: List[float], market_prices: List[float]) -> float:
    """Simple beta calculation from price series."""
    rets = _to_returns(prices)
    mrets = _to_returns(market_prices)
    n = min(len(rets), len(mrets))
    if n < 2:
        return 0.0

    r_mean = sum(rets) / n
    m_mean = sum(mrets) / n
    cov = sum((rets[i] - r_mean) * (mrets[i] - m_mean) for i in range(n)) / (n - 1)
    m_var = sum((m - m_mean) ** 2 for m in mrets[:n]) / (n - 1)
    return cov / m_var if m_var > 0 else 0.0


# ─── CLI demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Simulated BBCA daily prices (100 trading days, 20% annual return, 15% vol)
    import random
    random.seed(42)
    n = 100
    base = 100.0
    prices = [base]
    for i in range(n):
        ret = 0.20/252 + 0.15/math.sqrt(252) * random.gauss(0, 1)
        prices.append(prices[-1] * (1 + ret))

    # Simulated IHSG benchmark
    mkt = [100.0]
    for i in range(n):
        ret = 0.08/252 + 0.12/math.sqrt(252) * random.gauss(0, 1)
        mkt.append(mkt[-1] * (1 + ret))

    rm = calculate_risk_metrics(prices, mkt, risk_free_rate=0.07)
    print(f"=== BBCA Simulated Risk Metrics (100 trading days) ===")
    print(f"  Sharpe: {rm.sharpe_ratio}")
    print(f"  Sortino: {rm.sortino_ratio}")
    print(f"  Calmar:  {rm.calmar_ratio}")
    print(f"  Max DD:  {rm.max_drawdown*100:.2f}%")
    print(f"  VaR 95%: {rm.var_95*100:.2f}%")
    print(f"  CVaR 95%: {rm.cvar_95*100:.2f}%")
    print(f"  Beta:   {rm.beta}")
    print(f"  Alpha:  {rm.alpha_annualized*100:.2f}%")
