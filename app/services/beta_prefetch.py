"""
Prefetch beta bermassa untuk screener 937 emiten.

MASALAH YANG DIPERBAIKI
-----------------------
`build_peer_screener_rows` memanggil `compute_wacc` per emiten. Tiap
panggilan menurunkan beta lewat `compute_performance`, yang menarik 5 tahun
harga dari tabel `quotehistorydaily` — SATU QUERY PER EMITEN. Di SQLite
lokal itu ~20 ms (total ~19 detik, tidak terasa). Di Postgres remote seperti
Neon, tiap query = satu round-trip ~59 ms, jadi 937 query x 2 (emiten +
benchmark) = 5.419 round-trip = 320 detik. Halaman menggantung.

Obatnya bukan menaikkan timeout: kurangi round-trip-nya. Fungsi di sini
menarik SEMUA harga yang dibutuhkan dalam SATU query, menghitung return
harian sekali, lalu mengisi `_BETA_CACHE` di cost_of_capital. Sesudahnya
`_get_beta` cukup membaca cache — nol query tambahan.

Hasil beta identik dengan jalur lama karena rumus regresinya sama
(kovarians return harian emiten vs IHSG, dibagi varians IHSG). Yang berubah
hanya dari mana datanya datang: satu query besar, bukan 937 query kecil.
"""

from __future__ import annotations

import datetime as _dt
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlmodel import Session

# Ticker benchmark di tabel harga. IHSG disimpan seperti emiten lain.
BENCH_TICKER = "IHSG"

# Jendela beta: 5 tahun terakhir, sama dengan default compute_performance.
LOOKBACK_YEARS = 5

# Minimum observasi bersama agar regresi dianggap sah. Sama dengan
# performance_engine.MIN_OBS supaya hasil batch == hasil per-emiten.
MIN_OBS = 30


def _fetch_all_prices(session: Session, tickers: List[str]) -> Dict[str, Dict[str, float]]:
    """Satu query: {ticker: {date_str: close}} untuk semua ticker + IHSG."""
    if not tickers:
        return {}
    want = sorted({t.upper() for t in tickers} | {BENCH_TICKER})
    # Kolom `date` disimpan sebagai VARCHAR (campuran SQLite warisan), jadi
    # perbandingan dilakukan sebagai string ISO: 'YYYY-MM-DD'.
    # ASCII 'YYYY-MM-DD' terurut sama dengan urutan tanggal sebenarnya.
    cutoff = (_dt.date.today() - _dt.timedelta(days=365 * LOOKBACK_YEARS)).isoformat()

    # ANY(array) hanya ada di Postgres. SQLite butuh IN (?,?,...). Keduanya
    # didukung supaya app jalan sama cepat di lokal (SQLite) maupun di server
    # (Neon/Postgres) — sebelumnya `ANY` membuat prefetch gagal senyap di
    # SQLite dan screener lokal kembali lambat.
    is_pg = session.get_bind().dialect.name in ("postgresql", "postgres")
    if is_pg:
        q = text(
            "SELECT ticker, date, close FROM quotehistorydaily "
            "WHERE ticker = ANY(:tk) AND close > 0 AND date >= :cutoff "
            "ORDER BY ticker, date"
        )
        params: Dict[str, Any] = {"tk": want, "cutoff": cutoff}
    else:
        placeholders = ",".join(f":t{i}" for i in range(len(want)))
        q = text(
            "SELECT ticker, date, close FROM quotehistorydaily "
            f"WHERE ticker IN ({placeholders}) AND close > 0 AND date >= :cutoff "
            "ORDER BY ticker, date"
        )
        params = {f"t{i}": t for i, t in enumerate(want)}
        params["cutoff"] = cutoff

    rows = session.execute(q, params).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    for tkr, dt, close in rows:
        if close is None:
            continue
        key = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
        out.setdefault(str(tkr).upper(), {})[key] = float(close)
    return out


