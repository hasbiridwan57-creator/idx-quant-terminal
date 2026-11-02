"""
Konfigurasi database — sadar driver (SQLite untuk lokal, Postgres untuk deploy).

KENAPA INI ADA:
Deploy ke Railway/Neon butuh Postgres: filesystem Railway bersifat ephemeral,
jadi SQLite 160 MB hilang setiap redeploy. Pengembangan lokal tetap memakai
SQLite (cepat, tanpa server). Modul ini mendeteksi driver dari URL dan hanya
menjalankan perintah yang relevan.

Yang BERBEDA antar driver:
  1. PRAGMA journal_mode / synchronous  -> khusus SQLite, Postgres error.
  2. connect_args check_same_thread     -> khusus SQLite.
  3. sqlite_master / PRAGMA table_info  -> Postgres pakai information_schema.
  4. Pooling                            -> Postgres butuh pool_pre_ping supaya
     koneksi yang diputus Neon (idle timeout) tidak membuat request 500.
  5. Tipe REAL                          -> Postgres pakai DOUBLE PRECISION.

URL dari env var IDX_DB_URL. Contoh:
  sqlite:////Users/hasbi/idx-quant-terminal/idx_quant_cache.db   (lokal)
  postgresql+psycopg://user:pass@host/dbname?sslmode=require      (Neon)
"""

import os
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import event, text

BASE_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv(
    "IDX_DB_URL", f"sqlite:///{BASE_DIR / 'idx_quant_cache.db'}"
)

# Nama lama dipertahankan: modul lain mengimpor SQLITE_URL.
SQLITE_URL = DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# ── Engine ────────────────────────────────────────────────────────────────
if IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

else:
    # Postgres (Neon): serverless Postgres memutus koneksi idle. Tanpa
    # pool_pre_ping, request pertama setelah jeda gagal dengan
    # "server closed the connection unexpectedly".
    # pool_recycle < idle timeout Neon (default 5 menit) sebagai jaring aman.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=280,
        pool_size=5,
        max_overflow=5,
        future=True,
    )


def _table_exists(conn, table: str) -> bool:
    """Cek keberadaan tabel tanpa mengasumsikan driver."""
    if IS_SQLITE:
        r = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
        return r.fetchone() is not None
    r = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": table},
    )
    return r.fetchone() is not None


def _existing_columns(conn, table: str):
    """Daftar kolom tabel tanpa mengasumsikan driver."""
    if IS_SQLITE:
        r = conn.execute(text(f"PRAGMA table_info({table})"))
        return {row[1] for row in r.fetchall()}
    r = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": table},
    )
    return {row[0] for row in r.fetchall()}


def _migrate_schema_add_columns(engine_ref) -> None:
    """
    Tambah kolom yang belum ada (v3.0 -> v4.0).

    Berlaku untuk SQLite MAUPUN Postgres. Dulu blok ini SQLite-only sehingga
    database Postgres baru akan kehilangan 24 kolom dan seluruh valuasi gagal
    tanpa pesan yang jelas.
    """
    new_cols = [
        ("sector",                  "TEXT"),
        ("shares_outstanding",       "REAL"),
        ("cash_and_equivalents",     "REAL"),
        ("interest_bearing_debt",    "REAL"),
        ("current_assets",           "REAL"),
        ("current_liabilities",      "REAL"),
        ("interest_income",          "REAL"),
        ("interest_expense",         "REAL"),
        ("tax_provision",            "REAL"),
        ("operating_cash_flow",      "REAL"),
        ("capex",                    "REAL"),
        ("depreciation",             "REAL"),
        ("minority_interest",        "REAL"),
        ("pe_trailing",              "REAL"),
        ("pb_ratio",                 "REAL"),
        ("dividend_yield",           "REAL"),
        # Detail modal kerja & arus kas — field ini selalu ada di JSONL XBRL
        # tetapi lama tidak dipetakan, membuat CCC/DPR/AQI kehilangan input.
        ("inventories",              "REAL"),
        ("trade_receivables",        "REAL"),
        ("trade_payables",           "REAL"),
        ("finance_costs",            "REAL"),
        ("dividends_paid",           "REAL"),
        ("retained_earnings",        "REAL"),
        ("loans_gross",              "REAL"),
    ]

    table = "financialstatementcache"
    with engine_ref.connect() as conn:
        if not _table_exists(conn, table):
            return  # create_all akan membuatnya lengkap

        existing = _existing_columns(conn, table)
        # Postgres tidak mengenal REAL -> DOUBLE PRECISION.
        real_type = "REAL" if IS_SQLITE else "DOUBLE PRECISION"

        for col_name, col_type in new_cols:
            if col_name in existing:
                continue
            sql_type = real_type if col_type == "REAL" else col_type
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col_name} {sql_type}")
                )
                conn.commit()
                print(f"  ✓ Migrated: Added column '{col_name}' to {table}")
            except Exception as e:
                print(f"  ⚠ Migration skipped for '{col_name}': {e}")


def init_db() -> None:
    # Import all models explicitly to register with SQLModel.metadata
    from app.db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    # Auto-migrate existing DB (v3.0 → v4.0)
    _migrate_schema_add_columns(engine)


def get_session():
    with Session(engine) as session:
        yield session
