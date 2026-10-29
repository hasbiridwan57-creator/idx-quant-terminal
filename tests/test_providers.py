"""Test untuk provider layer (Fase 1) — tidak memanggil jaringan; memakai monkeypatch."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.providers import classify as classify_mod
from app.providers import yahoo as yahoo_mod
from app.providers.classify import DataFreshness, SourceHealth, classify_freshness
from app.providers.yahoo import SourceBudget, _parse_quote


# ── 1) Parsing quote ───────────────────────────────────────────────────

def test_parse_quote_maps_all_fields():
    entry = {
        "symbol": "BBCA",
        "name": "PT Bank Central Asia Tbk",
        "currency": "IDR",
        "price": 5025.0,
        "change": -150.0,
        "change_pct": -2.8985507,
        "previous_close": 5175.0,
        "volume": 495623900,
        "market_cap": 617279813320704.0,
        "pe_trailing": 10.646187,
        "price_to_book": 2.2825222,
        "dividend_yield_pct": 7.58,
        "week52_high": 8750.0,
        "week52_low": 4740.0,
        "market_state": "PREPRE",
        "market_time": "2026-10-23T16:14:59+07:00",
        "source": "yahoo:quote",
    }
    q = _parse_quote(entry)
    assert q["price"] == 5025.0
    assert q["change_pct"] == pytest.approx(-2.8985507)
    assert q["pb"] == pytest.approx(2.2825222)
    assert q["dividend_yield_pct"] == pytest.approx(7.58)
    assert q["as_of"] == "2026-10-23T16:14:59+07:00"
    assert q["source"] == "yahoo:quote"


def test_parse_quote_handles_null_fields():
    entry = {"symbol": "XXXX", "price": 100.0, "market_cap": None, "pe_trailing": None}
    q = _parse_quote(entry)
    assert q["market_cap"] is None
    assert q["pe_trailing"] is None
    assert q["pb"] is None


# ── 2) Freshness classifier ───────────────────────────────────────────

def test_freshness_realtime_when_fresh():
    # Jam 10:00 WIB (03:00 UTC), bursa OPEN, data seketika → REALTIME.
    fake_fetched = datetime(2026, 10, 27, 3, 0, 0, tzinfo=timezone.utc)  # 10:00 WIB
    as_of = fake_fetched.isoformat()
    # Pakai state IDX valid agar clock derivation di-skip
    res = classify_freshness(fake_fetched, as_of, "OPEN", "yahoo")
    assert res.label == DataFreshness.REALTIME
    assert res.freshness_pct > 95


def test_freshness_delayed_between_2_and_60_minutes():
    # Jam 10:00 WIB, data 5 menit lalu → DELAYED
    fake_fetched = datetime(2026, 10, 27, 3, 0, 0, tzinfo=timezone.utc)  # 10:00 WIB
    fake_as_of = datetime(2026, 10, 27, 2, 55, 0, tzinfo=timezone.utc)  # 09:55 WIB
    as_of_iso = fake_as_of.isoformat()
    res = classify_freshness(fake_fetched, as_of_iso, "OPEN", "yahoo")
    assert res.label == DataFreshness.DELAYED
    assert res.delay_minutes == 5


def test_freshness_eod_when_market_closed():
    """Data close Jumat (as_of 23 Okt 16:14 WIB) → EOD, bukan STALE.

    Snapshot EOD tetap EOD walau di-fetch hari berikutnya.
    """
    fetched = datetime(2026, 10, 26, 1, 30, 0, tzinfo=timezone.utc)  # Senin 08:30 WIB
    as_of_iso = "2026-10-23T16:14:59+07:00"  # Jumat close
    res = classify_freshness(fetched, as_of_iso, "PREPRE", "yahoo")
    assert res.label == DataFreshness.END_OF_DAY
    assert res.delay_minutes > 60


def test_freshness_unknown_when_no_as_of():
    res = classify_freshness(None, None, "REGULAR", "yahoo")
    assert res.label == DataFreshness.UNKNOWN
    assert res.freshness_pct == 0.0


def test_freshness_stale_during_trading_hours():
    """Saat bursa buka, data > 60 menit = STALE (bukan EOD)."""
    # Fetch Senin 10:10 WIB (03:10 UTC), data dari Senin 09:00 WIB (70 menit lalu, sesi aktif)
    fetched = datetime(2026, 10, 26, 3, 10, 0, tzinfo=timezone.utc)  # 10:10 WIB
    as_of_iso = "2026-10-26T09:00:00+07:00"  # 09:00 WIB
    res = classify_freshness(fetched, as_of_iso, "PREPRE", "yahoo")
    assert res.label == DataFreshness.STALE
    assert res.delay_minutes == 70


# ── 3) SourceBudget ────────────────────────────────────────────────────

def test_source_budget_resets_daily_and_cools_down():
    b = SourceBudget("test", daily_limit=2, cooldown_min=10)
    assert b.can_poll() is True
    assert b.can_poll() is True
    # Melebihi limit → masuk cooldown, poll berikutnya ditolak
    assert b.can_poll() is True  # triggers cooldown
    assert b.can_poll() is False
    st = b.status()
    assert st["kind"] == "test"
    assert st["next_allowed_seconds"] > 0


# ── 4) Provider fetchers (mocked) ──────────────────────────────────────

class _FakeTicker:
    """Mock yfinance.Ticker yang mengembalikan info/financials predetermined."""

    _info: Dict[str, Any] = {}
    _fin = None
    _bs = None

    def __init__(self, symbol, *a, **kw):
        self.symbol = symbol

    @property
    def info(self):
        return dict(self._info)

    @property
    def financials(self):
        return self._fin

    @property
    def balance_sheet(self):
        return self._bs


def test_fetch_quotes_uses_yfinance(monkeypatch):
    """yfinance adalah primary path; .JK suffix ditambahkan otomatis."""
    calls = []

    def fake_tickers(symbols_str):
        calls.append(symbols_str)
        syms = symbols_str.split()

        class _Holder:
            tickers = {}

        holder = _Holder()
        for s in syms:
            holder.tickers[s] = _FakeTicker(s)
        _FakeTicker._info = {
            "shortName": "PT Test Tbk",
            "currentPrice": 100.0,
            "previousClose": 99.0,
            "regularMarketChange": 1.0,
            "regularMarketChangePercent": 1.01,
            "marketCap": 1_000_000_000.0,
            "trailingPE": 10.0,
            "priceToBook": 1.5,
            "dividendYield": 0.05,
            "52WeekHigh": 150.0,
            "52WeekLow": 50.0,
            "regularMarketTime": 1793000000,
        }
        return holder

    monkeypatch.setattr(yahoo_mod.yf, "Tickers", fake_tickers)
    out = yahoo_mod.fetch_quotes(["BBCA", "BBRI", "TLKM"])

    assert set(out.keys()) == {"BBCA", "BBRI", "TLKM"}
    assert out["BBCA"]["price"] == 100.0
    assert out["BBCA"]["change_pct"] == 1.01
    assert out["BBCA"]["pb"] == 1.5
    assert out["BBCA"]["dividend_yield_pct"] == 5.0  # 0.05 → 5%
    assert out["BBCA"]["source"] == "yfinance"
    # Suffix .JK otomatis ditambahkan
    assert calls and all(".JK" in s for s in calls[0].split())


def test_fetch_quotes_falls_back_to_idx_cli(monkeypatch):
    """Kalau yfinance error → fallback ke idx CLI."""
    def boom(*a, **kw):
        raise RuntimeError("yfinance down")

    def fake_idx(*args, timeout=45):
        if "quote" in args:
            sym = args[args.index("quote") + 1]
            return json.dumps({
                "schema": "idx.quotes.v1",
                "data": [{
                    "symbol": sym, "price": 777.0, "change": 1.0, "change_pct": 0.1,
                    "market_state": "PREPRE", "market_time": "2026-10-26T10:00:00+07:00",
                }],
            })
        raise AssertionError(f"unexpected call {args}")

    monkeypatch.setattr(yahoo_mod.yf, "Tickers", boom)
    monkeypatch.setattr(yahoo_mod, "_idx", fake_idx)
    out = yahoo_mod.fetch_quotes(["BBCA"])
    assert out["BBCA"]["price"] == 777.0
    assert out["BBCA"]["source"] == "idx-cli"


def test_fetch_financials_maps_dupont_fields(monkeypatch):
    """Field yfinance financials/balance_sheet → field DuPont Engine."""
    import pandas as pd

    # yfinance format: index = line item, columns = tanggal (descending)
    d25 = "2025-12-31"
    d24 = "2024-12-31"
    fin = pd.DataFrame.from_dict(
        {
            "Total Revenue": {d25: 114_319_648_000_000.0, d24: 108_796_625_000_000.0},
            "Net Income From Continuing Operation Net Minority Interest": {
                d25: 57_537_287_000_000.0, d24: 54_836_305_000_000.0,
            },
            "Pretax Income": {d25: 78_904_000_000_000.0, d24: 74_200_000_000_000.0},
            "Interest Expense": {d25: 6_012_580_000_000.0, d24: 5_500_000_000_000.0},
            "Tax Provision": {d25: 21_366_713_000_000.0, d24: 19_363_695_000_000.0},
            "Diluted EPS": {d25: 470.0, d24: 448.0},
        },
        orient="index",
    )
    bs = pd.DataFrame.from_dict(
        {
            "Total Assets": {d25: 1_586_828_536_000_000.0, d24: 1_449_301_328_000_000.0},
            "Stockholders Equity": {d25: 281_466_478_000_000.0, d24: 262_640_621_000_000.0},
            "Total Debt": {d25: 52_021_302_394_880.0, d24: 45_000_000_000_000.0},
        },
        orient="index",
    )
    # Pastikan kolom urut descending (terbaru dulu) seperti yfinance asli
    fin = fin.reindex(columns=sorted(fin.columns, reverse=True))
    bs = bs.reindex(columns=sorted(bs.columns, reverse=True))

    _FakeTicker._fin = fin
    _FakeTicker._bs = bs
    monkeypatch.setattr(yahoo_mod.yf, "Ticker", _FakeTicker)

    f = yahoo_mod.fetch_financials("BBCA")
    assert f["revenue"] == 114_319_648_000_000.0
    assert f["net_income"] == 57_537_287_000_000.0
    assert f["total_assets"] == 1_586_828_536_000_000.0
    assert f["total_equity"] == 281_466_478_000_000.0
    assert f["total_debt"] == 52_021_302_394_880.0
    assert f["interest_expense"] == 6_012_580_000_000.0
    assert f["pretax_income"] == 78_904_000_000_000.0
    assert f["tax_provision"] == 21_366_713_000_000.0
    assert f["end_date"] == "2025-12-31"
    assert f["period"] == "2025"


def test_fetch_market_overview_maps_breadth(monkeypatch):
    payload = {
        "schema": "idx.market.v1",
        "warnings": ["42 of 955 tickers returned no quote and were skipped"],
        "data": {
            "as_of": "2026-10-23T16:14:59+07:00",
            "market_state": "PREPRE",
            "index": {"symbol": "^JKSE", "price": 5439.258, "change": 51.35791,
                      "change_pct": 0.9532083, "volume": 0, "value": 0.0},
            "universe": 955, "quoted": 913, "advancing": 501, "declining": 190,
            "unchanged": 222, "turnover": 13772092377400.0,
            "gainers": [{"symbol": "FAST", "price": 380.0, "change_pct": 25.0}],
            "losers": [], "most_active": [], "heavyweights": [],
        },
    }
    monkeypatch.setattr(
        yahoo_mod, "_idx", lambda *a, timeout=45: json.dumps(payload)
    )
    m = yahoo_mod.fetch_market_overview()
    assert m["breadth"]["advancing"] == 501
    assert m["breadth"]["universe"] == 955
    assert m["index"]["price"] == 5439.258
    assert len(m["warnings"]) == 1
