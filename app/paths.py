"""
Resolver path data — supaya aplikasi tidak bergantung pada path absolut macOS.

KENAPA INI ADA:
Dulu path data ditulis mati seperti
    /Users/hasbi/laporan/bei_full/parsed/xbrl_audited_metrics.jsonl
Di Railway path itu tidak ada, sehingga SINYALISASI BERHENTI: semua emiten
tampil tanpa data dan error-nya senyap (except: ...). Deploy jadi "hidup
tapi kosong" — lebih buruk daripada gagal terang-terangan.

URUTAN PENCARIAN (pertama yang ada dipakai):
  1. Env var eksplisit (IDX_XBRL_JSONL, IDX_SEGMENTS_JSONL) — untuk server.
  2. Path repo: <repo>/data/xbrl_audited_metrics.jsonl — untuk deploy,
     file ikut di-commit / di-upload.
  3. Path lokal pengembangan: ~/laporan/bei_full/parsed/... dan
     ~/idx-quant-terminal/...

Kalau semua tidak ada, fungsi mengembalikan None dan pemanggil WAJIB
memunculkan status "data tidak tersedia" ke UI, bukan diam-diam kosong.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root = dua level di atas app/services/.
# paths.py ada di <root>/app/paths.py -> parents[0]=app, [1]=<root>.
# Sebelumnya parents[2] dipakai dan hasilnya "/" di container (/app/app/paths.py?),
# sehingga data/ dicari di /data dan SEMUA data XBRL hilang tanpa error.
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_DATA = REPO_ROOT / "data"

HOME = Path.home()


def _first_existing(candidates):
    for p in candidates:
        if p and Path(p).exists():
            return str(p)
    return None


def _env_path(name: str):
    """Nilai env var sebagai Path, atau None kalau tidak diset."""
    v = os.getenv(name)
    return Path(v) if v else None


def xbrl_jsonl() -> str | None:
    """Sumber utama: metrik XBRL audited BEI (per emiten per tahun)."""
    return _first_existing([
        os.getenv("IDX_XBRL_JSONL"),
        REPO_DATA / "xbrl_audited_metrics.jsonl",
        HOME / "laporan/bei_full/parsed/xbrl_audited_metrics.jsonl",
        HOME / "idx-quant-terminal/data/xbrl_audited_metrics.jsonl",
    ])


def segments_jsonl() -> str | None:
    """Revenue by type (segmentasi pendapatan per segmen usaha)."""
    return _first_existing([
        os.getenv("IDX_SEGMENTS_JSONL"),
        REPO_DATA / "revenue_by_type.jsonl",
        HOME / "laporan/bei_full/parsed/revenue_by_type.jsonl",
    ])


def repo_data(filename: str) -> str | None:
    """File JSON pendukung di folder data/ (governance, profiles, dll)."""
    return _first_existing([
        os.getenv("IDX_DATA_DIR") and Path(os.getenv("IDX_DATA_DIR")) / filename,
        REPO_DATA / filename,
        HOME / "idx-quant-terminal/data" / filename,
    ])


def env_file() -> str | None:
    """File .env — di server variabel datang dari environment, bukan .env."""
    return _first_existing([
        os.getenv("IDX_ENV_FILE"),
        REPO_ROOT / ".env",
        HOME / "idx-quant-terminal/.env",
    ])
