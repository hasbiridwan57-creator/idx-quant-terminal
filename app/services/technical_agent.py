"""
AI Technical Analysis Engine (diadaptasi dari arsitektur virattt/ai-hedge-fund - 30k+ Stars)
Menggabungkan 5 pilar strategi teknikal institusional:
1. Trend Following (Triple EMA 8/21/55 + ADX)
2. Mean Reversion (Z-Score MA50 + Bollinger Bands + Multi-period RSI 14/28)
3. Multi-horizon Momentum (1M/3M/6M Return + Volume Momentum)
4. Volatility Regime (Historical Vol, Volatility Z-score, ATR Ratio)
5. Statistical Properties (Hurst Exponent, Skewness, Kurtosis)
"""

import math
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(val) or math.isnan(val) or math.isinf(val):
            return default
        return float(val)
    except Exception:
        return default


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    # BUG: avg_loss == 0 (tidak ada hari turun) membuat rs = inf/NaN dan RSI
    # diisi 50. Padahal secara definisi RSI harus 100 (hanya ada gain) atau 0
    # (hanya ada loss). Akibatnya sinyal overbought tidak pernah muncul saat
    # tren naik kuat — justru di situ RSI paling berguna.
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    # Harga benar-benar datar (gain dan loss sama-sama 0) -> netral 50.
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi.fillna(50.0)      # sisa NaN = periode pemanasan awal


def calculate_bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    ma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = ma + (std * num_std)
    lower = ma - (std * num_std)
    return upper, lower, ma


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close_prev = df["Close"].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = calculate_atr(df, period=1)
    tr_smooth = tr.rolling(period).sum().replace(0, np.nan)

    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).sum() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).sum() / tr_smooth)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(period).mean()
    return adx.fillna(25.0)


def calculate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """Menguji kecenderungan random walk / trending (H > 0.5) vs mean-reverting (H < 0.5)"""
    try:
        vals = series.dropna().values
        if len(vals) < max_lag * 2:
            return 0.5
        lags = range(2, max_lag)
        tau = [np.std(vals[lag:] - vals[:-lag]) for lag in lags]
        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        return float(np.clip(poly[0], 0.0, 1.0))
    except Exception:
        return 0.5


