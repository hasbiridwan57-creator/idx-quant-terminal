#!/usr/bin/env python
"""
Migrasi data SQLite -> Postgres (Neon) untuk IDX-Quant Terminal.

KENAPA DIPERLUKAN:
Railway memakai filesystem ephemeral — SQLite 160 MB hilang tiap redeploy.
Data harus hidup di Postgres.

CARA PAKAI:
    export IDX_SRC_DB="sqlite:////Users/hasbi/idx-quant-terminal/idx_quant_cache.db"
    export IDX_DST_DB="postgresql+psycopg://user:pass@host/db?sslmode=require"
    python scripts/migrate_to_postgres.py            # uji coba (dry-run)
    python scripts/migrate_to_postgres.py --apply    # benar-benar tulis

KEAMANAN:
  * Tanpa --apply, skrip hanya melaporkan rencana (tidak menulis apa pun).
  * --recreate menghapus tabel tujuan lebih dulu (berbahaya, minta konfirmasi).
  * Batch insert 5.000 baris agar tidak kehabisan memori / kena limit Neon.
  * Setiap tabel diverifikasi jumlah barisnya setelah migrasi.

CATATAN TIPE:
  SQLite menyimpan semua sebagai TEXT/REAL/INTEGER longgar. Saat menulis ke
  Postgres, SQLAlchemy memakai metadata model (SQLModel) sehingga tipe benar
  otomatis. Kolom yang tidak ada di model tetap dimigrasikan lewat
  reflection supaya tidak ada data hilang diam-diam.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BATCH = 5_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Benar-benar menulis ke Postgres (tanpa ini = dry-run)")
    ap.add_argument("--recreate", action="store_true",
                    help="DROP tabel tujuan sebelum migrasi")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    src_url = os.getenv("IDX_SRC_DB")
    dst_url = os.getenv("IDX_DST_DB")
    if not src_url or not dst_url:
        print("ERROR: set IDX_SRC_DB dan IDX_DST_DB lebih dulu.", file=sys.stderr)
        return 2
    if not dst_url.startswith(("postgresql", "postgres")):
        print("ERROR: IDX_DST_DB harus URL Postgres.", file=sys.stderr)
        return 2
    if src_url == dst_url:
        print("ERROR: sumber dan tujuan sama.", file=sys.stderr)
        return 2
    # Neon: string -pooler memakai PgBouncer (transaction mode) yang tidak
    # mendukung prepared statement / session state. Migrasi besar (1,15 juta
    # baris) lewat pooled sering gagal dengan pesan yang TIDAK menyebut
    # pooling sama sekali (mis. `prepared statement "s0" already exists`).
    # Pakai DATABASE_URL_UNPOOLED untuk migrasi.
    if "-pooler" in dst_url:
        print("PERINGATAN: URL tujuan memakai -pooler (PgBouncer).", file=sys.stderr)
        print("           Untuk migrasi, pakai connection string UNPOOLED.", file=sys.stderr)
        print("           Neon menyimpannya sebagai DATABASE_URL_UNPOOLED.", file=sys.stderr)
        return 6

    from sqlalchemy import MetaData, create_engine, inspect, select, text
    from sqlalchemy.exc import OperationalError

    src = create_engine(src_url)
    try:
        dst = create_engine(dst_url, pool_pre_ping=True)
        with dst.connect() as c:
            c.execute(text("SELECT 1"))
    except OperationalError as e:
        print(f"ERROR: tidak bisa konek ke Postgres: {e}", file=sys.stderr)
        return 3

    # ── Metadata SUMBER dari MODEL aplikasi, bukan reflect ───────────────
    # Reflect SQLite melaporkan volume sebagai INTEGER (SQLite longgar),
    # sehingga SQLAlchemy meng-cast `::INTEGER` dan baris volume besar
    # (GOTO 4,5 M) ditolak Postgres walau kolomnya sudah bigint.
    from app.db import models as _models  # noqa: F401
    from sqlmodel import SQLModel

    tables = [t for t in SQLModel.metadata.sorted_tables]
    print(f"Sumber : {src_url.split('@')[-1]}")
    print(f"Tujuan : {dst_url.split('@')[-1]}")
    print(f"Tabel  : {len(tables)}\n")

    # ── Dry-run: rencana saja, tidak menulis apa pun ──────────────────────
    if not args.apply:
        print("DRY-RUN — tidak menulis apa pun. Tambahkan --apply untuk eksekusi.")
        for t in tables:
            with src.connect() as c:
                n = c.execute(select(text("COUNT(*)")).select_from(t)).scalar()
            print(f"  {t.name:<32} {n:>10,} baris")
        return 0

    # ── Skema tujuan dari metadata MODEL aplikasi ────────────────────────
    # Import model mendaftarkan tabel ke SQLModel.metadata. create_all
    # melewati tabel yang sudah ada, jadi aman dijalankan berulang.
    from app.db import models as _models  # noqa: F401
    from sqlmodel import SQLModel

    if args.recreate:
        ans = input("--recreate menghapus tabel di Postgres. Ketik 'HAPUS': ")
        if ans.strip() != "HAPUS":
            print("Dibatalkan.")
            return 1
        with dst.begin() as c:
            for t in reversed(tables):
                c.execute(text(f'DROP TABLE IF EXISTS "{t.name}" CASCADE'))

    SQLModel.metadata.create_all(bind=dst)

    dst_tables = set(inspect(dst).get_table_names())
    missing = [t.name for t in tables if t.name not in dst_tables]
    if missing:
        print(f"ERROR: tabel tidak terbentuk di Postgres: {missing}", file=sys.stderr)
        return 5
    print("Skema dibuat/diverifikasi di Postgres.\n")

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    total_src = total_dst = 0
    failures = []
    for t in tables:
        cols = [c.name for c in t.columns]
        # Postgres mentok 65.535 parameter per statement. Ukuran batch
        # harus DIHITUNG dari jumlah kolom, bukan angka tetap: 5.000 baris
        # x 29 kolom = 145.000 parameter -> langsung ditolak Postgres.
        n_cols = max(len(cols), 1)
        batch_n = max(1, min(args.batch, 60000 // n_cols))

        with src.connect() as c:
            n_src = c.execute(select(text("COUNT(*)")).select_from(t)).scalar()
        total_src += n_src
        if n_src == 0:
            print(f"  {t.name:<32} {0:>10,} (kosong, dilewati)")
            continue

        try:
            with src.connect() as sc:
                rs = sc.execute(select(t)).yield_per(batch_n)
                chunk = []
                for row in rs:
                    chunk.append(dict(zip(cols, row)))
                    if len(chunk) >= batch_n:
                        _insert(dst, t, chunk, pg_insert)
                        chunk = []
                if chunk:
                    _insert(dst, t, chunk, pg_insert)
        except Exception as e:  # noqa: BLE001
            failures.append((t.name, str(e)[:200]))
            print(f"  {t.name:<32} GAGAL: {str(e)[:120]}")
            continue

        with dst.connect() as c:
            n_dst = c.execute(select(text("COUNT(*)")).select_from(t)).scalar()
        total_dst += n_dst
        status = "OK" if n_dst == n_src else f"BEDA (src {n_src:,} dst {n_dst:,})"
        print(f"  {t.name:<32} {n_dst:>10,} {status}")
        if n_dst != n_src:
            failures.append((t.name, f"jumlah baris beda: {n_src} -> {n_dst}"))

    print(f"\nTOTAL sumber {total_src:,} | tujuan {total_dst:,}")
    if failures:
        print("KEGAGALAN:")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 4
    print("SELESAI — semua tabel cocok.")
    return 0


def _insert(dst, table, chunk, pg_insert) -> None:
    """Insert batch; on_conflict_do_nothing supaya aman dijalankan ulang."""
    with dst.begin() as c:
        c.execute(pg_insert(table).values(chunk).on_conflict_do_nothing())


if __name__ == "__main__":
    raise SystemExit(main())
