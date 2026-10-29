import hashlib
import io
import json
import re
from typing import Dict, List, Optional, Tuple
import pandas as pd
import pdfplumber
from sqlmodel import Session, select
from app.db.models import FinancialStatementCache
from app.services.dupont_engine import FinancialStatementInput, PeriodType

# Pos neraca (total_*) HANYA dicocokkan persis setelah normalisasi
EXACT_ONLY_KEYS = {
    "total_assets", "total_liabilities", "total_equity_parent", "total_equity_consolidated",
}
ACCOUNT_SYNONYMS: Dict[str, List[str]] = {
    "revenue": [
        "pendapatan bersih", "penjualan bersih", "pendapatan usaha",
        "revenue", "net revenue", "net sales", "total pendapatan",
    ],
    "ebit": [
        "laba usaha", "laba operasional", "operating profit",
        "operating income", "ebit", "laba sebelum bunga dan pajak",
    ],
    "ebt": [
        "laba sebelum pajak", "laba sebelum beban pajak penghasilan",
        "profit before tax", "income before tax", "ebt",
    ],
    "net_income_parent": [
        "laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk",
        "laba periode berjalan yang dapat diatribusikan kepada pemilik entitas induk",
        "profit attributable to owners of the parent",
        "net income attributable to parent", "laba bersih entitas induk", "net_income_parent",
    ],
    "total_assets": [
        "jumlah aset", "total aset", "jumlah aktiva", "total assets", "total_assets",
    ],
    "total_liabilities": [
        "jumlah liabilitas", "total liabilitas", "jumlah kewajiban", "total kewajiban",
        "total liabilities", "total_liabilities",
    ],
    "total_equity_parent": [
        "jumlah ekuitas yang dapat diatribusikan kepada pemilik entitas induk",
        "ekuitas yang dapat diatribusikan kepada pemilik entitas induk",
        "ekuitas entitas induk",
        "equity attributable to owners of the parent",
        "total equity attributable to owners of the parent",
        "total_equity_parent",
    ],
    "total_equity_consolidated": [
        "jumlah ekuitas", "total ekuitas", "total equity", "total_equity_consolidated",
    ],
    # ── Extended Fields (v4.0): Opsional, tidak wajib ada di file lama ──
    "sector": ["sektor", "sector", "industri", "industry"],
    "shares_outstanding": ["jumlah lembar saham", "jumlah saham beredar", "shares outstanding",
                           "ordinary shares number", "share issued"],
    "cash_and_equivalents": ["kas dan setara kas", "cash and cash equivalents",
                             "cash cash equivalents and short term investments"],
    "interest_bearing_debt": ["utang berbunga", "total debt", "long term debt",
                             "interest bearing debt"],
    "current_assets": ["aset lancar", "current assets"],
    "current_liabilities": ["liabilitas jangka pendek", "current liabilities"],
    "interest_income": ["pendapatan bunga", "interest income", "net interest income"],
    "interest_expense": ["beban bunga", "interest expense"],
    "tax_provision": ["beban pajak", "tax provision", "income tax expense"],
    "operating_cash_flow": ["arus kas aktivitas operasional", "operating cash flow",
                            "cash flow from continuing operating activities"],
    "capex": ["pengeluaran modal", "capital expenditure", "purchase of ppe"],
    "depreciation": ["depresiasi", "depreciation and amortization", "reconciled depreciation"],
    "minority_interest": ["kepentingan non-pengendali", "minority interest",
                          "non-controlling interest"],
}
NOT_ALLOWED_FRAGMENTS = ("ebitda", "per saham", "non-pengendali", "non pengendali", "nonpengendali")
_EXACT_LOOKUP: Dict[str, str] = {
    syn: key for key, syns in ACCOUNT_SYNONYMS.items() for syn in syns
}

def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def _label_candidates(raw_label: str) -> List[str]:
    text = re.sub(r"\s+", " ", str(raw_label).strip().lower()).rstrip(":").strip()
    parts = [text]
    # Label dwibahasa: "Jumlah aset / Total assets" atau "Jumlah aset (Total assets)".
    # Pisahkan pada "/" dan kurung/braket — bukan pada parens mentah (re.error unbalanced parenthesis).
    normalized = re.sub(r"[/()\[\]]", " | ", text)
    for piece in normalized.split("|"):
        piece = re.sub(r"\s+", " ", piece).strip()
        if piece and piece != text:
            parts.append(piece)
    return parts

