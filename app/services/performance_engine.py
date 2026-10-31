"""
Performance & Risk Engine — Institutional Grade (CFA / GIPS aligned).

Menghitung metrik performa historis dari OHLCV harian yang tersimpan di DB:
  Return      : CAGR, total return, annualized return
  Risk        : Volatility (annualized), downside deviation
  Risk-adj    : Sharpe, Sortino, Calmar, Information Ratio, Treynor
  Drawdown    : Max Drawdown, longest drawdown, recovery, Ulcer Index
  Market      : Beta, Alpha (Jensen), R², correlation vs benchmark
  Distribution: Skewness, Kurtosis, VaR 95/99, CVaR (Expected Shortfall)
  Consistency : Hit rate (win days), best/worst day, positive months

ZERO-FAKE:
  - Semua dari harga riil di DB. Tidak ada simulasi, tidak ada angka karangan.
  - Data kurang dari MIN_OBS -> kembalikan None + alasan, bukan angka nol.
  - Metrik yang butuh benchmark -> None jika benchmark tidak tersedia.

Referensi formula:
  Sharpe   = (Rp - Rf) / sigma_p                      (Sharpe 1966, annualized)
  Sortino  = (Rp - Rf) / sigma_downside               (Sortino & Price 1994)
  Calmar   = CAGR / |MaxDD|                           (Young 1991)
  Jensen a = Rp - [Rf + beta*(Rm - Rf)]               (Jensen 1968)
  IR       = (Rp - Rb) / tracking_error               (excess return vs benchmark)
  VaR 95   = percentile(returns, 5)                   (historical, bukan parametrik)
  CVaR 95  = mean(returns <= VaR)
  Ulcer    = sqrt(mean(drawdown_pct^2))               (Martin & McCann 1989)
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlmodel import Session

MIN_OBS = 60           # minimum observasi harian agar metrik bermakna
TRADING_DAYS = 252


# ─────────────────────────────────────────────────────────────────
# Data access
# ─────────────────────────────────────────────────────────────────
def load_prices(session: Session, ticker: str,
                start: Optional[str] = None,
                end: Optional[str] = None) -> List[Tuple[str, float]]:
    """Ambil (date, close) terurut naik. Hanya harga valid (> 0)."""
    q = "SELECT date, close FROM quotehistorydaily WHERE ticker = :t AND close > 0"
    params: Dict[str, Any] = {"t": ticker.upper()}
    if start:
        q += " AND date >= :s"
        params["s"] = start
    if end:
        q += " AND date <= :e"
        params["e"] = end
    q += " ORDER BY date ASC"
    rows = session.execute(text(q), params).fetchall()
    return [(r[0], float(r[1])) for r in rows if r[1] is not None]


# ─────────────────────────────────────────────────────────────────
# Statistik dasar (pure python, tanpa numpy dependency di runtime)
# ─────────────────────────────────────────────────────────────────
def _mean(xs: List[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _stdev(xs: List[float]) -> Optional[float]:
    """Sample standard deviation (n-1)."""
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _percentile(xs: List[float], p: float) -> Optional[float]:
    """Percentile dengan interpolasi linear (metode sama dengan numpy default)."""
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _daily_returns(prices: List[float]) -> List[float]:
    """Simple return harian: (P_t / P_t-1) - 1. Butuh minimal 2 harga."""
    out = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        if prev > 0:
            out.append(prices[i] / prev - 1.0)
    return out


def _align(series_a: List[Tuple[str, float]],
           series_b: List[Tuple[str, float]]) -> Tuple[List[float], List[float]]:
    """Samakan tanggal yang ada di kedua seri -> (returns_a, returns_b)."""
    da = dict(series_a)
    db = dict(series_b)
    common = sorted(set(da) & set(db))
    if len(common) < 2:
        return [], []
    pa = [da[d] for d in common]
    pb = [db[d] for d in common]
    return _daily_returns(pa), _daily_returns(pb)


# ─────────────────────────────────────────────────────────────────
# Drawdown analytics
# ─────────────────────────────────────────────────────────────────
def _drawdown_stats(prices: List[float], dates: List[str]) -> Dict[str, Any]:
    if len(prices) < 2:
        return {"max_drawdown_pct": None, "max_dd_start": None, "max_dd_trough": None,
                "max_dd_recovery": None, "max_dd_duration_days": None,
                "current_dd_pct": None, "ulcer_index": None, "longest_dd_days": None}

    peak = prices[0]
    peak_idx = 0
    max_dd = 0.0
    dd_start_idx = 0
    dd_trough_idx = 0

    # untuk recovery & longest drawdown
    in_dd = False
    dd_begin_idx = 0
    longest = 0
    longest_begin = 0
    dd_squares: List[float] = []
    recovery_date: Optional[str] = None

    for i, p in enumerate(prices):
        if p > peak:
            peak = p
            peak_idx = i
            if in_dd:
                dur = i - dd_begin_idx
                if dur > longest:
                    longest = dur
                    longest_begin = dd_begin_idx
                in_dd = False
        else:
            if not in_dd:
                in_dd = True
                dd_begin_idx = peak_idx
            dd = (p / peak - 1.0) * 100.0
            dd_squares.append(dd)
            if dd < max_dd:
                max_dd = dd
                dd_start_idx = peak_idx
                dd_trough_idx = i
                recovery_date = None

    # cari tanggal recovery setelah trough
    rec_date = None
    if max_dd < 0:
        peak_price = prices[dd_start_idx]
        for j in range(dd_trough_idx + 1, len(prices)):
            if prices[j] >= peak_price:
                rec_date = dates[j]
                break

    # hitung durasi drawdown terpanjang (hari kalender)
    longest_days = None
    if longest > 0:
        try:
            d0 = date.fromisoformat(dates[longest_begin])
            d1 = date.fromisoformat(dates[min(longest_begin + longest, len(dates) - 1)])
            longest_days = (d1 - d0).days
        except Exception:
            longest_days = longest

    max_dd_days = None
    if max_dd < 0:
        try:
            d0 = date.fromisoformat(dates[dd_start_idx])
            d1 = date.fromisoformat(dates[dd_trough_idx])
            max_dd_days = (d1 - d0).days
        except Exception:
            pass

    running_peak = prices[0]
    for p in prices:
        running_peak = max(running_peak, p)
    current_dd = (prices[-1] / running_peak - 1.0) * 100.0 if running_peak > 0 else None

    ulcer = math.sqrt(sum(d * d for d in dd_squares) / len(dd_squares)) if dd_squares else None

    return {
        "max_drawdown_pct": round(max_dd, 2) if max_dd < 0 else 0.0,
        "max_dd_start": dates[dd_start_idx] if max_dd < 0 else None,
        "max_dd_trough": dates[dd_trough_idx] if max_dd < 0 else None,
        "max_dd_recovery": rec_date,
        "max_dd_duration_days": max_dd_days,
        "current_dd_pct": round(current_dd, 2) if current_dd is not None else None,
        "ulcer_index": round(ulcer, 2) if ulcer is not None else None,
        "longest_dd_days": longest_days,
    }


# ─────────────────────────────────────────────────────────────────
# Metrik utama
# ─────────────────────────────────────────────────────────────────
def compute_performance(session: Session, ticker: str,
                        benchmark: str = "IHSG",
                        risk_free_pct: float = 6.0,
                        start: Optional[str] = None,
                        end: Optional[str] = None) -> Dict[str, Any]:
    """
    Hitung seluruh metrik performa & risiko. Mengembalikan dict siap-JSON.

    risk_free_pct : default 6.0% (rata-rata yield SUN 10Y Indonesia; bisa diubah).
    """
    tk = ticker.upper().strip()
    prices_rows = load_prices(session, tk, start, end)

    result: Dict[str, Any] = {
        "ticker": tk,
        "benchmark": benchmark.upper(),
        "risk_free_pct": risk_free_pct,
        "observations": len(prices_rows),
        "period_start": prices_rows[0][0] if prices_rows else None,
        "period_end": prices_rows[-1][0] if prices_rows else None,
        "years": None,
        "available": False,
        "reason": None,
        "provenance": "MARKET (OHLCV harian dari DB)",
    }

    if len(prices_rows) < MIN_OBS:
        result["reason"] = (
            f"Data harga tidak cukup ({len(prices_rows)} baris, minimum {MIN_OBS}). "
            "Emiten mungkin tersuspensi/delisting — lihat /api/trading-status."
        )
        return result

    dates = [r[0] for r in prices_rows]
    prices = [r[1] for r in prices_rows]
    rets = _daily_returns(prices)

    if len(rets) < 2:
        result["reason"] = "Return harian tidak dapat dihitung"
        return result

    # ── Periode & return total ────────────────────────────────────
    try:
        d0 = date.fromisoformat(dates[0])
        d1 = date.fromisoformat(dates[-1])
        years = (d1 - d0).days / 365.25
    except Exception:
        years = len(prices) / TRADING_DAYS
    result["years"] = round(years, 2)

    total_return = (prices[-1] / prices[0] - 1.0)
    cagr = ((prices[-1] / prices[0]) ** (1.0 / years) - 1.0) if years > 0 and prices[0] > 0 else None

    ann_ret = _mean(rets)
    ann_ret = (ann_ret * TRADING_DAYS) if ann_ret is not None else None  # aritmetik annualized

    vol_daily = _stdev(rets)
    vol_ann = (vol_daily * math.sqrt(TRADING_DAYS)) if vol_daily is not None else None

    rf_daily = (risk_free_pct / 100.0) / TRADING_DAYS

    # ── Sharpe ────────────────────────────────────────────────────
    sharpe = None
    if ann_ret is not None and vol_ann and vol_ann > 0:
        sharpe = (ann_ret - risk_free_pct / 100.0) / vol_ann

    # ── Sortino (downside deviation terhadap MAR = rf) ────────────
    downside = [r - rf_daily for r in rets if r < rf_daily]
    sortino = None
    downside_dev_ann = None
    if downside:
        dd_daily = math.sqrt(sum(d * d for d in downside) / len(downside))
        downside_dev_ann = dd_daily * math.sqrt(TRADING_DAYS)
        if downside_dev_ann > 0 and ann_ret is not None:
            sortino = (ann_ret - risk_free_pct / 100.0) / downside_dev_ann

    # ── Drawdown ──────────────────────────────────────────────────
    dd = _drawdown_stats(prices, dates)

    calmar = None
    if cagr is not None and dd["max_drawdown_pct"] not in (None, 0):
        calmar = cagr / abs(dd["max_drawdown_pct"] / 100.0)

    # ── Benchmark-relative ────────────────────────────────────────
    bench_rows = load_prices(session, benchmark, start, end)
    beta = alpha = treynor = info_ratio = correlation = r_squared = None
    tracking_error = excess_return_ann = bench_cagr = None

    if len(bench_rows) >= MIN_OBS:
        ra, rb = _align(prices_rows, bench_rows)
        if len(ra) >= MIN_OBS:
            mr, mb = _mean(ra), _mean(rb)
            if mr is not None and mb is not None:
                var_b = sum((x - mb) ** 2 for x in rb) / (len(rb) - 1) if len(rb) > 1 else 0
                cov = sum((ra[i] - mr) * (rb[i] - mb) for i in range(len(ra))) / (len(ra) - 1)
                if var_b > 0:
                    beta = cov / var_b
                sda, sdb = _stdev(ra), _stdev(rb)
                if sda and sdb and sdb > 0:
                    correlation = cov / (sda * sdb)
                    r_squared = correlation ** 2

            ann_a = mr * TRADING_DAYS if mr is not None else None
            ann_b = mb * TRADING_DAYS if mb is not None else None
            if ann_a is not None and ann_b is not None:
                excess_return_ann = ann_a - ann_b
                diffs = [ra[i] - rb[i] for i in range(len(ra))]
                te_daily = _stdev(diffs)
                if te_daily and te_daily > 0:
                    tracking_error = te_daily * math.sqrt(TRADING_DAYS)
                    if tracking_error > 0:
                        info_ratio = excess_return_ann / tracking_error
            if beta is not None and ann_a is not None:
                # Alpha & Treynor WAJIB pakai ann_a dari seri ter-align (tanggal sama
                # dengan benchmark), bukan dari seri penuh — supaya beta dan return
                # diukur pada periode yang identik.
                alpha = ann_a - (risk_free_pct / 100.0 + beta * (ann_b - risk_free_pct / 100.0))
                if beta != 0:
                    treynor = (ann_a - risk_free_pct / 100.0) / beta

            # CAGR benchmark
            bp = [p for _, p in bench_rows]
            b_years = None
            try:
                b0 = date.fromisoformat(bench_rows[0][0])
                b1 = date.fromisoformat(bench_rows[-1][0])
                b_years = (b1 - b0).days / 365.25
            except Exception:
                b_years = len(bp) / TRADING_DAYS
            if b_years and b_years > 0 and bp[0] > 0:
                bench_cagr = (bp[-1] / bp[0]) ** (1.0 / b_years) - 1.0

    # ── Distribusi & tail risk ────────────────────────────────────
    var95 = _percentile(rets, 0.05)
    var99 = _percentile(rets, 0.01)
    cvar95 = _mean([r for r in rets if var95 is not None and r <= var95]) if var95 is not None else None
    worst = min(rets) if rets else None
    best = max(rets) if rets else None

    # skewness & kurtosis (excess)
    skew = kurt = None
    m = _mean(rets)
    sd = _stdev(rets)
    if m is not None and sd and sd > 0 and len(rets) > 3:
        n = len(rets)
        skew = (n / ((n - 1) * (n - 2))) * sum(((r - m) / sd) ** 3 for r in rets)
        kurt = (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) * sum(((r - m) / sd) ** 4 for r in rets) \
               - (3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))

    # hit rate
    hit_rate = (sum(1 for r in rets if r > 0) / len(rets) * 100.0) if rets else None

    # monthly return series (untuk bar chart)
    monthly: List[Dict[str, Any]] = []
    cur_ym, first_p, last_p = None, None, None
    for d, p in prices_rows:
        ym = d[:7]
        if ym != cur_ym:
            if cur_ym is not None and first_p and last_p is not None and first_p > 0:
                monthly.append({"month": cur_ym,
                                "return_pct": round((last_p / first_p - 1.0) * 100.0, 2)})
            cur_ym, first_p, last_p = ym, p, p
        else:
            last_p = p
    if cur_ym and first_p and last_p is not None and first_p > 0:
        monthly.append({"month": cur_ym,
                        "return_pct": round((last_p / first_p - 1.0) * 100.0, 2)})

    pos_months = sum(1 for x in monthly if x["return_pct"] > 0)
    month_hit = (pos_months / len(monthly) * 100.0) if monthly else None

    # equity curve (downsampled ke maksimal 400 titik untuk chart)
    step = max(1, len(prices) // 400)
    equity_curve = [
        {"date": dates[i], "growth": round(prices[i] / prices[0], 4)}
        for i in range(0, len(prices), step)
    ]
    if equity_curve and equity_curve[-1]["date"] != dates[-1]:
        equity_curve.append({"date": dates[-1], "growth": round(prices[-1] / prices[0], 4)})

    # rolling drawdown curve
    dd_curve = []
    rp = prices[0]
    for i, p in enumerate(prices):
        rp = max(rp, p)
        if i % step == 0:
            dd_curve.append({"date": dates[i], "dd_pct": round((p / rp - 1.0) * 100.0, 2)})

    result.update({
        "available": True,
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2) if cagr is not None else None,
        "annual_return_pct": round(ann_ret * 100.0, 2) if ann_ret is not None else None,
        "annual_volatility_pct": round(vol_ann * 100.0, 2) if vol_ann is not None else None,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "downside_deviation_pct": round(downside_dev_ann * 100.0, 2) if downside_dev_ann else None,
        "calmar": round(calmar, 2) if calmar is not None else None,
        "beta": round(beta, 2) if beta is not None else None,
        "alpha_pct": round(alpha * 100.0, 2) if alpha is not None else None,
        "treynor": round(treynor, 2) if treynor is not None else None,
        "information_ratio": round(info_ratio, 2) if info_ratio is not None else None,
        "tracking_error_pct": round(tracking_error * 100.0, 2) if tracking_error else None,
        "excess_return_ann_pct": round(excess_return_ann * 100.0, 2) if excess_return_ann is not None else None,
        "benchmark_cagr_pct": round(bench_cagr * 100.0, 2) if bench_cagr is not None else None,
        "correlation": round(correlation, 3) if correlation is not None else None,
        "r_squared": round(r_squared, 3) if r_squared is not None else None,
        "var_95_daily_pct": round(var95 * 100.0, 2) if var95 is not None else None,
        "var_99_daily_pct": round(var99 * 100.0, 2) if var99 is not None else None,
        "cvar_95_daily_pct": round(cvar95 * 100.0, 2) if cvar95 is not None else None,
        "worst_day_pct": round(worst * 100.0, 2) if worst is not None else None,
        "best_day_pct": round(best * 100.0, 2) if best is not None else None,
        "skewness": round(skew, 3) if skew is not None else None,
        "kurtosis_excess": round(kurt, 3) if kurt is not None else None,
        "hit_rate_pct": round(hit_rate, 1) if hit_rate is not None else None,
        "monthly_hit_rate_pct": round(month_hit, 1) if month_hit is not None else None,
        "positive_months": pos_months,
        "total_months": len(monthly),
        "monthly_returns": monthly,
        "equity_curve": equity_curve,
        "drawdown_curve": dd_curve,
        **dd,
    })
    # Penjelasan bahasa awam — dibangun dari angka yang SUDAH dihitung,
    # tidak menambah metrik baru atau mengarang nilai.
    try:
        from app.services.performance_insight import build_interpretation
        result["interpretation"] = build_interpretation(result)
    except Exception as exc:      # jangan sampai penjelasan merusak endpoint
        result["interpretation"] = {
            "available": False,
            "reason": f"Penjelasan tidak dapat dibangun: {exc}",
        }
    return result


def compute_rolling_stats(session: Session, ticker: str,
                          window_days: int = 252,
                          risk_free_pct: float = 6.0,
                          benchmark: str = "IHSG") -> Dict[str, Any]:
    """
    Rolling Sharpe & Sortino sepanjang periode (window default 252 hari = 1 tahun).

    Kenapa penting: Sharpe agregat menyembunyikan inkonsistensi. Emiten bisa punya
    Sharpe 0.5 secara total tapi sebenarnya 3 tahun bagus lalu 2 tahun hancur.
    Rolling window memperlihatkan stabilitas, bukan cuma rata-rata.
    """
    rows = load_prices(session, ticker)
    if len(rows) < window_days + 30:
        return {
            "available": False,
            "reason": f"Butuh minimal {window_days + 30} observasi, tersedia {len(rows)}",
        }

    dates = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    rets = _daily_returns(prices)
    if len(rets) < window_days:
        return {"available": False, "reason": "Return harian tidak cukup"}

    rf_daily = (risk_free_pct / 100.0) / TRADING_DAYS
    ann_rf = risk_free_pct / 100.0

    out: List[Dict[str, Any]] = []
    # rets[i] sesuai dengan dates[i+1]
    for end in range(window_days, len(rets) + 1):
        win = rets[end - window_days:end]
        m = _mean(win)
        sd = _stdev(win)
        if m is None or sd is None or sd == 0:
            continue
        ann_r = m * TRADING_DAYS
        ann_vol = sd * math.sqrt(TRADING_DAYS)
        sharpe = (ann_r - ann_rf) / ann_vol if ann_vol > 0 else None

        downside = [r - rf_daily for r in win if r < rf_daily]
        sortino = None
        if downside:
            dd = math.sqrt(sum(d * d for d in downside) / len(downside)) * math.sqrt(TRADING_DAYS)
            if dd > 0:
                sortino = (ann_r - ann_rf) / dd

        # max drawdown dalam window
        w_prices = prices[end - window_days:end + 1]
        peak = w_prices[0]
        mdd = 0.0
        for p in w_prices:
            peak = max(peak, p)
            mdd = min(mdd, p / peak - 1.0)

        out.append({
            "date": dates[min(end, len(dates) - 1)],
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "sortino": round(sortino, 2) if sortino is not None else None,
            "volatility_pct": round(ann_vol * 100.0, 2),
            "return_pct": round(ann_r * 100.0, 2),
            "max_dd_pct": round(mdd * 100.0, 2),
        })

    if not out:
        return {"available": False, "reason": "Tidak ada window valid"}

    sharpes = [o["sharpe"] for o in out if o["sharpe"] is not None]
    pos = sum(1 for s in sharpes if s > 0)

    return {
        "available": True,
        "window_days": window_days,
        "observations": len(out),
        "series": out,
        "sharpe_min": round(min(sharpes), 2) if sharpes else None,
        "sharpe_max": round(max(sharpes), 2) if sharpes else None,
        "sharpe_median": round(_percentile(sharpes, 0.5), 2) if sharpes else None,
        "sharpe_current": out[-1]["sharpe"],
        "pct_windows_positive": round(pos / len(sharpes) * 100.0, 1) if sharpes else None,
        "consistency": (
            "SANGAT KONSISTEN" if sharpes and pos / len(sharpes) >= 0.90 else
            "KONSISTEN" if sharpes and pos / len(sharpes) >= 0.70 else
            "TIDAK KONSISTEN" if sharpes else None
        ),
        "provenance": f"MARKET (rolling {window_days} hari dari OHLCV harian)",
    }


def compute_performance_multi(session: Session, tickers: List[str],
                              benchmark: str = "IHSG",
                              risk_free_pct: float = 6.0,
                              start: Optional[str] = None,
                              end: Optional[str] = None) -> Dict[str, Any]:
    """Ranking beberapa emiten sekaligus, diurutkan berdasarkan Sharpe."""
    rows = [compute_performance(session, t, benchmark, risk_free_pct, start, end)
            for t in tickers]
    ok = [r for r in rows if r.get("available")]
    ok.sort(key=lambda r: (r.get("sharpe") is None, -(r.get("sharpe") or 0)))
    return {
        "benchmark": benchmark.upper(),
        "risk_free_pct": risk_free_pct,
        "count": len(rows),
        "available_count": len(ok),
        "results": rows,
        "ranking": [r["ticker"] for r in ok],
    }
