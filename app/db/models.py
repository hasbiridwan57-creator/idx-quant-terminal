from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field

# ── Legacy Model (v2.2) ────────────────────────────────────────────────
class FinancialStatementCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("ticker", "year", "period_type", name="uq_ticker_year_period"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    file_hash: str = Field(index=True, unique=True)
    ticker: str = Field(index=True)
    company_name: str
    year: int = Field(index=True)
    period_type: str = Field(default="FY")
    currency: str = Field(default="IDR")
    unit_multiplier: float = Field(default=1.0)

    revenue: float
    ebit: float
    ebt: float
    net_income_parent: float

    total_assets: float
    total_liabilities: float
    total_equity_parent: float
    total_equity_consolidated: Optional[float] = None

    # ── NEW: Phase 1 Fields (v4.0) ──────────────────────────────────────
    sector: Optional[str] = Field(default=None, index=True)
    shares_outstanding: Optional[float] = Field(default=None)
    cash_and_equivalents: Optional[float] = Field(default=None)
    interest_bearing_debt: Optional[float] = Field(default=None)
    current_assets: Optional[float] = Field(default=None)
    current_liabilities: Optional[float] = Field(default=None)
    interest_income: Optional[float] = Field(default=None)
    interest_expense: Optional[float] = Field(default=None)
    tax_provision: Optional[float] = Field(default=None)
    operating_cash_flow: Optional[float] = Field(default=None)
    capex: Optional[float] = Field(default=None)
    depreciation: Optional[float] = Field(default=None)
    minority_interest: Optional[float] = Field(default=None)

    # ── Extended metadata ──────────────────────────────────────────────
    pe_trailing: Optional[float] = Field(default=None)
    pb_ratio: Optional[float] = Field(default=None)
    dividend_yield: Optional[float] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── New Models for Phase 1 & 2 (v3.0) ───────────────────────────────────

class Symbol(SQLModel, table=True):
    """Seluruh emiten BEI aktif/nonaktif."""
    ticker: str = Field(primary_key=True, index=True)
    name: str
    sector: Optional[str] = Field(default=None, index=True)
    subsector: Optional[str] = None
    board: Optional[str] = None  # UTAMA, PENGEMBANGAN, AKSELERASI
    is_active: bool = Field(default=True, index=True)
    listing_date: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QuoteLatest(SQLModel, table=True):
    """Snapshot harga terkini per emiten."""
    ticker: str = Field(primary_key=True, index=True)
    price: float
    change: float
    change_pct: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    volume_lot: Optional[int] = None
    value_idr: Optional[float] = None
    market_cap: Optional[float] = None
    pe_trailing: Optional[float] = None
    pb: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    as_of: Optional[str] = None
    source: str = Field(default="yfinance")
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QuoteHistoryDaily(SQLModel, table=True):
    """OHLCV harian untuk analisis teknikal & kalkulasi S/R."""
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IndexQuote(SQLModel, table=True):
    """Snapshot nilai indeks komposit & sektoral."""
    symbol: str = Field(primary_key=True, index=True)  # ^JKSE, IDX30, LQ45
    name: str
    price: float
    change: float
    change_pct: float
    high: Optional[float] = None
    low: Optional[float] = None
    as_of: Optional[str] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ForeignFlowDaily(SQLModel, table=True):
    """Arus dana investor asing harian per emiten."""
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_flow_ticker_date"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: str = Field(index=True)
    net_foreign_rg_bn: float
    net_foreign_ng_bn: float = 0.0
    source: str = Field(default="MANUAL")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderCallLog(SQLModel, table=True):
    """Audit log panggilan provider (tanpa rahasia/keys)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str
    endpoint: str
    status_code: int
    latency_ms: float
    records_count: int = 0
    error_msg: Optional[str] = None
    called_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketSnapshot(SQLModel, table=True):
    """Snapshot terminal yang dipersistensikan ke database."""
    id: Optional[int] = Field(default=None, primary_key=True)
    trading_date: str = Field(index=True)
    ihsg_last: float
    change_pts: float
    change_pct: float
    total_value_bn: float
    net_foreign_rg_bn: float
    market_status: str
    headline: str
    payload_json: str  # JSON dump lengkap dari TerminalPayload
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