def _match_account_key(raw_label: str) -> Optional[str]:
    candidates = _label_candidates(raw_label)
    for cand in candidates:
        if cand in _EXACT_LOOKUP:
            return _EXACT_LOOKUP[cand]
    for cand in candidates:
        if any(frag in cand for frag in NOT_ALLOWED_FRAGMENTS):
            continue
        for key, syns in ACCOUNT_SYNONYMS.items():
            if key in EXACT_ONLY_KEYS:
                continue
            for syn in syns:
                if len(syn) >= 8 and re.search(rf"(?<!\w){re.escape(syn)}(?!\w)", cand):
                    return key
    return None

def parse_idx_file_bytes(
    filename: str,
    file_bytes: bytes,
    default_ticker: str = "XXXX",
    default_year: int = 2025,
) -> FinancialStatementInput:
    lower_name = filename.lower()
    if lower_name.endswith(".json"):
        data = json.loads(file_bytes.decode("utf-8"))
        return FinancialStatementInput(**data)

    extracted: Dict[str, float] = {}
    meta: Dict[str, str] = {
        "ticker": default_ticker.upper(),
        "company_name": f"Emiten {default_ticker.upper()} Tbk",
        "year": str(default_year),
        "period_type": "FY",
    }

    if lower_name.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        for sheet in xls.sheet_names:
            df = xls.parse(sheet, header=None).dropna(how="all")
            for _, row in df.iterrows():
                vals = [v for v in row.values if pd.notna(v)]
                if len(vals) >= 2:
                    label = str(vals[0]).strip()
                    if label.lower() in ("ticker", "kode saham"):
                        meta["ticker"] = str(vals[1]).strip().upper()
                    elif label.lower() in ("company_name", "nama emiten"):
                        meta["company_name"] = str(vals[1]).strip()
                    elif label.lower() in ("year", "tahun"):
                        meta["year"] = str(int(float(vals[1])))
                    elif label.lower() in ("period_type", "periode"):
                        meta["period_type"] = str(vals[1]).strip().upper()
                    else:
                        key = _match_account_key(label)
                        if key and key not in extracted:
                            try:
                                num_str = str(vals[1]).replace(",", "").replace("(", "-").replace(")", "")
                                extracted[key] = float(num_str)
                            except ValueError:
                                pass

    elif lower_name.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for table in tables:
                    for row in table:
                        clean_row = [c.strip() for c in row if c and c.strip()]
                        if len(clean_row) >= 2:
                            key = _match_account_key(clean_row[0])
                            if key and key not in extracted:
                                try:
                                    raw_num = (
                                        clean_row[-1]
                                        .replace(".", "")
                                        .replace(",", ".")
                                        .replace("(", "-")
                                        .replace(")", "")
                                    )
                                    extracted[key] = float(raw_num)
                                except ValueError:
                                    pass
    else:
        raise ValueError("Format file tidak didukung. Gunakan .xlsx, .pdf, atau .json")

    if "total_equity_parent" not in extracted and "total_equity_consolidated" in extracted:
        extracted["total_equity_parent"] = extracted["total_equity_consolidated"]

    required_keys = [
        "revenue", "ebit", "ebt", "net_income_parent",
        "total_assets", "total_liabilities", "total_equity_parent",
    ]
    missing = [k for k in required_keys if k not in extracted]
    if missing:
        raise ValueError(f"Pos laporan keuangan belum lengkap di file: {', '.join(missing)}")

    return FinancialStatementInput(
        ticker=meta["ticker"],
        company_name=meta["company_name"],
        year=int(meta["year"]),
        period_type=PeriodType(meta["period_type"]),
        revenue=extracted["revenue"],
        ebit=extracted["ebit"],
        ebt=extracted["ebt"],
        net_income_parent=extracted["net_income_parent"],
        total_assets=extracted["total_assets"],
        total_liabilities=extracted["total_liabilities"],
        total_equity_parent=extracted["total_equity_parent"],
        total_equity_consolidated=extracted.get("total_equity_consolidated"),
    )

