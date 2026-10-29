"""Data providers: Yahoo Finance (via yfinance library) + fallback idx CLI."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Dynamic resolution of idx CLI binary (no hardcoded path) ─────────────
_IDX_PATH = os.getenv("IDX_CLI_PATH") or shutil.which("idx") or os.path.expanduser("~/.local/bin/idx")


def _idx(*args: str, timeout: int = 45) -> str:
    """Run `idx <args...>` fallback; raise on non-zero exit."""
    import subprocess
    cmd = [_IDX_PATH, *(a for a in args if a)]  # type: ignore[arg-type]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"idx CLI error {r.returncode}: {r.stderr.strip()}")
    return r.stdout.strip()


# ── helpers ────────────────────────────────────────────────────────────

def _now_wib() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone.utc).astimezone(
        timezone(datetime.now().astimezone().utcoffset())
    )


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f  # reject NaN
    except (TypeError, ValueError):
        return None


def _to_str(v: Any) -> str:
    return str(v) if v is not None else ""


# ── 1) QUOTE_BULK ─────────────────────────────────────────────────────

def fetch_quotes(symbols: List[str], max_per_request: int = 50) -> Dict[str, Dict[str, Any]]:
    """
    Ambil quote untuk daftar simbol via yfinance (primary) atau idx CLI (fallback).

    Return: {symbol: {"price", "change", "change_pct", "market_cap", "pe_trailing",
                     "pb", "dividend_yield_pct", "week52_high", "week52_low",
                     "market_state", "as_of", "source"}}
    """
    out: Dict[str, Dict[str, Any]] = {}

    # ── primary: yfinance ──
    try:
        # yfinance Tickers() bisa terima banyak simbol sekaligus
        # Gunakan format .JK untuk IDX (Indonesia)
        yf_symbols = [s if s.endswith(".JK") else f"{s}.JK" for s in symbols]
        tickers = yf.Tickers(" ".join(yf_symbols))

        for sym in symbols:
            ysym = sym if sym.endswith(".JK") else f"{sym}.JK"
            t = tickers.tickers.get(ysym)
            if t is None:
                continue
            try:
                info = t.info
            except Exception:
                continue
            if not info or len(info) < 3:
                continue

            price = _safe_float(info.get("currentPrice")) or _safe_float(
                info.get("regularMarketPrice")
            )
            change = _safe_float(info.get("regularMarketChange"))
            change_pct = _safe_float(info.get("regularMarketChangePercent"))
            # Jika pct tidak ada, hitung dari price vs prev_close
            if change_pct is None and price and info.get("previousClose"):
                prev = _safe_float(info.get("previousClose"))
                if prev and prev != 0:
                    change = round(price - prev, 2)
                    change_pct = round((price - prev) / prev * 100, 4)

            out[sym] = {
                "price": price or 0.0,
                "change": change or 0.0,
                "change_pct": change_pct or 0.0,
                "market_cap": _safe_float(info.get("marketCap")),
                "pe_trailing": _safe_float(info.get("trailingPE")),
                "pb": _safe_float(info.get("priceToBook")),
                "dividend_yield_pct": (
                    round(float(info["dividendYield"]) * 100, 2)
                    if info.get("dividendYield") is not None
                    else None
                ),
                "week52_high": _safe_float(info.get("52WeekHigh")),
                "week52_low": _safe_float(info.get("52WeekLow")),
                "market_state": _derive_market_state(),
                "as_of": _to_str(info.get("regularMarketTime")),
                "source": "yfinance",
            }
        time.sleep(0.15)  # rate-limit ramah

    except Exception as e:
        logger.warning(f"yfinance fetch_quotes gagal: {e}; fallback ke idx CLI")
        # ── fallback: idx CLI ──
        for sym in symbols:
            try:
                raw = _idx("-o", "json", "stocks", "quote", sym)
                data = json.loads(raw)["data"]
                for entry in data:
                    s = entry.get("symbol", "")
                    if s:
                        out[s] = _parse_quote(entry)
            except Exception:
                pass

    return out


def _derive_market_state() -> str:
    """Infer state bursa IDX dari jam WIB saat ini."""
    wib = _now_wib()
    if wib.weekday() >= 5:
        return "CLOSED EOD"
    minute = wib.hour * 60 + wib.minute
    if minute < 540:  # < 09:00
        return "PREOPEN"
    if minute <= 945:  # <= 15:45
        return "OPEN"
    return "CLOSED EOD"


def _parse_quote(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Parse quote dari respons idx CLI fallback."""
    return {
        "price": float(entry.get("price", 0) or 0),
        "change": float(entry.get("change", 0) or 0),
        "change_pct": float(entry.get("change_pct", 0) or 0),
        "market_cap": float(entry.get("market_cap", 0) or 0)
        if entry.get("market_cap") is not None
        else None,
        "pe_trailing": float(entry.get("pe_trailing", 0) or 0)
        if entry.get("pe_trailing") is not None
        else None,
        "pb": float(entry.get("price_to_book", 0) or 0)
        if entry.get("price_to_book") is not None
        else None,
        "dividend_yield_pct": float(entry.get("dividend_yield_pct", 0) or 0)
        if entry.get("dividend_yield_pct") is not None
        else None,
        "week52_high": float(entry.get("week52_high", 0) or 0),
        "week52_low": float(entry.get("week52_low", 0) or 0),
        "market_state": entry.get("market_state", "UNKNOWN"),
        "as_of": entry.get("market_time", ""),
        "source": entry.get("source", "idx-cli"),
    }


