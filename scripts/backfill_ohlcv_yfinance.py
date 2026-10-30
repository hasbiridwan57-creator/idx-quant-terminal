"""
Backfill OHLCV 5 tahun (2021-01-01 s/d sekarang) untuk seluruh emiten yang
punya data XBRL audited, sumber yfinance (.JK).

ZERO-FAKE:
  - Hanya menulis baris yang benar-benar dikembalikan yfinance.
  - Ticker tanpa data -> dicatat skipped, TIDAK diisi angka karangan.
  - Idempoten: unique (ticker, date) -> skip yang sudah ada.

Usage:
  python backfill_ohlcv_yfinance.py                 # semua ticker di XBRL
  python backfill_ohlcv_yfinance.py ASII BBCA UNTR  # ticker tertentu
"""
from __future__ import annotations

import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

sys.path.insert(0, "/Users/hasbi/idx-quant-terminal")

import yfinance as yf
from sqlalchemy import text
from sqlmodel import Session

from app.db.database import engine
from app.db.models import QuoteHistoryDaily
from app.services.idx_audited_financials import _load

START = "2021-01-01"


def _existing_dates(session: Session, ticker: str) -> set[str]:
    rows = session.execute(
        text("SELECT date FROM quotehistorydaily WHERE ticker = :t"), {"t": ticker}
    ).fetchall()
    return {r[0] for r in rows}


def backfill(ticker: str, session: Session) -> tuple[int, str]:
    """Return (inserted, status)."""
    sym = f"{ticker.upper()}.JK"
    try:
        df = yf.download(sym, start=START, progress=False, auto_adjust=True, threads=False)
    except Exception as e:
        return 0, f"ERROR {type(e).__name__}"

    if df is None or df.empty:
        return 0, "NO_DATA"

    # yfinance multi-index columns -> flatten
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = [c[0] for c in df.columns]

    have = _existing_dates(session, ticker.upper())
    inserted = 0
    for idx, row in df.iterrows():
        d = idx.strftime("%Y-%m-%d")
        if d in have:
            continue
        try:
            c = float(row["Close"])
            if c != c or c <= 0:  # NaN / invalid
                continue
            session.add(QuoteHistoryDaily(
                ticker=ticker.upper(),
                date=d,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=c,
                volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            ))
            inserted += 1
        except Exception:
            continue
    session.commit()
    return inserted, "OK"


def main() -> None:
    args = [a.upper() for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        tickers = args
    else:
        data = _load()
        tickers = sorted(data.keys())

    print(f"[backfill] {len(tickers)} ticker, start={START}, source=yfinance .JK")
    total = 0
    ok = skip = err = 0
    with Session(engine) as session:
        for i, tk in enumerate(tickers, 1):
            n, status = backfill(tk, session)
            total += n
            if status == "OK":
                ok += 1
            elif status == "NO_DATA":
                skip += 1
            else:
                err += 1
            if i % 50 == 0 or i == len(tickers):
                print(f"  {i}/{len(tickers)} ok={ok} nodata={skip} err={err} rows={total}")
    print(f"DONE rows={total} ok={ok} nodata={skip} err={err}")


if __name__ == "__main__":
    main()