def save_or_get_cached_statement(
    session: Session, stmt: FinancialStatementInput, raw_bytes: Optional[bytes] = None
) -> FinancialStatementCache:
    if raw_bytes is None:
        raw_bytes = stmt.model_dump_json().encode("utf-8")
    f_hash = compute_sha256(raw_bytes)

    existing = session.exec(
        select(FinancialStatementCache).where(FinancialStatementCache.file_hash == f_hash)
    ).first()
    if existing:
        return existing

    values = dict(
        file_hash=f_hash,
        company_name=stmt.company_name,
        currency=stmt.currency,
        unit_multiplier=stmt.unit_multiplier,
        revenue=stmt.revenue,
        ebit=stmt.ebit,
        ebt=stmt.ebt,
        net_income_parent=stmt.net_income_parent,
        total_assets=stmt.total_assets,
        total_liabilities=stmt.total_liabilities,
        total_equity_parent=stmt.total_equity_parent,
        total_equity_consolidated=stmt.total_equity_consolidated,
        # Extended fields (v4.0)
        sector=stmt.sector,
        shares_outstanding=stmt.shares_outstanding,
        cash_and_equivalents=stmt.cash_and_equivalents,
        interest_bearing_debt=stmt.interest_bearing_debt,
        current_assets=stmt.current_assets,
        current_liabilities=stmt.current_liabilities,
        interest_income=stmt.interest_income,
        interest_expense=stmt.interest_expense,
        tax_provision=stmt.tax_provision,
        operating_cash_flow=stmt.operating_cash_flow,
        capex=stmt.capex,
        depreciation=stmt.depreciation,
        minority_interest=stmt.minority_interest,
    )
    same_period = session.exec(
        select(FinancialStatementCache).where(
            FinancialStatementCache.ticker == stmt.ticker.upper(),
            FinancialStatementCache.year == stmt.year,
            FinancialStatementCache.period_type == stmt.period_type.value,
        )
    ).first()
    if same_period:
        for k, v in values.items():
            setattr(same_period, k, v)
        record = same_period
    else:
        record = FinancialStatementCache(
            ticker=stmt.ticker.upper(),
            year=stmt.year,
            period_type=stmt.period_type.value,
            **values,
        )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record