# ── 2) FUNDAMENTALS & FINANCIALS ──────────────────────────────────────

def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Ambil fundamental ringkas dari yfinance.info (fast lookup).

    Return dict terstruktur: {sector, industry, valuation, profitability, health, growth}
    """
    t = yf.Ticker(symbol if symbol.endswith(".JK") else f"{symbol}.JK")
    try:
        info = t.info
    except Exception as e:
        logger.warning(f"yfinance fundamentals {symbol} gagal: {e}")
        return {}

    basic = {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName", ""),
        "currency": info.get("currency", "IDR"),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "price": _safe_float(info.get("currentPrice")),
        "beta": _safe_float(info.get("beta")),
        "week52_high": _safe_float(info.get("52WeekHigh")),
        "week52_low": _safe_float(info.get("52WeekLow")),
    }

    val = info.get("valuation", {})
    basic["valuation"] = {
        "market_cap": _safe_float(info.get("marketCap")),
        "enterprise_value": _safe_float(info.get("enterpriseValue")),
        "pe_trailing": _safe_float(info.get("trailingPE")),
        "pe_forward": _safe_float(info.get("forwardPE")),
        "peg": _safe_float(info.get("pegRatio")),
        "price_to_book": _safe_float(info.get("priceToBook")),
        "price_to_sales": _safe_float(info.get("priceToSales")),
        "ev_to_ebitda": _safe_float(info.get("evToEbitda")),
        "ev_to_revenue": _safe_float(info.get("evToRevenue")),
    }

    # Profitability — operating/net margin dikonversi dari desimal ke %
    def pct(v: Any) -> Optional[float]:
        f = _safe_float(v)
        return round(f * 100, 2) if f is not None else None

    basic["profitability"] = {
        "roe_pct": None,  # dihitung dari financials
        "roa_pct": None,
        "gross_margin_pct": None,
        "operating_margin_pct": pct(info.get("OperatingMargins")),
        "net_margin_pct": pct(info.get("ProfitMargins")),
    }

    basic["health"] = {
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "current_ratio": None,
        "quick_ratio": None,
        "total_debt": _safe_float(info.get("totalDebt")),
        "total_cash": _safe_float(info.get("totalCash")),
    }

    basic["growth"] = {
        "revenue_growth_pct": pct(info.get("revenueGrowth")),
        "earnings_growth_pct": pct(info.get("earningsGrowth")),
        "revenue_cagr_5y_pct": None,
    }
    return basic


def fetch_financials(symbol: str, period: str = "annual") -> Dict[str, Any]:
    """
    Ambil laporan keuangan tahunan/kuartal dari yfinance.

    Return: {"period": str, "end_date": str, "revenue": float, "net_income": float,
             "total_assets": float, "total_equity": float, "total_debt": float,
             "interest_income": float, "interest_expense": float,
             "pretax_income": float, "tax_provision": float, "eps_diluted": float}

    Field ini langsung bisa di-map ke DuPont Engine (FinancialStatementInput).
    """
    ysym = symbol if symbol.endswith(".JK") else f"{symbol}.JK"
    t = yf.Ticker(ysym)

    try:
        fin = t.financials
        bs = t.balance_sheet
    except Exception as e:
        logger.warning(f"yfinance financials {symbol} gagal: {e}")
        return {}

    if fin.empty or bs.empty:
        return {}

    # Kolom = [2025-12-31, 2024-12-31, ...] terurut descending
    curr_col = fin.columns[0]
    curr_date = str(curr_col)[:10]

    def get_val(df, key: str) -> float:
        if key in df.index:
            v = df.loc[key, curr_col]
            if hasattr(v, "iloc"):
                v = v.iloc[0]
            import numpy as np

            f = float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0
            return f
        return 0.0

    # ── Income Statement ──
    rev = get_val(fin, "Total Revenue") or get_val(fin, "TotalRevenue")
    ni = (
        get_val(fin, "Net Income From Continuing Operation Net Minority Interest")
        or get_val(fin, "Net Income")
    )
    pretax = get_val(fin, "Pretax Income")
    interest = get_val(fin, "Interest Expense")
    tax = get_val(fin, "Tax Provision")
    eps = get_val(fin, "Diluted EPS") if "Diluted EPS" in fin.index else None

    # ── Balance Sheet ──
    total_assets = get_val(bs, "Total Assets")
    total_equity = get_val(bs, "Stockholders Equity") or get_val(bs, "Common Stock Equity")
    total_debt = get_val(bs, "Total Debt")

    return {
        "period": str(curr_col)[:4],
        "end_date": curr_date,
        "revenue": rev,
        "net_income": ni,
        "total_assets": total_assets,
        "total_equity": total_equity,
        "total_debt": total_debt,
        "interest_income": 0.0,  # yfinance tidak expose terpisah
        "interest_expense": interest,
        "pretax_income": pretax,
        "tax_provision": tax,
        "eps_diluted": eps,
    }


# ── 3) HISTORY_DAILY ───────────────────────────────────────────────────

def fetch_history(
    symbol: str,
    period: str = "5d",
    interval: str = "1d",
) -> List[Dict[str, Any]]:
    """
    Ambil riwayat harian untuk satu ticker via yfinance.

    Return: list of dict dengan fields: date, open, high, low, close, volume
    """
    ysym = symbol if symbol.endswith(".JK") else f"{symbol}.JK"
    t = yf.Ticker(ysym)
    try:
        hist = t.history(period=period, interval=interval, auto_adjust=True)
    except Exception:
        return []

    if hist.empty:
        return []

    out = []
    for _, row in hist.iterrows():
        date = row.name
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        out.append(
            {
                "date": date_str,
                "open": float(row.get("Open", 0) or 0),
                "high": float(row.get("High", 0) or 0),
                "low": float(row.get("Low", 0) or 0),
                "close": float(row.get("Close", 0) or 0),
                "volume": int(row.get("Volume", 0) or 0),
            }
        )
    return out


# ── 4) MARKET OVERVIEW & INDEX ─────────────────────────────────────────

def fetch_index_quote(symbol: str = "^JKSE") -> Dict[str, Any]:
    """
    Quote indeks (IHSG/^JKSE) via yfinance (primary) atau idx CLI (fallback).
    """
    try:
        t = yf.Ticker(symbol)
        info = t.info
        return {
            "symbol": symbol,
            "name": info.get("longName") or symbol,
            "price": _safe_float(info.get("regularMarketPrice")),
            "change": _safe_float(info.get("regularMarketChange")),
            "change_pct": _safe_float(info.get("regularMarketChangePercent")),
            "volume": int(info.get("volume")) if info.get("volume") is not None else None,
            "as_of": _to_str(info.get("regularMarketTime")),
            "market_state": _derive_market_state(),
        }
    except Exception:
        pass

    # fallback ke idx CLI
    try:
        raw = _idx("-o", "json", "market", "overview")
        d = json.loads(raw)["data"]
        idx = d.get("index", {})
        if idx.get("symbol") != symbol:
            return {}
        return {
            "symbol": idx.get("symbol", symbol),
            "name": idx.get("name", ""),
            "price": _safe_float(idx.get("price")),
            "change": _safe_float(idx.get("change")),
            "change_pct": _safe_float(idx.get("change_pct")),
            "volume": int(idx.get("volume")) if idx.get("volume") is not None else None,
            "value": _safe_float(idx.get("value")),
            "as_of": d.get("as_of", ""),
            "market_state": d.get("market_state", "UNKNOWN"),
        }
    except Exception as e:
        logger.error(f"fetch_index_quote gagal: {e}")
        return {}


def fetch_market_overview() -> Dict[str, Any]:
    """
    Snapshot pasar IDX: breadth + top movers.

    Skenario: coba yfinance untuk gainers utama; fallback ke idx CLI untuk
    data pasar lengkap (breadth, turnover, 955 emiten).
    """
    # ── primary: idx CLI karena sudah teruji lengkap ──
    try:
        raw = _idx("-o", "json", "market", "overview")
        envelope = json.loads(raw)
        d = envelope.get("data", {})
        return {
            "as_of": d.get("as_of", ""),
            "market_state": d.get("market_state", "UNKNOWN"),
            "index": d.get("index", {}),
            "breadth": {
                "universe": int(d.get("universe", 0) or 0),
                "quoted": int(d.get("quoted", 0) or 0),
                "advancing": int(d.get("advancing", 0) or 0),
                "declining": int(d.get("declining", 0) or 0),
                "unchanged": int(d.get("unchanged", 0) or 0),
                "turnover_idr": float(d.get("turnover", 0) or 0),
            },
            "gainers": d.get("gainers", []),
            "losers": d.get("losers", []),
            "most_active": d.get("most_active", []),
            "heavyweights": d.get("heavyweights", []),
            "warnings": envelope.get("warnings", []),
        }
    except Exception as e:
        logger.warning(f"idx CLI overview gagal: {e}; pakai yfinance")

    # ── fallback: yfinance untuk gainers/losers jika idx CLI gagal ──
    # Ambil daftar simbol aktif dari database atau fallback ke query umum tanpa hardcode
    try:
        from app.db.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT ticker FROM symbol WHERE is_active = 1 LIMIT 50")).fetchall()
            active_symbols = [r[0] for r in rows]
    except Exception:
        active_symbols = []

    gainers, losers, active = [], [], []
    for sym in active_symbols:
        try:
            t = yf.Ticker(f"{sym}.JK")
            info = t.info
            price = _safe_float(info.get("currentPrice")) or _safe_float(info.get("regularMarketPrice"))
            chg_pct = _safe_float(info.get("regularMarketChangePercent"))
            if price is None or chg_pct is None:
                continue
            entry = {"symbol": sym, "name": info.get("shortName", sym),
                     "price": price, "change_pct": chg_pct}
            if chg_pct > 0:
                gainers.append(entry)
            elif chg_pct < 0:
                losers.append(entry)
            else:
                active.append(entry)
        except Exception:
            pass

    return {
        "as_of": "",
        "market_state": "UNKNOWN",
        "index": {},
        "breadth": {
            "universe": 0, "quoted": 0, "advancing": 0,
            "declining": 0, "unchanged": 0, "turnover_idr": 0.0,
        },
        "gainers": gainers[:10],
        "losers": losers[:10],
        "most_active": active[:10],
        "heavyweights": [],
        "warnings": ["idx CLI unavailable; yfinance fallback aktif"],
    }


# ── 5) BUDGET / HEALTH TRACKING ────────────────────────────────────────

class SourceBudget:
    """Tracker kuota polling & backoff sederhana."""

    def __init__(self, kind: str, daily_limit: int = 200, cooldown_min: int = 10):
        self.kind = kind
        self.daily_limit = daily_limit
        self.cooldown_min = cooldown_min
        self.counter = 0
        self.last_reset = datetime.now(timezone.utc).date()
        self.next_allowed = 0.0

    def can_poll(self) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset:
            self.counter = 0
            self.last_reset = today
        if now >= self.next_allowed:
            self.counter += 1
            if self.counter > self.daily_limit:
                self.next_allowed = now + self.cooldown_min * 60
                self.counter = 1
            return True
        return False

    def status(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "counter": self.counter,
            "daily_limit": self.daily_limit,
            "next_allowed_seconds": max(
                0, int(self.next_allowed - datetime.now(timezone.utc).timestamp())
            ),
        }


quote_budget = SourceBudget("quotes", daily_limit=200, cooldown_min=10)
fund_budget = SourceBudget("fundamentals", daily_limit=50, cooldown_min=30)


# ── 6) DB CACHING (opsional) ──────────────────────────────────────────

def cache_quote_to_db(db, symbol: str, data: Dict[str, Any]) -> None:
    """Simpan quote ke model QuoteLatest (BUKAN FinancialStatementCache).
    
    CATATAN: Sebelumnya kode ini merusak tabel FinancialStatementCache karena
    menyimpan market_cap ke kolom revenue dan price ke net_income_parent.
    """
    from app.db.models import QuoteLatest

    ticker_key = symbol.upper()
    ql = db.get(QuoteLatest, ticker_key)
    if ql is None:
        ql = QuoteLatest(ticker=ticker_key)

    # Isi field quote (hanya field yang ada di model QuoteLatest)
    ql.price            = data.get("price", 0.0)
    ql.change           = data.get("change", 0.0)
    ql.change_pct       = data.get("change_pct", 0.0)
    ql.open             = data.get("open")
    ql.high             = data.get("high")
    ql.low              = data.get("low")
    ql.previous_close   = data.get("previous_close")
    ql.volume_lot       = data.get("volume_lot")
    ql.value_idr         = data.get("value_idr")
    ql.market_cap        = data.get("market_cap")
    ql.pe_trailing      = data.get("pe_trailing")
    ql.pb                = data.get("pb")
    ql.dividend_yield_pct= data.get("dividend_yield_pct")
    ql.as_of             = data.get("as_of")
    ql.source            = data.get("source", "yfinance")
    ql.fetched_at        = datetime.now(timezone.utc)

    db.add(ql)
    db.flush()


def fetch_financials_multi(symbol: str, years: int = 4) -> List[Dict[str, Any]]:
    """
    Ambil laporan keuangan tahunan untuk N tahun terakhir (yfinance).

    Setiap entri punya field DuPont lengkap + extended fields (cash, debt, minorities, shares, OCF).
    DIURUTKAN dari tahun terbaru (index 0) ke terlama.
    
    PERBAIKI (FATAL BUG FIXED):
      - Total Liabilities ≠ Total Debt (utang berbunga). Utang berbunga adalah 
        sebagian dari Total Liabilities. Untuk keseimbangan neraca WAJIB gunakan
        Total Liabilities yang sebenarnya, BUKAN Total Debt.
      - Ambil juga: cash, interest_bearing_debt, minority_interest, shares, OCF, capex, depreciation.
    """
    ysym = symbol if symbol.endswith(".JK") else f"{symbol}.JK"
    t = yf.Ticker(ysym)

    try:
        fin = t.financials
        bs = t.balance_sheet
        # JANGAN pakai `or None` pada DataFrame: truth value-nya ambiguous (ValueError).
        cf = getattr(t, "cashflow", None)
        if cf is not None and getattr(cf, "empty", True):
            cf = None
    except Exception as e:
        logger.warning(f"yfinance financials {symbol} gagal: {e}")
        return []

    if fin.empty or bs.empty:
        return []

    def get_val(df, col, key: str) -> float:
        if df is None or key not in df.index:
            return 0.0
        try:
            v = df.loc[key, col]
            if hasattr(v, "iloc"):
                v = v.iloc[0]
            import numpy as np
            if v is None:
                return 0.0
            f = float(v)
            return 0.0 if np.isnan(f) else f
        except Exception:
            return 0.0

    # Ambil info ticker untuk sector, shares outstanding, dll
    info = getattr(t, "info", {}) or {}
    fin_cols = list(fin.columns)[:years]
    out: List[Dict[str, Any]] = []

    for col in fin_cols:
        curr_date = str(col)[:10]
        fy = curr_date[:4]
        if not fy.isdigit():
            continue

        # ── Income Statement ──────────────────────────────────────
        rev = get_val(fin, col, "Total Revenue") or get_val(fin, col, "TotalRevenue")
        ni = (
            get_val(fin, col, "Net Income From Continuing Operation Net Minority Interest")
            or get_val(fin, col, "Net Income")
        )
        pretax = get_val(fin, col, "Pretax Income")
        tax = get_val(fin, col, "Tax Provision")
        interest_expense = abs(get_val(fin, col, "Interest Expense"))
        interest_income = abs(get_val(fin, col, "Interest Income"))
        ebit = get_val(fin, col, "EBIT") or get_val(fin, col, "Operating Income")
        eps = get_val(fin, col, "Diluted EPS") if "Diluted EPS" in fin.index else 0.0

        # ── Balance Sheet: kolom tidak selalu sama dengan income statement ──
        bs_col = col if col in bs.columns else (bs.columns[0] if len(bs.columns) else None)
        if bs_col is not None:
            total_assets    = get_val(bs, bs_col, "Total Assets")
            total_equity    = (
                get_val(bs, bs_col, "Stockholders Equity")
                or get_val(bs, bs_col, "Common Stock Equity")
                or get_val(bs, bs_col, "Total Equity Gross Minority Interest")
            )
            total_liabilities = (
                get_val(bs, bs_col, "Total Liabilities Net Minority Interest")
                or get_val(bs, bs_col, "Total Liab")
                or 0.0
            )
            minority_interest = get_val(bs, bs_col, "Minority Interest") or 0.0
            
            # Perbaiki: Total Liabilities WAJIB dari neraca, BUKAN dari Total Debt!
            if total_liabilities == 0.0 and total_assets > 0:
                total_liabilities = max(0.0, total_assets - total_equity - minority_interest)
            
            interest_bearing_debt = (
                get_val(bs, bs_col, "Total Debt")
                or get_val(bs, bs_col, "Long Term Debt")
                or 0.0
            )
            cash_and_equivs  = (
                get_val(bs, bs_col, "Cash And Cash Equivalents")
                or get_val(bs, bs_col, "Cash Cash Equivalents And Short Term Investments")
                or 0.0
            )
            current_assets   = get_val(bs, bs_col, "Current Assets") or 0.0
            current_liab     = get_val(bs, bs_col, "Current Liabilities") or 0.0
            
            # Shares outstanding: coba dari BS dulu, fallback ke info ticker
            shares_out = (
                get_val(bs, bs_col, "Ordinary Shares Number")
                or get_val(bs, bs_col, "Share Issued")
                or 0.0
            )
            if shares_out == 0.0:
                shares_out = float(info.get("sharesOutstanding") or 0.0)
        else:
            total_assets = total_equity = total_liabilities = 0.0
            minority_interest = interest_bearing_debt = cash_and_equivs = 0.0
            current_assets = current_liab = shares_out = 0.0

        # ── Cash Flow Statement ────────────────────────────────────
        ocf = 0.0
        capex_val = 0.0
        da_val = 0.0
        if cf is not None:
            bs_cf_col = col if col in cf.columns else (cf.columns[0] if len(cf.columns) else None)
            if bs_cf_col is not None:
                ocf = get_val(cf, bs_cf_col, "Operating Cash Flow")
                if ocf == 0.0:
                    ocf = get_val(cf, bs_cf_col, "Cash Flow From Continuing Operating Activities")
                capex_val = abs(get_val(cf, bs_cf_col, "Capital Expenditure"))
                if capex_val == 0.0:
                    capex_val = abs(get_val(cf, bs_cf_col, "Purchase Of PPE"))
                da_val = get_val(cf, bs_cf_col, "Depreciation And Amortization")
                if da_val == 0.0:
                    da_val = get_val(fin, col, "Reconciled Depreciation")

        # Fallback EBIT/EBT dari komponen yang tersedia
        if not ebit and rev:
            ebit = ni + tax + interest_expense if (ni and (tax or interest_expense)) else ni
        if not pretax and ebit:
            pretax = ebit - interest_expense

        # Sector dari info ticker
        sector = info.get("sector") or info.get("industry") or None

        out.append({
            "period": fy,
            "end_date": curr_date,
            "revenue": rev,
            "net_income": ni,
            "ebit": ebit,
            "ebt": pretax,
            # Neraca: PASTIKAN field sesuai dengan meaning akuntansinya!
            "total_assets": total_assets,
            "total_equity": total_equity,
            "total_liabilities": total_liabilities,   # ← Total Kewajiban (BUKAN Total Debt!)
            "interest_bearing_debt": interest_bearing_debt,  # ← Utang Berbunga saja
            "minority_interest": minority_interest,
            "cash_and_equivalents": cash_and_equivs,
            "current_assets": current_assets,
            "current_liabilities": current_liab,
            # Income/CF tambahan
            "interest_income": interest_income,
            "interest_expense": interest_expense,
            "tax_provision": tax,
            "operating_cash_flow": ocf,
            "capex": capex_val,
            "depreciation": da_val,
            "shares_outstanding": shares_out,
            # Metadata
            "eps_diluted": eps,
            "name": info.get("longName", symbol),
            "currency": "IDR",
            "sector": sector,
        })

    return out


def cache_financials_to_db(db, symbol: str, data: Dict[str, Any]) -> None:
    """Simpan financials ke DB untuk caching (upsert per ticker+year+period_type).
    
    PERBAIKI: Menggunakan upsert (cek dulu ada/tidak, baru update atau insert)
    agar tidak melanggar UNIQUE constraint.
    """
    from app.db.models import FinancialStatementCache
    from app.services.dupont_engine import PeriodType
    import hashlib

    raw = json.dumps(data, sort_keys=True).encode()
    fhash = hashlib.sha256(raw).hexdigest()
    fy = data.get("end_date", "")[:4]
    year = int(fy) if fy.isdigit() else datetime.utcnow().year
    period_val = PeriodType.FY.value

    # ── Upsert: cek existing dulu, baru update atau insert ──────────
    existing = db.exec(
        select(FinancialStatementCache).where(
            FinancialStatementCache.ticker == symbol.upper(),
            FinancialStatementCache.year == year,
            FinancialStatementCache.period_type == period_val,
        )
    ).first()

    if existing:
        # UPDATE record yang sudah ada dengan field baru
        existing.file_hash = fhash
        existing.company_name = data.get("name", symbol)
        existing.currency = data.get("currency", "IDR")
        existing.unit_multiplier = 1.0
        existing.revenue = data.get("revenue", 0.0)
        existing.ebit = data.get("ebit", 0.0)
        existing.ebt = data.get("ebt", 0.0)
        existing.net_income_parent = data.get("net_income", 0.0)
        existing.total_assets = data.get("total_assets", 0.0)
        existing.total_liabilities = data.get("total_liabilities", 0.0)
        existing.total_equity_parent = data.get("total_equity", 0.0)
        # ── Extended fields (v4.0) ──────────────────────────────────
        existing.sector = data.get("sector")
        existing.shares_outstanding = data.get("shares_outstanding")
        existing.cash_and_equivalents = data.get("cash_and_equivalents")
        existing.interest_bearing_debt = data.get("interest_bearing_debt")
        existing.current_assets = data.get("current_assets")
        existing.current_liabilities = data.get("current_liabilities")
        existing.interest_income = data.get("interest_income")
        existing.interest_expense = data.get("interest_expense")
        existing.tax_provision = data.get("tax_provision")
        existing.operating_cash_flow = data.get("operating_cash_flow")
        existing.capex = data.get("capex")
        existing.depreciation = data.get("depreciation")
        existing.minority_interest = data.get("minority_interest")
        record = existing
    else:
        record = FinancialStatementCache(
            file_hash=fhash,
            ticker=symbol.upper(),
            company_name=data.get("name", symbol),
            year=year,
            period_type=period_val,
            currency=data.get("currency", "IDR"),
            unit_multiplier=1.0,
            revenue=data.get("revenue", 0.0),
            ebit=data.get("ebit", 0.0),
            ebt=data.get("ebt", 0.0),
            net_income_parent=data.get("net_income", 0.0),
            total_assets=data.get("total_assets", 0.0),
            total_liabilities=data.get("total_liabilities", 0.0),
            total_equity_parent=data.get("total_equity", 0.0),
            sector=data.get("sector"),
            shares_outstanding=data.get("shares_outstanding"),
            cash_and_equivalents=data.get("cash_and_equivalents"),
            interest_bearing_debt=data.get("interest_bearing_debt"),
            current_assets=data.get("current_assets"),
            current_liabilities=data.get("current_liabilities"),
            interest_income=data.get("interest_income"),
            interest_expense=data.get("interest_expense"),
            tax_provision=data.get("tax_provision"),
            operating_cash_flow=data.get("operating_cash_flow"),
            capex=data.get("capex"),
            depreciation=data.get("depreciation"),
            minority_interest=data.get("minority_interest"),
            created_at=datetime.now(timezone.utc),
        )

    db.add(record)


def cache_financials_multi_to_db(db, symbol: str, rows: List[Dict[str, Any]]) -> int:
    """Simpan beberapa periode tahunan sekaligus. Return jumlah baris tersimpan.
    
    PERBAIKI: Pakai upsert per periode untuk hindari UNIQUE constraint violation
    dan masukkan seluruh 15 field extended (sector, shares, cash, debt, minorities, OCF, dll).
    """
    from app.db.models import FinancialStatementCache
    from app.services.dupont_engine import PeriodType
    import hashlib

    n = 0
    for data in rows:
        raw = json.dumps(data, sort_keys=True).encode()
        fhash = hashlib.sha256(raw).hexdigest()
        fy = data.get("end_date", "")[:4]
        year = int(fy) if fy.isdigit() else datetime.utcnow().year
        period_val = PeriodType.FY.value

        # ── Upsert: cek existing dulu ─────────────────────────────
        existing = db.exec(
            select(FinancialStatementCache).where(
                FinancialStatementCache.ticker == symbol.upper(),
                FinancialStatementCache.year == year,
                FinancialStatementCache.period_type == period_val,
            )
        ).first()

        if existing:
            existing.file_hash = fhash
            existing.company_name = data.get("name", symbol)
            existing.currency = data.get("currency", "IDR")
            existing.unit_multiplier = 1.0
            existing.revenue = data.get("revenue", 0.0)
            existing.ebit = data.get("ebit", 0.0)
            existing.ebt = data.get("ebt", 0.0)
            existing.net_income_parent = data.get("net_income", 0.0)
            existing.total_assets = data.get("total_assets", 0.0)
            existing.total_liabilities = data.get("total_liabilities", 0.0)
            existing.total_equity_parent = data.get("total_equity", 0.0)
            # Extended fields
            existing.sector = data.get("sector")
            existing.shares_outstanding = data.get("shares_outstanding")
            existing.cash_and_equivalents = data.get("cash_and_equivalents")
            existing.interest_bearing_debt = data.get("interest_bearing_debt")
            existing.current_assets = data.get("current_assets")
            existing.current_liabilities = data.get("current_liabilities")
            existing.interest_income = data.get("interest_income")
            existing.interest_expense = data.get("interest_expense")
            existing.tax_provision = data.get("tax_provision")
            existing.operating_cash_flow = data.get("operating_cash_flow")
            existing.capex = data.get("capex")
            existing.depreciation = data.get("depreciation")
            existing.minority_interest = data.get("minority_interest")
            db.add(existing)
        else:
            db.add(FinancialStatementCache(
                file_hash=fhash,
                ticker=symbol.upper(),
                company_name=data.get("name", symbol),
                year=year,
                period_type=period_val,
                currency=data.get("currency", "IDR"),
                unit_multiplier=1.0,
                revenue=data.get("revenue", 0.0),
                ebit=data.get("ebit", 0.0),
                ebt=data.get("ebt", 0.0),
                net_income_parent=data.get("net_income", 0.0),
                total_assets=data.get("total_assets", 0.0),
                total_liabilities=data.get("total_liabilities", 0.0),
                total_equity_parent=data.get("total_equity", 0.0),
                sector=data.get("sector"),
                shares_outstanding=data.get("shares_outstanding"),
                cash_and_equivalents=data.get("cash_and_equivalents"),
                interest_bearing_debt=data.get("interest_bearing_debt"),
                current_assets=data.get("current_assets"),
                current_liabilities=data.get("current_liabilities"),
                interest_income=data.get("interest_income"),
                interest_expense=data.get("interest_expense"),
                tax_provision=data.get("tax_provision"),
                operating_cash_flow=data.get("operating_cash_flow"),
                capex=data.get("capex"),
                depreciation=data.get("depreciation"),
                minority_interest=data.get("minority_interest"),
                created_at=datetime.now(timezone.utc),
            ))
        n += 1
    return n
