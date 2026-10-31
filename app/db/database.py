import os
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import event, text

BASE_DIR = Path(__file__).resolve().parents[2]
SQLITE_URL = os.getenv("IDX_DB_URL", f"sqlite:///{BASE_DIR / 'idx_quant_cache.db'}")

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


def _migrate_schema_add_columns(engine_ref) -> None:
    """Add missing columns to FinancialStatementCache if DB already exists (v3.0 -> v4.0 migration)."""
    new_cols = [
        ("sector",                  "TEXT"),
        ("shares_outstanding",       "REAL"),
        ("cash_and_equivalents",     "REAL"),
        ("interest_bearing_debt",    "REAL"),
        ("current_assets",           "REAL"),
        ("current_liabilities",       "REAL"),
        ("interest_income",          "REAL"),
        ("interest_expense",         "REAL"),
        ("tax_provision",           "REAL"),
        ("operating_cash_flow",     "REAL"),
        ("capex",                    "REAL"),
        ("depreciation",             "REAL"),
        ("minority_interest",        "REAL"),
        ("pe_trailing",             "REAL"),
        ("pb_ratio",                "REAL"),
        ("dividend_yield",          "REAL"),
        # Detail modal kerja & arus kas — field ini selalu ada di JSONL XBRL
        # tetapi lama tidak dipetakan, membuat CCC/DPR/AQI kehilangan input.
        ("inventories",             "REAL"),
        ("trade_receivables",       "REAL"),
        ("trade_payables",          "REAL"),
        ("finance_costs",           "REAL"),
        ("dividends_paid",          "REAL"),
        ("retained_earnings",       "REAL"),
        ("loans_gross",             "REAL"),
    ]

    with engine_ref.connect() as conn:
        # Check if table exists
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='financialstatementcache'"))
        table_exists = result.fetchone() is not None
        if not table_exists:
            return  # create_all will handle it

        # Get existing columns
        result = conn.execute(text("PRAGMA table_info(financialstatementcache)"))
        existing_cols = {row[1] for row in result.fetchall()}

        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                try:
                    conn.execute(text(f"ALTER TABLE financialstatementcache ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                    print(f"  ✓ Migrated: Added column '{col_name}' to financialstatementcache")
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