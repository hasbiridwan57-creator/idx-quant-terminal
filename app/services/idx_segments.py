"""Loader segmentasi pendapatan (revenue by type) dari XLSX audited IDX/BEI.

Sumber: sheet `1617000` (Notes for revenue by type) pada file
`TICKER-YYYY-Audit-xlsx.xlsx`.

CATATAN SATUAN: satuan nilai pada XLSX IDX **bervariasi antar emiten**
(ada yang juta rupiah, ada yang rupiah penuh). Karena itu:
  - `share_pct` (rasio terhadap subtotal "Tipe pendapatan") bersifat
    bebas satuan -> dipakai sebagai ground truth.
  - `revenue_raw` disimpan apa adanya (nilai mentahan dari filing).
  - Nilai dalam **miliar rupiah** TIDAK dihitung di sini; normalisasi
    dilakukan di consumer dengan memakai total revenue audited (XBRL)
    sebagai pembanding.

ZERO FAKE: bila emiten tidak punya breakdown produk/jasa, kembalikan list
kosong. Jangan mengarang pembagian segmen.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

_JSONL = "/Users/hasbi/laporan/bei_full/parsed/revenue_by_type.jsonl"

_lock = threading.Lock()
_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _load() -> Dict[str, Dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        data: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(_JSONL):
            with open(_JSONL, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    tk = str(rec.get("ticker") or "").upper()
                    if not tk:
                        continue
                    data[tk] = rec
        _cache = data
        return _cache


def available() -> bool:
    return bool(_load())


def has_ticker(ticker: str) -> bool:
    return str(ticker or "").upper() in _load()


def segments(ticker: str) -> List[Dict[str, Any]]:
    """Kembalikan list segmen [{segment, revenue_raw, share_pct, growth_yoy}] urut share desc."""
    rec = _load().get(str(ticker or "").upper())
    if not rec:
        return []
    segs = rec.get("segments") or []
    out: List[Dict[str, Any]] = []
    for s in segs:
        label = str(s.get("segment") or "").strip()
        if not label:
            continue
        out.append({
            "segment": label,
            "revenue_raw": s.get("revenue_raw"),
            "share_pct": s.get("share_pct"),
            "growth_yoy": s.get("growth_yoy"),
        })
    out.sort(key=lambda r: (r.get("share_pct") or 0.0), reverse=True)
    return out


def latest_year(ticker: str) -> Optional[int]:
    rec = _load().get(str(ticker or "").upper())
    if not rec:
        return None
    try:
        return int(rec.get("year"))
    except Exception:
        return None