def seed_initial_idx_statements(session: Session) -> None:
    """Seed data lengkap 4 emiten non-bank + 1 bank (BBCA) dengan seluruh 15 field extended."""
    samples = [
        # ── ASII 2024 & 2025 (Industrials) ──────────────────────────
        FinancialStatementInput(
            ticker="ASII", company_name="PT Astra International Tbk", year=2024, period_type=PeriodType.FY,
            revenue=316565, ebit=44200, ebt=42800, net_income_parent=33839,
            total_assets=445679, total_liabilities=195261, total_equity_parent=250418,
            unit_multiplier=1e9,
            sector="Industrials",
            shares_outstanding=40483553140.0,
            cash_and_equivalents=42000.0,
            interest_bearing_debt=62000.0,
            current_assets=118000.0,
            current_liabilities=89000.0,
            interest_income=1800.0,
            interest_expense=5600.0,
            tax_provision=8970.0,
            operating_cash_flow=52000.0,
            capex=18000.0,
            depreciation=11200.0,
            minority_interest=7800.0,
        ),
        FinancialStatementInput(
            ticker="ASII", company_name="PT Astra International Tbk", year=2025, period_type=PeriodType.FY,
            revenue=338400, ebit=50760, ebt=49100, net_income_parent=38789,
            total_assets=462000, total_liabilities=198000, total_equity_parent=264000,
            unit_multiplier=1e9,
            sector="Industrials",
            shares_outstanding=40483553140.0,
            cash_and_equivalents=48000.0,
            interest_bearing_debt=65000.0,
            current_assets=125000.0,
            current_liabilities=92000.0,
            interest_income=2200.0,
            interest_expense=5200.0,
            tax_provision=10320.0,
            operating_cash_flow=58000.0,
            capex=19000.0,
            depreciation=11800.0,
            minority_interest=8200.0,
        ),
        # ── ICBP 2024 & 2025 (Consumer Non-Cyclicals) ────────────────
        FinancialStatementInput(
            ticker="ICBP", company_name="PT Indofood CBP Sukses Makmur Tbk", year=2024, period_type=PeriodType.FY,
            revenue=67910, ebit=14260, ebt=11900, net_income_parent=8950,
            total_assets=119200, total_liabilities=57100, total_equity_parent=62100,
            unit_multiplier=1e9,
            sector="Consumer Non-Cyclicals",
            shares_outstanding=11661908000.0,
            cash_and_equivalents=9500.0,
            interest_bearing_debt=28000.0,
            current_assets=42000.0,
            current_liabilities=31000.0,
            interest_income=420.0,
            interest_expense=2360.0,
            tax_provision=2950.0,
            operating_cash_flow=13500.0,
            capex=6200.0,
            depreciation=4800.0,
            minority_interest=4500.0,
        ),
        FinancialStatementInput(
            ticker="ICBP", company_name="PT Indofood CBP Sukses Makmur Tbk", year=2025, period_type=PeriodType.FY,
            revenue=72400, ebit=16652, ebt=14500, net_income_parent=11165,
            total_assets=123500, total_liabilities=56500, total_equity_parent=67000,
            unit_multiplier=1e9,
            sector="Consumer Non-Cyclicals",
            shares_outstanding=11661908000.0,
            cash_and_equivalents=11200.0,
            interest_bearing_debt=26000.0,
            current_assets=45000.0,
            current_liabilities=29500.0,
            interest_income=510.0,
            interest_expense=2152.0,
            tax_provision=3340.0,
            operating_cash_flow=15800.0,
            capex=6800.0,
            depreciation=5000.0,
            minority_interest=4700.0,
        ),
        # ── TLKM 2024 & 2025 (Communication Services) ───────────────
        FinancialStatementInput(
            ticker="TLKM", company_name="PT Telkom Indonesia (Persero) Tbk", year=2024, period_type=PeriodType.FY,
            revenue=149216, ebit=44764, ebt=40800, net_income_parent=24560,
            total_assets=287042, total_liabilities=130480, total_equity_parent=156562,
            unit_multiplier=1e9,
            sector="Communication Services",
            shares_outstanding=99062216600.0,
            cash_and_equivalents=32000.0,
            interest_bearing_debt=78000.0,
            current_assets=38000.0,
            current_liabilities=65000.0,
            interest_income=2800.0,
            interest_expense=3964.0,
            tax_provision=16240.0,
            operating_cash_flow=48000.0,
            capex=35000.0,
            depreciation=22000.0,
            minority_interest=0.0,
        ),
        FinancialStatementInput(
            ticker="TLKM", company_name="PT Telkom Indonesia (Persero) Tbk", year=2025, period_type=PeriodType.FY,
            revenue=152000, ebit=44840, ebt=39200, net_income_parent=24300,
            total_assets=335000, total_liabilities=197000, total_equity_parent=138000,
            unit_multiplier=1e9,
            sector="Communication Services",
            shares_outstanding=99062216600.0,
            cash_and_equivalents=29000.0,
            interest_bearing_debt=95000.0,
            current_assets=41000.0,
            current_liabilities=78000.0,
            interest_income=3100.0,
            interest_expense=5640.0,
            tax_provision=14900.0,
            operating_cash_flow=45000.0,
            capex=38000.0,
            depreciation=23000.0,
            minority_interest=0.0,
        ),
        # ── ADRO 2024 & 2025 (Energy) ────────────────────────────────
        FinancialStatementInput(
            ticker="ADRO", company_name="PT Alamtri Resources Indonesia Tbk", year=2024, period_type=PeriodType.FY,
            revenue=98500, ebit=31520, ebt=30900, net_income_parent=24100,
            total_assets=162000, total_liabilities=47000, total_equity_parent=115000,
            unit_multiplier=1e9,
            sector="Energy",
            shares_outstanding=30758665900.0,
            cash_and_equivalents=18000.0,
            interest_bearing_debt=32000.0,
            current_assets=42000.0,
            current_liabilities=22000.0,
            interest_income=900.0,
            interest_expense=620.0,
            tax_provision=6800.0,
            operating_cash_flow=38000.0,
            capex=15000.0,
            depreciation=9500.0,
            minority_interest=1200.0,
        ),
        FinancialStatementInput(
            ticker="ADRO", company_name="PT Alamtri Resources Indonesia Tbk", year=2025, period_type=PeriodType.FY,
            revenue=106200, ebit=36108, ebt=35400, net_income_parent=27612,
            total_assets=170000, total_liabilities=46000, total_equity_parent=124000,
            unit_multiplier=1e9,
            sector="Energy",
            shares_outstanding=30758665900.0,
            cash_and_equivalents=21000.0,
            interest_bearing_debt=30000.0,
            current_assets=48000.0,
            current_liabilities=21000.0,
            interest_income=1100.0,
            interest_expense=708.0,
            tax_provision=7788.0,
            operating_cash_flow=42000.0,
            capex=14000.0,
            depreciation=9800.0,
            minority_interest=1300.0,
        ),
        # ── BBCA 2024 & 2025 (Financials — Bank Model out-of-the-box) ──
        # Satuan Miliar Rupiah (unit_multiplier=1e9) konsisten dengan emiten lain
        # BBCA FY2024: Revenue Rp 109.9T, EBIT Rp 64.6T, NI Rp 52.6T, Aset Rp 1.765T, Ekuitas Rp 209T
        # BBCA FY2025: Revenue Rp 116.3T, EBIT Rp 69.4T, NI Rp 56.8T, Aset Rp 1.950T, Ekuitas Rp 232T
        FinancialStatementInput(
            ticker="BBCA", company_name="PT Bank Central Asia Tbk", year=2024, period_type=PeriodType.FY,
            revenue=109900.0, ebit=64600.0, ebt=75200.0, net_income_parent=52600.0,
            total_assets=1765000.0, total_liabilities=1556000.0, total_equity_parent=209000.0,
            unit_multiplier=1e9,
            sector="Financials",
            shares_outstanding=123275050000.0,
            cash_and_equivalents=312000.0,
            interest_bearing_debt=1150000.0,
            current_assets=0.0,
            current_liabilities=0.0,
            interest_income=82300.0,
            interest_expense=28400.0,
            tax_provision=22600.0,
            operating_cash_flow=95000.0,
            capex=8500.0,
            depreciation=6200.0,
            minority_interest=0.0,
        ),
        FinancialStatementInput(
            ticker="BBCA", company_name="PT Bank Central Asia Tbk", year=2025, period_type=PeriodType.FY,
            revenue=116300.0, ebit=69400.0, ebt=80700.0, net_income_parent=56800.0,
            total_assets=1950000.0, total_liabilities=1718000.0, total_equity_parent=232000.0,
            unit_multiplier=1e9,
            sector="Financials",
            shares_outstanding=123275050000.0,
            cash_and_equivalents=355000.0,
            interest_bearing_debt=1240000.0,
            current_assets=0.0,
            current_liabilities=0.0,
            interest_income=96400.0,
            interest_expense=32600.0,
            tax_provision=23900.0,
            operating_cash_flow=102000.0,
            capex=9200.0,
            depreciation=6600.0,
            minority_interest=0.0,
        ),
    ]
    for s in samples:
        save_or_get_cached_statement(session, s)