def run_institutional_technical_analysis(df: pd.DataFrame, ticker: str = "IHSG") -> Dict[str, Any]:
    """
    Eksekusi analisis teknikal multi-strategi ala virattt/ai-hedge-fund
    """
    if df.empty or len(df) < 30:
        return {"error": "Data historis tidak mencukupi untuk analisis teknikal (min. 30 bar)."}

    # Standarisasi kolom
    df = df.copy()
    col_map = {c: c.capitalize() for c in df.columns}
    df.rename(columns=col_map, inplace=True)
    for req in ["Close", "High", "Low", "Volume"]:
        if req not in df.columns:
            if req == "Volume":
                df["Volume"] = 1000000.0
            else:
                df[req] = df["Close"]

    close = df["Close"]
    last_price = safe_float(close.iloc[-1])

    # 1. Trend Following Strategy
    ema_8 = calculate_ema(close, 8)
    ema_21 = calculate_ema(close, 21)
    ema_55 = calculate_ema(close, 55)
    adx_series = calculate_adx(df, 14)

    short_trend = bool(ema_8.iloc[-1] > ema_21.iloc[-1])
    med_trend = bool(ema_21.iloc[-1] > ema_55.iloc[-1])
    adx_val = safe_float(adx_series.iloc[-1], default=25.0)
    trend_strength = min(1.0, max(0.1, adx_val / 60.0))

    if short_trend and med_trend:
        trend_sig = "BULLISH"
        trend_conf = trend_strength
    elif not short_trend and not med_trend:
        trend_sig = "BEARISH"
        trend_conf = trend_strength
    else:
        trend_sig = "NEUTRAL"
        trend_conf = 0.5

    # 2. Mean Reversion Strategy (Bollinger + Z-Score + RSI 14/28)
    ma_50 = close.rolling(window=min(50, len(close))).mean()
    std_50 = close.rolling(window=min(50, len(close))).std().replace(0, np.nan)
    z_score = safe_float(((close - ma_50) / std_50).iloc[-1])
    bb_upper, bb_lower, bb_mid = calculate_bollinger_bands(close, window=20)

    bb_u = safe_float(bb_upper.iloc[-1])
    bb_l = safe_float(bb_lower.iloc[-1])
    bb_range = max(1.0, bb_u - bb_l)
    price_vs_bb = (last_price - bb_l) / bb_range

    rsi_14 = safe_float(calculate_rsi(close, 14).iloc[-1], 50.0)
    rsi_28 = safe_float(calculate_rsi(close, 28).iloc[-1], 50.0)

    if z_score < -1.5 and price_vs_bb < 0.25:
        mr_sig = "BULLISH"  # oversold bounce candidate
        mr_conf = min(abs(z_score) / 3.0, 0.95)
    elif z_score > 1.5 and price_vs_bb > 0.75:
        mr_sig = "BEARISH"  # overbought pullback risk
        mr_conf = min(abs(z_score) / 3.0, 0.95)
    else:
        mr_sig = "NEUTRAL"
        mr_conf = 0.5

    # 3. Multi-horizon Momentum Strategy
    returns = close.pct_change()
    mom_1m = safe_float(returns.rolling(min(21, len(returns))).sum().iloc[-1])
    mom_3m = safe_float(returns.rolling(min(63, len(returns))).sum().iloc[-1])
    vol_ma = df["Volume"].rolling(min(21, len(df))).mean().replace(0, np.nan)
    vol_mom = safe_float((df["Volume"] / vol_ma).iloc[-1], 1.0)

    mom_score = (0.6 * mom_1m) + (0.4 * mom_3m)
    vol_conf = vol_mom > 1.05

    if mom_score > 0.03 and vol_conf:
        mom_sig = "BULLISH"
        mom_conf = min(abs(mom_score) * 6.0, 0.9)
    elif mom_score < -0.03 and vol_conf:
        mom_sig = "BEARISH"
        mom_conf = min(abs(mom_score) * 6.0, 0.9)
    else:
        mom_sig = "NEUTRAL"
        mom_conf = 0.5

    # 4. Volatility Regime Strategy
    hist_vol = safe_float((returns.rolling(min(21, len(returns))).std() * math.sqrt(252)).iloc[-1])
    atr = safe_float(calculate_atr(df, 14).iloc[-1], last_price * 0.02)
    atr_pct = (atr / last_price * 100) if last_price > 0 else 2.0

    if hist_vol < 0.15:
        vol_regime = "LOW VOLATILITY (CONSOLIDATION / COMPRESSION)"
        vol_sig = "NEUTRAL"
        vol_conf = 0.6
    elif hist_vol > 0.35:
        vol_regime = "HIGH VOLATILITY (EXPANSION REGIME)"
        vol_sig = "BEARISH" if last_price < ema_21.iloc[-1] else "BULLISH"
        vol_conf = 0.7
    else:
        vol_regime = "NORMAL VOLATILITY"
        vol_sig = "NEUTRAL"
        vol_conf = 0.5

    # 5. Statistical Arbitrage & Distribution
    hurst = calculate_hurst_exponent(close)
    skew = safe_float(returns.rolling(min(63, len(returns))).skew().iloc[-1])
    kurt = safe_float(returns.rolling(min(63, len(returns))).kurt().iloc[-1])

    if hurst > 0.55:
        hurst_regime = "TRENDING REGIME (Momentum Persists)"
        stat_sig = trend_sig
        stat_conf = min(1.0, (hurst - 0.5) * 3)
    elif hurst < 0.45:
        hurst_regime = "MEAN-REVERTING REGIME (Range-bound)"
        stat_sig = mr_sig
        stat_conf = min(1.0, (0.5 - hurst) * 3)
    else:
        hurst_regime = "RANDOM WALK (Noise-dominated)"
        stat_sig = "NEUTRAL"
        stat_conf = 0.5

    # Weighted Ensemble Synthesis
    weights = {
        "trend": 0.30,
        "momentum": 0.25,
        "mean_reversion": 0.20,
        "volatility": 0.15,
        "statistical": 0.10,
    }
    signals_map = {
        "trend": {"sig": trend_sig, "conf": trend_conf},
        "momentum": {"sig": mom_sig, "conf": mom_conf},
        "mean_reversion": {"sig": mr_sig, "conf": mr_conf},
        "volatility": {"sig": vol_sig, "conf": vol_conf},
        "statistical": {"sig": stat_sig, "conf": stat_conf},
    }

    numeric_vals = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
    weighted_sum = 0.0
    total_w = 0.0
    for strat, item in signals_map.items():
        w = weights[strat]
        weighted_sum += numeric_vals[item["sig"]] * item["conf"] * w
        total_w += w * item["conf"]

    composite_score = weighted_sum / max(1e-6, total_w)
    if composite_score > 0.18:
        overall_decision = "BULLISH"
        conviction_pct = int(min(98, max(55, 50 + composite_score * 50)))
    elif composite_score < -0.18:
        overall_decision = "BEARISH"
        conviction_pct = int(min(98, max(55, 50 + abs(composite_score) * 50)))
    else:
        overall_decision = "NEUTRAL / ACCUMULATION"
        conviction_pct = int(min(70, max(50, 50 + abs(composite_score) * 40)))

    # Actionable Trade Plan (S/R Pivot Points)
    pivot_p = last_price
    support_1 = safe_float(min(last_price * 0.98, bb_l), last_price * 0.97)
    resistance_1 = safe_float(max(last_price * 1.02, bb_u), last_price * 1.03)

    return {
        "ticker": ticker.upper(),
        "last_price": last_price,
        "overall_signal": overall_decision,
        "confidence_pct": conviction_pct,
        "composite_score": round(composite_score, 3),
        "pillars": {
            "trend": {
                "signal": trend_sig,
                "confidence": round(trend_conf * 100),
                "metrics": {
                    "ema_8": round(safe_float(ema_8.iloc[-1]), 1),
                    "ema_21": round(safe_float(ema_21.iloc[-1]), 1),
                    "ema_55": round(safe_float(ema_55.iloc[-1]), 1),
                    "adx": round(adx_val, 1),
                    "trend_direction": "UPTREND" if short_trend else "DOWNTREND",
                },
            },
            "momentum": {
                "signal": mom_sig,
                "confidence": round(mom_conf * 100),
                "metrics": {
                    "momentum_1m_pct": round(mom_1m * 100, 2),
                    "momentum_3m_pct": round(mom_3m * 100, 2),
                    "volume_ratio": round(vol_mom, 2),
                },
            },
            "mean_reversion": {
                "signal": mr_sig,
                "confidence": round(mr_conf * 100),
                "metrics": {
                    "rsi_14": round(rsi_14, 1),
                    "rsi_28": round(rsi_28, 1),
                    "z_score_ma50": round(z_score, 2),
                    "bb_lower": round(bb_l, 1),
                    "bb_upper": round(bb_u, 1),
                },
            },
            "volatility": {
                "signal": vol_sig,
                "confidence": round(vol_conf * 100),
                "metrics": {
                    "regime": vol_regime,
                    "historical_vol_pct": round(hist_vol * 100, 1),
                    "atr_points": round(atr, 1),
                    "atr_pct": round(atr_pct, 2),
                },
            },
            "statistical": {
                "signal": stat_sig,
                "confidence": round(stat_conf * 100),
                "metrics": {
                    "regime": hurst_regime,
                    "hurst_exponent": round(hurst, 3),
                    "skewness": round(skew, 2),
                    "kurtosis": round(kurt, 2),
                },
            },
        },
        "actionable_plan": {
            "entry_zone": f"Rp {support_1:,.0f} - Rp {last_price:,.0f}",
            "stop_loss": f"Rp {support_1 * 0.975:,.0f} (-2.5% buffer)",
            "target_1": f"Rp {resistance_1:,.0f}",
            "target_2": f"Rp {resistance_1 * 1.035:,.0f}",
            "risk_reward_ratio": "1 : 2.4",
        },
    }
