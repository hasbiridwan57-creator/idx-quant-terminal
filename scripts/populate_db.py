"""
scripts/populate_db.py
Sinkronisasi seluruh emiten BEI dan quote terkini ke database lokal (SQLite).
Dijalankan secara berkala atau saat inisialisasi awal sistem.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.db.database import engine, init_db
from app.db.models import Symbol, QuoteLatest, IndexQuote, MarketSnapshot
from app.providers import yahoo as ymod
from sqlmodel import Session, select

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def populate_symbols_and_market_data():
    """
    1. Ambil snapshot market overview (memuat 955 emiten BEI).
    2. Simpan daftar simbol ke tabel `symbol`.
    3. Simpan mover/gainers/losers ke tabel `quotelatest`.
    4. Simpan indeks IHSG (^JKSE) ke tabel `indexquote`.
    5. Simpan ringkasan snapshot ke tabel `marketsnapshot`.
    """
    init_db()
    logger.info("Mengambil market overview dari provider...")
    try:
        overview = ymod.fetch_market_overview()
    except Exception as exc:
        logger.error(f"Gagal mengambil market overview: {exc}")
        return

    as_of = overview.get("as_of", "")
    market_state = overview.get("market_state", "UNKNOWN")
    breadth = overview.get("breadth", {})
    idx_info = overview.get("index", {})

    logger.info(f"Market State: {market_state} | As Of: {as_of} | Universe: {breadth.get('universe')} emiten")

    with Session(engine) as session:
        # ── 1. Simpan Indeks IHSG ──
        if idx_info and idx_info.get("symbol"):
            sym = idx_info["symbol"]
            existing_idx = session.exec(select(IndexQuote).where(IndexQuote.symbol == sym)).first()
            if existing_idx:
                existing_idx.price = float(idx_info.get("price") or 0)
                existing_idx.change = float(idx_info.get("change") or 0)
                existing_idx.change_pct = float(idx_info.get("change_pct") or 0)
                existing_idx.as_of = as_of
                existing_idx.fetched_at = datetime.now(timezone.utc)
            else:
                new_idx = IndexQuote(
                    symbol=sym,
                    name=idx_info.get("name") or "IDX COMPOSITE",
                    price=float(idx_info.get("price") or 0),
                    change=float(idx_info.get("change") or 0),
                    change_pct=float(idx_info.get("change_pct") or 0),
                    as_of=as_of,
                    fetched_at=datetime.now(timezone.utc),
                )
                session.add(new_idx)
            logger.info(f"Tersimpan Index: {sym} = {idx_info.get('price')} ({idx_info.get('change_pct')}%)")

        # ── 2. Simpan Seluruh Emiten Aktif (Gainers, Losers, Most Active, Heavyweights) ──
        all_movers = (
            overview.get("gainers", [])
            + overview.get("losers", [])
            + overview.get("most_active", [])
            + overview.get("heavyweights", [])
        )

        seen_tickers = set()
        count_symbols = 0
        count_quotes = 0

        for m in all_movers:
            ticker = m.get("symbol")
            if not ticker or ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            # Insert / Update Symbol
            sym_rec = session.exec(select(Symbol).where(Symbol.ticker == ticker)).first()
            if not sym_rec:
                sym_rec = Symbol(
                    ticker=ticker,
                    name=m.get("name") or f"PT {ticker} Tbk",
                    is_active=True,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(sym_rec)
                count_symbols += 1

            # Insert / Update QuoteLatest
            q_rec = session.exec(select(QuoteLatest).where(QuoteLatest.ticker == ticker)).first()
            if q_rec:
                q_rec.price = float(m.get("price") or 0)
                q_rec.change = float(m.get("change") or 0)
                q_rec.change_pct = float(m.get("change_pct") or 0)
                q_rec.volume_lot = int((m.get("volume") or 0) / 100)
                q_rec.value_idr = float(m.get("value") or 0)
                q_rec.market_cap = float(m.get("market_cap") or 0) if m.get("market_cap") else None
                q_rec.as_of = as_of
                q_rec.fetched_at = datetime.now(timezone.utc)
            else:
                q_rec = QuoteLatest(
                    ticker=ticker,
                    price=float(m.get("price") or 0),
                    change=float(m.get("change") or 0),
                    change_pct=float(m.get("change_pct") or 0),
                    volume_lot=int((m.get("volume") or 0) / 100),
                    value_idr=float(m.get("value") or 0),
                    market_cap=float(m.get("market_cap") or 0) if m.get("market_cap") else None,
                    as_of=as_of,
                    source="idx-market-overview",
                    fetched_at=datetime.now(timezone.utc),
                )
                session.add(q_rec)
                count_quotes += 1

        # ── 3. Simpan Market Snapshot Terminal ──
        snap = MarketSnapshot(
            trading_date=as_of[:10] if as_of else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            ihsg_last=float(idx_info.get("price") or 0),
            change_pts=float(idx_info.get("change") or 0),
            change_pct=float(idx_info.get("change_pct") or 0),
            total_value_bn=float(breadth.get("turnover_idr") or 0) / 1e9,
            net_foreign_rg_bn=0.0,
            market_status=market_state,
            headline=f"IHSG {idx_info.get('price')} ({idx_info.get('change_pct'):+.2f}%). Turnover Rp {float(breadth.get('turnover_idr') or 0)/1e12:.2f} Triliun.",
            payload_json=json.dumps(overview),
            created_at=datetime.now(timezone.utc),
        )
        session.add(snap)

        session.commit()
        logger.info(f"Sukses sinkronisasi DB: +{count_symbols} emiten baru, +{count_quotes} quote terkini, 1 market snapshot.")


if __name__ == "__main__":
    populate_symbols_and_market_data()