_PERIOD_RANK = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}

def load_ticker_pair(
    session: Session, ticker: str
) -> Tuple[Optional[FinancialStatementInput], Optional[FinancialStatementInput]]:
    """Periode terbaru + pembanding YoY = jenis periode sama pada tahun sebelumnya."""
    rows = session.exec(
        select(FinancialStatementCache).where(FinancialStatementCache.ticker == ticker.upper())
    ).all()
    if not rows:
        return None, None
    rows = sorted(rows, key=lambda r: (r.year, _PERIOD_RANK.get(r.period_type, 0)), reverse=True)

    def _to_input(r: FinancialStatementCache) -> FinancialStatementInput:
        period_str = str(r.period_type).strip().upper()
        try:
            ptype = PeriodType(period_str)
        except ValueError:
            ptype = PeriodType.FY  # Fallback gracefully instead of raising 500 error

        return FinancialStatementInput(
            ticker=r.ticker,
            company_name=r.company_name,
            year=r.year,
            period_type=ptype,
            currency=r.currency,
            unit_multiplier=r.unit_multiplier,
            revenue=r.revenue,
            ebit=r.ebit,
            ebt=r.ebt,
            net_income_parent=r.net_income_parent,
            total_assets=r.total_assets,
            total_liabilities=r.total_liabilities,
            total_equity_parent=r.total_equity_parent,
            total_equity_consolidated=r.total_equity_consolidated,
            # Extended fields (v4.0)
            sector=r.sector,
            shares_outstanding=r.shares_outstanding,
            cash_and_equivalents=r.cash_and_equivalents,
            interest_bearing_debt=r.interest_bearing_debt,
            current_assets=r.current_assets,
            current_liabilities=r.current_liabilities,
            interest_income=r.interest_income,
            interest_expense=r.interest_expense,
            tax_provision=r.tax_provision,
            operating_cash_flow=r.operating_cash_flow,
            capex=r.capex,
            depreciation=r.depreciation,
            minority_interest=r.minority_interest,
        )

    latest = rows[0]
    prior = next(
        (r for r in rows if r.period_type == latest.period_type and r.year == latest.year - 1),
        None,
    )
    return _to_input(latest), (_to_input(prior) if prior else None)


