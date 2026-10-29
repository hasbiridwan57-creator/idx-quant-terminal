"""
app/services/market_data.py
Modul penyedia data pasar riil dari yfinance dan database lokal.
Tidak ada data sintetis / gelombang sinus.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict, Any
import math
import yfinance as yf
from sqlmodel import Session, select
from app.db.models import QuoteLatest, QuoteHistoryDaily

QUOTE_TTL_S = 300  # 5 menit cache quote
MIN_BARS = 60      # Minimal baris harga untuk kalkulasi risiko yang valid

class InsufficientData(Exception):
    pass

def yf_symbol(ticker: str) -> str:
    clean = ticker.upper().replace("IDX:", "").replace("^", "").strip()
    return "^JKSE" if clean in ("IHSG", "COMPOSITE") else f"{clean}.JK"

def get_quote(session: Session, ticker: str, force: bool = False) -> Tuple[Optional[QuoteLatest], str]:
    """
    Mengambil data quote harga terakhir.
    Returns: (QuoteLatest, status) dengan status: 'LIVE' | 'CACHED' | 'STALE' | 'UNAVAILABLE'
    """
    clean_t = ticker.upper().replace("IDX:", "").replace("^", "").strip()
    ql = session.get(QuoteLatest, clean_t)
    
    if ql and not force and ql.fetched_at:
        ts = ql.fetched_at if ql.fetched_at.tzinfo else ql.fetched_at.replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - ts).total_seconds()
        if diff < QUOTE_TTL_S:
            return ql, "CACHED"
            
    try:
        sym = yf_symbol(clean_t)
        t_obj = yf.Ticker(sym)
        fi = t_obj.fast_info
        
        price = float(fi.last_price) if getattr(fi, "last_price", None) else None
        prev = float(fi.previous_close) if getattr(fi, "previous_close", None) else None
        
        if price is None or price <= 0:
            # Fallback 1 day history jika fast_info kosong
            hist = t_obj.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
                
        if price is not None and price > 0:
            change = (price - prev) if prev else 0.0
            change_pct = ((price / prev) - 1.0) * 100.0 if prev else 0.0
            mcap = getattr(fi, "market_cap", None)
            
            row = ql or QuoteLatest(ticker=clean_t, price=price, change=change, change_pct=change_pct)
            row.price = price
            row.previous_close = prev
            row.change = change
            row.change_pct = change_pct
            row.market_cap = mcap
            row.source = "yfinance"
            row.fetched_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row, "LIVE"
            
        return (ql, "STALE") if ql else (None, "UNAVAILABLE")
    except Exception:
        return (ql, "STALE") if ql else (None, "UNAVAILABLE")

def ensure_history(session: Session, ticker: str, years: int = 3) -> List[QuoteHistoryDaily]:
    """
    Memastikan data historis harga saham tersedia di database lokal.
    Jika kadaluarsa / kosong, fetch dari yfinance.
    """
    clean_t = ticker.upper().replace("IDX:", "").replace("^", "").strip()
    q = select(QuoteHistoryDaily).where(QuoteHistoryDaily.ticker == clean_t).order_by(QuoteHistoryDaily.date.asc())
    rows = session.exec(q).all()
    
    needs_fetch = False
    if not rows or len(rows) < MIN_BARS:
        needs_fetch = True
    else:
        last_date_str = rows[-1].date
        try:
            last_date = datetime.fromisoformat(last_date_str).date()
            if (datetime.now().date() - last_date).days > 3:
                needs_fetch = True
        except Exception:
            needs_fetch = True
            
    if needs_fetch:
        try:
            sym = yf_symbol(clean_t)
            df = yf.Ticker(sym).history(period=f"{years}y", auto_adjust=True)
            if not df.empty and len(df) >= 10:
                have_dates = {r.date for r in rows}
                new_items = []
                for ts, r in df.iterrows():
                    d_str = ts.strftime("%Y-%m-%d")
                    c_val = float(r["Close"])
                    if d_str in have_dates or math.isnan(c_val) or c_val <= 0:
                        continue
                    item = QuoteHistoryDaily(
                        ticker=clean_t,
                        date=d_str,
                        open=float(r["Open"]) if not math.isnan(r["Open"]) else c_val,
                        high=float(r["High"]) if not math.isnan(r["High"]) else c_val,
                        low=float(r["Low"]) if not math.isnan(r["Low"]) else c_val,
                        close=c_val,
                        volume=float(r["Volume"]) if not math.isnan(r["Volume"]) else 0.0,
                    )
                    session.add(item)
                    have_dates.add(d_str)
                session.commit()
                rows = session.exec(q).all()
        except Exception as e:
            pass
            
    return list(rows)

def aligned_closes(stock_rows: List[QuoteHistoryDaily], bench_rows: List[QuoteHistoryDaily]) -> Tuple[List[float], List[float], List[str]]:
    """
    Menyelaraskan deret harga saham dan benchmark BERDASARKAN TANGGAL KALENDER NYATA.
    Mencegah pergeseran indeks yang membuat korelasi dan beta terdistorsi.
    """
    s_map = {r.date: float(r.close) for r in stock_rows if r.close and r.close > 0}
    b_map = {r.date: float(r.close) for r in bench_rows if r.close and r.close > 0}
    
    common_dates = sorted(set(s_map.keys()) & set(b_map.keys()))
    s_closes = [s_map[d] for d in common_dates]
    b_closes = [b_map[d] for d in common_dates]
    return s_closes, b_closes, common_dates

def calculate_realized_volatility(closes: List[float], annualize_factor: float = 252.0) -> Optional[float]:
    """Menghitung volatilitas terealisasi tahunan (annualized realized vol) dari log-returns."""
    if len(closes) < 10:
        return None
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i-1]))
    if len(log_returns) < 5:
        return None
    mean_ret = sum(log_returns) / len(log_returns)
    variance = sum((r - mean_ret) ** 2 for r in log_returns) / (len(log_returns) - 1)
    return math.sqrt(variance * annualize_factor)
