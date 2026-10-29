"""Freshness classifier & health monitor (Fase 0 — 4.4 / PRD)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo  # Python 3.9+


class DataFreshness(str, Enum):
    """Klasifikasi label kesegaran data (UI chip)."""
    REALTIME   = "REALTIME"   # < 2 menit dari as_of, bursa aktif
    DELAYED    = "DELAYED"    # 2–60 menit, bursa aktif
    END_OF_DAY = "EOD"        # bursa tutup / di luar sesi / akhir pekan
    STALE      = "STALE"      # bursa aktif tapi data > 60 menit
    UNKNOWN    = "UNKNOWN"


class SourceHealth(str, Enum):
    """Status kesehatan satu sumber data."""
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"   # ada field yang hilang / timeout parsial
    RUSAK    = "RUSAK"       # respons kosong / error; auto-switch ke cadangan


_WIB = ZoneInfo("Asia/Jakarta")

# State bursa IDX yang valid. State dari Yahoo (PREPRE, REGULAR, dll.) yang
# berbasis jam AS TIDAK masuk set ini — diabaikan demi state turunan WIB.
_IDX_STATES = {
    "OPEN",
    "CLOSED EOD",
    "PREOPEN",
    "PRECLOSE",
    "POSTCLOSE",
    "CLOSED",
}


@dataclass
class FreshnessResult:
    label: DataFreshness
    freshness_pct: float          # 0..100, 100 = paling fresh
    as_of_wib: str               # formatted "dd MMM yyyy HH:mm"
    delay_minutes: int           # beda antara fetched_at dan as_of
    source: str                  # nama provider
    market_state: str            # OPEN / CLOSED EOD / PREOPEN / ...


def _parse_as_of(as_of: str | None) -> datetime:
    """Parse as_of string (ISO) ke datetime WIB."""
    if not as_of:
        return datetime.now(_WIB)
    try:
        return datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(_WIB)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(as_of).replace(tzinfo=_WIB)
    except ValueError:
        return datetime.now(_WIB)


def _derive_idx_state(
    moment: datetime,
    market_open_h: int,
    market_open_min: int,
    market_close_h: int,
    market_close_min: int,
) -> str:
    """Tentukan state bursa IDX dari jam lokal WIB + hari kalender."""
    if moment.weekday() >= 5:  # Sabtu=5, Minggu=6
        return "CLOSED EOD"
    minute_of_day = moment.hour * 60 + moment.minute
    open_min = market_open_h * 60 + market_open_min
    close_min = market_close_h * 60 + market_close_min
    if minute_of_day < open_min:
        return "PREOPEN"
    if minute_of_day <= close_min:
        return "OPEN"
    return "CLOSED EOD"


def classify_freshness(
    fetched_at: datetime | None,
    as_of: str | None,
    market_state: str,
    source: str = "unknown",
    *,
    market_open_h: int = 9,
    market_open_min: int = 0,
    market_close_h: int = 15,
    market_close_min: int = 45,
    polling_interval_s: int = 600,
) -> FreshnessResult:
    """
    Klasifikasi kesegaran data.

    `fetched_at` = waktu kita mengambil data (UTC). Delay = fetched_at - as_of.
    `as_of` = stempel waktu data itu sendiri (WIB, dari sumber).

    Aturan (PRD 4.4):
    - fetched_at None → UNKNOWN
    - bursa tidak aktif (tutup, akhir pekan, pre-open) → EOD
    - bursa aktif: delay < 2m → REALTIME; ≤ 60m → DELAYED; > 60m → STALE
    - `market_state` hanya dipakai bila merupakan state IDX valid
      (Yahoo mengirim state berbasis jam AS → diabaikan).
    """
    if fetched_at is None:
        return FreshnessResult(
            label=DataFreshness.UNKNOWN,
            freshness_pct=0.0,
            as_of_wib="—",
            delay_minutes=0,
            source=source,
            market_state=market_state or "UNKNOWN",
        )

    now_wib = fetched_at.astimezone(_WIB)
    as_of_dt = _parse_as_of(as_of)

    delay_s = max(0.0, (now_wib - as_of_dt).total_seconds())
    delay_min = int(delay_s / 60)

    stale_threshold_s = 60 * 60
    freshness_pct = max(0.0, min(100.0, 100.0 * (1.0 - delay_s / stale_threshold_s)))

    # State bursa diturunkan dari MOMEN DATA (as_of), bukan momen fetch.
    # Contoh: data close Jumat yang di-fetch Senin pagi tetap "EOD" — itu
    # snapshot akhir sesi, bukan data live yang basi. Lihat docs/DATA_SOURCE_DISCOVERY.md.
    given = (market_state or "").strip().upper()
    if given in _IDX_STATES:
        state = given
    else:
        state = _derive_idx_state(
            as_of_dt,
            market_open_h,
            market_open_min,
            market_close_h,
            market_close_min,
        )

    if state != "OPEN":
        # Sesi bursa sudah tutup saat data diambil → EOD. Delay tetap
        # dilaporkan lewat delay_minutes supaya UI jujur soal umur data.
        label = DataFreshness.END_OF_DAY
    elif delay_min < 2:
        label = DataFreshness.REALTIME
    elif delay_min <= 60:
        # 60 menit = DELAYED, bukan STALE (STALE = > 60 menit, bursa aktif)
        label = DataFreshness.DELAYED
    else:
        label = DataFreshness.STALE

    return FreshnessResult(
        label=label,
        freshness_pct=round(freshness_pct, 1),
        as_of_wib=as_of_dt.strftime("%d %b %Y %H:%M"),
        delay_minutes=delay_min,
        source=source,
        market_state=state,
    )


# ── Schema Pydantic untuk /api/health ────────────────────────────────

def build_source_health(
    source: str,
    fetched_at: datetime | None,
    status: SourceHealth,
    records_count: int = 0,
    error_msg: str | None = None,
) -> dict:
    """Buat objek health untuk response /api/health."""
    return {
        "source": source,
        "status": status.value,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "records_count": records_count,
        "error_msg": error_msg,
    }