def load_ticker_history(
    session: Session, ticker: str, limit: int = 5
) -> List[FinancialStatementInput]:
    """Ambil seluruh riwayat tahunan/periode sejenis, terurut terbaru ke terlama.

    Gunakan untuk merender Tabel & Sparkline Multi-Year DuPont Trend (3–5 Tahun).
    """
    rows = session.exec(
        select(FinancialStatementCache).where(
            FinancialStatementCache.ticker == ticker.upper()
        )
    ).all()
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r.year, _PERIOD_RANK.get(r.period_type, 0)), reverse=True)
    rows = rows[:limit]

    result = []
    for r in rows:
        period_str = str(r.period_type).strip().upper()
        try:
            ptype = PeriodType(period_str)
        except ValueError:
            ptype = PeriodType.FY
        result.append(FinancialStatementInput(
            ticker=r.ticker,
            company_name=r.company_name,
            year=r.year,
            period_type=ptype,
            currency=r.currency,
            unit_multiplier=r.unit_multiplier,
            revenue=r.revenue,
            ebit=r.ebit,
            ebt=r.ebt,
            net_income_parent=r.net_income_parent,
            total_assets=r.total_assets,
            total_liabilities=r.total_liabilities,
            total_equity_parent=r.total_equity_parent,
            total_equity_consolidated=r.total_equity_consolidated,
            sector=r.sector,
            shares_outstanding=r.shares_outstanding,
            cash_and_equivalents=r.cash_and_equivalents,
            interest_bearing_debt=r.interest_bearing_debt,
            current_assets=r.current_assets,
            current_liabilities=r.current_liabilities,
            interest_income=r.interest_income,
            interest_expense=r.interest_expense,
            tax_provision=r.tax_provision,
            operating_cash_flow=r.operating_cash_flow,
            capex=r.capex,
            depreciation=r.depreciation,
            minority_interest=r.minority_interest,
        ))
    return result


# ── Template Generator: Excel laporan keuangan resmi ─────────────────