def _daily_returns(series: Dict[str, float]) -> Dict[str, float]:
    """Return harian sederhana berurut tanggal: {date: r}."""
    items = sorted(series.items())
    out: Dict[str, float] = {}
    for i in range(1, len(items)):
        prev, cur = items[i - 1][1], items[i][1]
        if prev > 0:
            out[items[i][0]] = (cur / prev) - 1.0
    return out


def _beta_vs(returns: Dict[str, float], bench_ret: Dict[str, float]) -> Optional[float]:
    """Beta = cov(r_i, r_m) / var(r_m) pada tanggal yang beririsan."""
    common = sorted(set(returns) & set(bench_ret))
    if len(common) < MIN_OBS:
        return None
    xs = [bench_ret[d] for d in common]   # pasar
    ys = [returns[d] for d in common]     # emiten
    n = len(common)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (n - 1)
    var = sum((x - mx) ** 2 for x in xs) / (n - 1)
    if var <= 0:
        return None
    b = cov / var
    if not math.isfinite(b) or b == 0:
        return None
    return float(b)


def prefetch_betas(session: Optional[Session], tickers: List[str],
                   ttl_s: int = 3600) -> int:
    """
    Isi `_BETA_CACHE` untuk banyak ticker sekaligus. Return jumlah yang terisi.

    Dipanggil di awal `build_peer_screener_rows`; setelah itu tiap
    `_get_beta(ticker)` dalam loop cukup membaca memori.
    """
    if session is None or not tickers:
        return 0

    from app.services import cost_of_capital as _cc

    # Hormati TTL: jangan buang cache yang masih segar (beta berubah sekali
    # sehari bersama harga EOD).
    now = time.time()
    fresh = {t for t in (x.upper() for x in tickers)
             if (c := _cc._BETA_CACHE.get(t)) and (now - c[0]) < ttl_s}
    todo = sorted({t.upper() for t in tickers} - fresh)
    if not todo:
        return 0

    prices = _fetch_all_prices(session, todo)
    bench = prices.get(BENCH_TICKER)
    if not bench:
        # Tanpa benchmark, beta tidak bisa diregresi. Biarkan _get_beta
        # jatuh ke proxy sektor seperti perilaku lama.
        return 0
    bench_ret = _daily_returns(bench)

    filled = 0
    for t in todo:
        series = prices.get(t)
        if not series:
            continue
        b = _beta_vs(_daily_returns(series), bench_ret)
        if b is None:
            continue
        _cc._BETA_CACHE[t] = (
            now,
            b,
            "MARKET (regresi return harian vs IHSG, 5 tahun)",
        )
        filled += 1
    return filled


def _self_check() -> None:
    """Uji rumus beta dengan deret buatan: emiten 2x pasar -> beta 2.0."""
    # Return pasar dibuat bervariasi (bukan linear) supaya regresi punya
    # varians yang sah. Pola deterministik: bergantian naik/turun.
    days = [f"2020-{1 + (i // 28):02d}-{1 + (i % 28):02d}" for i in range(61)]
    mkt_ret = [0.01 if i % 2 == 0 else -0.008 for i in range(60)]
    bench_px, em_px = [100.0], [100.0]
    for r in mkt_ret:
        bench_px.append(bench_px[-1] * (1 + r))
        em_px.append(em_px[-1] * (1 + 2 * r))   # persis 2x return pasar
    bench = {d: bench_px[i] for i, d in enumerate(days)}
    em = {d: em_px[i] for i, d in enumerate(days)}

    b = _beta_vs(_daily_returns(em), _daily_returns(bench))
    assert b is not None and abs(b - 2.0) < 0.02, f"beta salah: {b}"

    # Seri datar -> varians nol -> None, bukan ZeroDivisionError.
    flat = {d: 100.0 for d in days}
    assert _beta_vs(_daily_returns(flat), _daily_returns(bench)) is None

    # Observasi kurang -> None.
    tiny = {d: bench_px[i] for i, d in enumerate(days[:5])}
    assert _beta_vs(_daily_returns(tiny), _daily_returns(bench)) is None
    print("beta_prefetch self-check OK")


if __name__ == "__main__":
    _self_check()
