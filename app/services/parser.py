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

def sync_audited_to_statement_cache(session: Session) -> int:
    """
    ZERO-DUMMY: isi FinancialStatementCache HANYA dari XBRL audited BEI.
    Menggantikan seed hardcoded. Idempoten: update jika sudah ada, insert jika belum.
    Return jumlah baris yang di-sync.
    """
    from app.services.idx_audited_financials import _load, five_year_table

    data = _load()
    if not data:
        print("[sync] XBRL audited kosong — tidak ada yang di-sync")
        return 0

    existing = {
        (r.ticker, r.year, str(r.period_type)): r
        for r in session.exec(select(FinancialStatementCache)).all()
    }

    synced = 0
    skipped = 0
    for tk in data.keys():
        try:
            rows = five_year_table(tk)
        except Exception:
            continue
        for fy in rows:
            if not fy.get("year"):
                continue
            key = (tk, int(fy["year"]), "FY")
            rec = existing.get(key)
            def _f(k):
                v = fy.get(k)
                return float(v) if v is not None else None

            # ZERO-FAKE: baris dengan komponen inti kosong DILEWATI, bukan diisi 0.
            # Skema DB mewajibkan revenue/ebit/ebt/NI/assets/liabilities/equity.
            _core = ["revenue_bn", "ebit_bn", "profit_before_tax_bn", "net_income_parent_bn",
                     "assets_bn", "liabilities_bn", "equity_parent_bn"]
            if any(fy.get(k) is None for k in _core):
                skipped += 1
                continue
            # Skema Pydantic menolak revenue negatif; revenue negatif = artefak
            # pencatatan bank syariah, bukan angka bisnis. Lewati (jangan di-nol-kan).
            if fy.get("revenue_bn") is not None and fy["revenue_bn"] < 0:
                skipped += 1
                continue

            payload = dict(
                company_name=fy.get("company_name") or tk,
                currency=fy.get("currency") or "IDR",
                unit_multiplier=1e9,
                revenue=_f("revenue_bn"),
                ebit=_f("ebit_bn"),
                ebt=_f("profit_before_tax_bn"),
                net_income_parent=_f("net_income_parent_bn"),
                total_assets=_f("assets_bn"),
                total_liabilities=_f("liabilities_bn"),
                total_equity_parent=_f("equity_parent_bn"),
                total_equity_consolidated=_f("equity_total_bn"),
                sector=fy.get("sector"),
                cash_and_equivalents=_f("cash_bn"),
                depreciation=_f("depreciation_amortization_bn"),
                capex=_f("capex_bn"),
                operating_cash_flow=_f("operating_cash_flow_bn"),
                interest_income=_f("interest_income_bn"),
                interest_expense=_f("interest_expense_bn"),
                tax_provision=_f("tax_provision_bn"),
                shares_outstanding=_f("shares_outstanding"),
                interest_bearing_debt=_f("total_loans_bn"),
            )

            if rec:
                changed = False
                for k, v in payload.items():
                    if getattr(rec, k, None) != v:
                        setattr(rec, k, v)
                        changed = True
                if changed:
                    session.add(rec)
                    synced += 1
            else:
                session.add(FinancialStatementCache(
                    ticker=tk, year=int(fy["year"]), period_type="FY",
                    file_hash=f"xbrl-audited-{tk}-{fy['year']}", **payload
                ))
                synced += 1
    session.commit()
    print(f"[sync] XBRL audited -> statement cache: {synced} baris tersinkron, {skipped} dilewati (komponen inti kosong)")
    return synced


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