def generate_idx_excel_template_bytes() -> bytes:
    """Buat file .xlsx template laporan keuangan standar IDX (2 sheet: data + panduan)."""
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                                  numbers as xl_numbers)
    from openpyxl.utils import get_column_letter
    import io

    wb = Workbook()

    # ── Sheet 1: Laporan_Keuangan ──────────────────────────────────
    ws1 = wb.active
    ws1.title = "Laporan_Keuangan"

    HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
    SUB_FILL    = PatternFill("solid", fgColor="2A5276")
    ALT_FILL    = PatternFill("solid", fgColor="F0F4F8")
    RED_FILL    = PatternFill("solid", fgColor="FADBD8")
    HDR_FONT    = Font(bold=True, color="FFFFFF", size=11)
    SUB_FONT    = Font(bold=True, color="FFFFFF", size=10)
    TITLE_FONT  = Font(bold=True, size=14, color="1E3A5F")
    BOLD_FONT   = Font(bold=True)
    NORMAL_FONT = Font(size=10)

    thin = Side(style="thin", color="B0BEC5")
    med  = Side(style="medium", color="1E3A5F")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    med_border  = Border(left=med, right=med, top=med, bottom=med)

    def cell_style(ws, row, col, value="", font=None, fill=None, align_h=None,
                   num_fmt=None, border=None):
        c = ws.cell(row=row, column=col, value=None)  # Mulai dengan value None
        if font:   c.font = font
        if fill:   c.fill = fill
        if align_h: c.alignment = Alignment(horizontal=align_h)
        if num_fmt: c.number_format = num_fmt
        if border: c.border = border
        if value is not None:  # Hanya set value jika tidak None
            c.value = value
        return c

    # Title row
    ws1.merge_cells("A1:E1")
    c = ws1.cell(1, 1, "TEMPLATE LAPORAN KEUANGAN — PT XXX TBK (IDX)")
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal="center")

    # Metadata header
    meta_rows = [
        (3, "Kode Emiten", "XXXX", "Tahun", "2025"),
        (4, "Nama Perusahaan", "PT XXX TBK", "Periode", "FY"),
        (5, "Mata Uang", "IDR", "Satuan", "Miliar IDR"),
    ]
    for r, lbl1, val1, lbl2, val2 in meta_rows:
        cell_style(ws1, r, 1, lbl1, BOLD_FONT, fill=SUB_FILL, align_h="left")
        cell_style(ws1, r, 2, val1, NORMAL_FONT, fill=ALT_FILL, align_h="left")
        cell_style(ws1, r, 3, "", fill=None)
        cell_style(ws1, r, 4, lbl2, BOLD_FONT, fill=SUB_FILL, align_h="left")
        cell_style(ws1, r, 5, val2, NORMAL_FONT, fill=ALT_FILL, align_h="left")

    # Separator
    ws1.row_dimensions[6].height = 8

    # Column headers
    headers = ["No", "Pos Akun", "Keterangan / Contoh ASII", "Nilai (IDR Penuh)", "Satuan"]
    for col, h in enumerate(headers, 1):
        cell_style(ws1, 7, col, h, HDR_FONT, fill=HEADER_FILL, align_h="center",
                   border=thin_border)

    # Account rows: (No, Label, Keterangan, Contoh Nilai, Satuan)
    accounts = [
        # ── Income Statement ──
        (None, "LAPORAN LABA RUGI", None, None, None),
        (1, "Pendapatan Bersih (Revenue)", "Total pendapatan usaha", 338400, "Miliar"),
        (2, "Laba Usaha / EBIT", "Laba dari operasional", 50760, "Miliar"),
        (3, "Laba Sebelum Pajak (EBT)", "Profit Before Tax", 49100, "Miliar"),
        (4, "Beban Pajak (Tax Provision)", "Income Tax Expense", 10320, "Miliar"),
        (5, "Laba Bersih yang Dapat Diatribusikan", "Net Income Attributable to Parent", 38789, "Miliar"),
        # ── Balance Sheet ──
        (None, "NERACA", None, None, None),
        (6, "Total Aset", "Total Assets", 462000, "Miliar"),
        (7, "Total Liabilitas", "Total Liabilities", 198000, "Miliar"),
        (8, "Ekuitas Induk (Total Equity — Parent)", "Equity Attributable to Parent", 264000, "Miliar"),
        (9, "Saham Beredar (Shares Outstanding)", "Jumlah lembar saham beredar", 40483553140, "Lembar"),
        (10, "Kas & Setara Kas", "Cash and Cash Equivalents", 48000, "Miliar"),
        (11, "Utang Berbunga (Interest Bearing Debt)", "Total Debt / Long Term Debt", 65000, "Miliar"),
        (12, "Aset Lancar", "Current Assets", 125000, "Miliar"),
        (13, "Liabilitas Lancar", "Current Liabilities", 92000, "Miliar"),
        # ── Cash Flow & Additional ──
        (None, "ARUS KAS & TAMBAHAN", None, None, None),
        (14, "Arus Kas Operasional (OCF)", "Operating Cash Flow", 58000, "Miliar"),
        (15, "CapEx (Capital Expenditure)", "Pengeluaran modal", 19000, "Miliar"),
        (16, "Depresiasi & Amortisasi (D&A)", "Depreciation And Amortization", 11800, "Miliar"),
        (17, "Pendapatan Bunga (Interest Income)", "Interest Income (bank)", 2200, "Miliar"),
        (18, "Beban Bunga (Interest Expense)", "Interest Expense", 5200, "Miliar"),
        (19, "Kepentingan Non-Pengendali (Minority Interest)", "Minority Interest", 8200, "Miliar"),
        (20, "Sektor (Sector)", "Sektor Bursa: Financials / Industrials / Energy", "Industrials", ""),
    ]

    for i, row_data in enumerate(accounts, start=8):
        no, label, note, example, unit = row_data
        row_num = i
        if no is None:  # Section header
            # PENTING: merge_cells SEBELUM menulis/menyimpan nilai
            ws1.merge_cells(f"B{row_num}:E{row_num}")
            # Untuk merged range, HANYA tulis ke anchor (kolom B); sel C,D,E tidak disentuh
            cell_style(ws1, row_num, 2, f"  {label}", SUB_FONT, fill=SUB_FILL)
        else:
            fill = RED_FILL if no in (1, 2, 3, 5, 6, 8, 9) else (
                ALT_FILL if i % 2 == 0 else None
            )
            cell_style(ws1, row_num, 1, no, NORMAL_FONT, fill=fill, align_h="center", border=thin_border)
            cell_style(ws1, row_num, 2, label, NORMAL_FONT, fill=fill, border=thin_border)
            cell_style(ws1, row_num, 3, note or "", NORMAL_FONT, fill=fill, border=thin_border)
            if example is not None:
                fmt = "#,##0" if isinstance(example, (int, float)) else "@"
                cell_style(ws1, row_num, 4, example, NORMAL_FONT, fill=fill,
                           align_h="right", num_fmt=fmt, border=thin_border)
            else:
                cell_style(ws1, row_num, 4, "", fill=fill, border=thin_border)
            cell_style(ws1, row_num, 5, unit, NORMAL_FONT, fill=fill, align_h="center", border=thin_border)

    # Column widths
    ws1.column_dimensions["A"].width = 5
    ws1.column_dimensions["B"].width = 42
    ws1.column_dimensions["C"].width = 35
    ws1.column_dimensions["D"].width = 18
    ws1.column_dimensions["E"].width = 12

    # Freeze header
    ws1.freeze_panes = "A8"

    # ── Sheet 2: Panduan_Upload ────────────────────────────────────
    ws2 = wb.create_sheet("Panduan_Upload")
    guide_items = [
        ("CARA MENGGUNAKAN TEMPLATE INI", None, True),
        ("1. Isi kolom Nilai (Kolom D) untuk setiap pos yang diperlukan.", None, False),
        ("2. Kolom E (Satuan) membantu Anda memahami skala angka:", None, False),
        ("   - Miliar: angka dalam Miliaran IDR (contoh: 338.400 = 338.400 Miliar IDR)", None, False),
        ("   - Lembar: jumlah lembar saham beredar (contoh: 40.483.553.140 lembar)", None, False),
        ("3. Pastikan Kolom B (Pos Akun) TIDAK diubah.", None, False),
        ("4. Simpan file sebagai .xlsx (Excel 2007+).", None, False),
        ("", None, False),
        ("FORMAT UPLOAD", None, True),
        ("5. Unggah file melalui tombol Upload Lapkeu di dashboard.", None, False),
        ("6. Anda juga dapat upload file JSON dengan format:", None, False),
        ('   {"ticker": "XXXX", "year": 2025, "period_type": "FY", ... }', None, False),
        ("7. Untuk upload bulk, gunakan API:", None, False),
        ("   POST /api/dupont/upload", None, False),
        ("", None, False),
        ("CONTOH DATA ASII 2025 (dalam Miliar IDR)", None, True),
        ("Revenue: 338.400 | EBIT: 50.760 | EBT: 49.100 | Net Income: 38.789", None, False),
        ("Total Assets: 462.000 | Total Liabilities: 198.000 | Equity Parent: 264.000", None, False),
        ("", None, False),
        ("CATATAN PENTING", None, True),
        ("- Pastikan Total Assets = Total Liabilities + Total Equity (selisih < 0.05%)", None, False),
        ("- Untuk bank: EBIT = Revenue (karena interest income sudah termasuk di revenue)", None, False),
        ("- Accrual Alert: Jika OCF/Net Income < 0.75, kualitas laba perlu dicek lebih lanjut", None, False),
    ]
    for row_num, (text, _, is_header) in enumerate(guide_items, start=1):
        c = ws2.cell(row_num, 1, text)
        if is_header:
            c.font = Font(bold=True, size=11, color="1E3A5F")
        else:
            c.font = Font(size=10)
    ws2.column_dimensions["A"].width = 90

    # ── Save to BytesIO ───────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
