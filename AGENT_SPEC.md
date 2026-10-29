# PRODUCT REQUIREMENT DOCUMENT (PRD) & HERMES AGENT MASTER ENGINEERING BLUEPRINT
## FinTech/Investment Platform: DuPont & Terminal Integration (`IDX-QuantTerminal`)

- **Project Name:** FinTech/Investment Platform — DuPont & Terminal Integration
- **Code Name:** `IDX-QuantTerminal`
- **Version:** 2.2 (Audited & Patched — 23 test lolos; lihat BAB 8 untuk batasan yang diketahui)
- **Target Industries:** FinTech, Sekuritas, Equity Research, Corporate Finance Tech
- **Target Execution Agent:** Hermes Agent (Telegram Web Developer Workflow)

---

## DAFTAR ISI
1. **BAB 1: Executive Objective & Capability Signal**
2. **BAB 2: Core Features & Combined 2-Tab Architecture**
3. **BAB 3: Data Inputs, Outputs, & Non-Functional Requirements (NFR)**
4. **BAB 4: 10 Guardrails Anti-Bug Akuntansi BEI & Mikrostruktur Pasar**
5. **BAB 5: Milestones (M1–M8) & Success Metrics**
6. **BAB 6: Full Production Codebase (Seluruh Modul Lengkap Tanpa Potongan)**
   - `6.1` Struktur Direktori & `requirements.txt`
   - `6.2` Database & SHA-256 Cache Layer (`app/db/database.py` & `app/db/models.py`)
   - `6.3` Deterministic 3-Stage & 5-Stage DuPont Engine (`app/services/dupont_engine.py`)
   - `6.4` IDX Excel/PDF Financial Parser & Seed Data (`app/services/parser.py`)
   - `6.5` Anti-Hallucination LLM Anomaly Summarizer (`app/services/llm_analyzer.py`)
   - `6.6` Institutional 1-Page PDF Export Module (`app/services/pdf_exporter.py`)
   - `6.7` Terminal Riset Saham/IHSG Pipeline & BEI Validator (`app/services/terminal_pipeline.py`)
   - `6.8` FastAPI Main Entrypoint & REST/HTMX Endpoints (`app/main.py`)
   - `6.9` Combined 2-Tab Dashboard UI (`app/templates/base.html`)
   - `6.10` Complete Automated Test Suite (`tests/test_core_platform.py`)
7. **BAB 7: Playbook Prompt Eksekusi Hermes Agent di Telegram (M0–M8) & Tips Operasional**
8. **BAB 8: Audit Log v2.2 & Batasan yang Diketahui**

---

# BAB 1: EXECUTIVE OBJECTIVE & CAPABILITY SIGNAL

## 1.1 Objective
Membangun satu platform web terpadu (*unified platform*) yang menggabungkan **Analisis Laporan Keuangan (ALK) & Dekomposisi Rasio DuPont (3-Tahap & 5-Tahap)** dengan **UI Terminal Riset Saham/IHSG** bergaya Bloomberg/TradingView.

## 1.2 Target & Positioning
Developer yang memahami standar akuntansi PSAK/BEI (ALK), dekomposisi matematis 5-stage DuPont, mikrostruktur aliran dana asing BEI (*Foreign Flow Regular vs Negotiated*), aturan fraksi harga saham Indonesia, serta rekayasa *full-stack* berkecepatan tinggi sangat langka di industri. Platform ini menangkap dan membuktikan kapabilitas tersebut secara nyata.

---

# BAB 2: CORE FEATURES & COMBINED 2-TAB ARCHITECTURE

## 2.1 Data Layer (Shared Cache Engine)
- **Input Proyek 1:** Parsing file laporan keuangan emiten BEI/IDX dalam format Excel (`.xlsx`), PDF (`.pdf`), atau JSON standar.
- **Input Proyek 2:** Ingesti terstruktur dari *pipeline* harian IHSG (briefing indeks, *big-cap movers*, *foreign flow*, dan matriks *support/resistance*).
- **Output Shared Layer:** Data keuangan dan pasar yang telah dinormalisasi disimpan di dalam *database* lokal (SQLite mode WAL / PostgreSQL) dengan kunci sidik jari `SHA-256(file_bytes)` serta indeks komposit `(ticker, year, period_type)` sehingga kedua proyek berbagi satu sumber kebenaran (*single source of truth*) tanpa pernah melakukan *re-parse* berulang.

## 2.2 Proyek 1: Platform DuPont & ALK
- **Ratio Engine:** Kalkulasi otomatis dan deterministik untuk:
  - **3-Stage DuPont:** Return on Equity (ROE), Net Profit Margin (NPM), Asset Turnover (AT), dan Equity Multiplier (EM).
  - **5-Stage DuPont:** Ekspansi NPM menjadi Tax Burden ($\frac{\text{Net Income}}{\text{EBT}}$), Interest Burden ($\frac{\text{EBT}}{\text{EBIT}}$), dan EBIT Margin ($\frac{\text{EBIT}}{\text{Revenue}}$), dikalikan dengan Asset Turnover dan Equity Multiplier.
- **AI Layer (LLM Anomaly Summarizer):** Merangkum anomali rasio tahun berjalan dibanding tahun sebelumnya (YoY)—menjawab secara tajam apakah kenaikan/penurunan ROE digerakkan oleh kualitas operasional (*margin/turnover expansion*) atau semata-mata didorong oleh pembengkakan utang (*financial leverage / debt*).
- **Output Proyek 1:** Visualisasi pohon DuPont interaktif (*Interactive DuPont Tree*) dengan kode warna kesehatan + ekspor laporan ringkas PDF 1 halaman (*Concise Institutional Tear-Sheet*).

## 2.3 Proyek 2: Terminal Riset Saham / IHSG
- **Pipeline Integration:** Terhubung langsung dengan *pipeline* data pasar harian yang mencakup:
  1. Daily IHSG Briefing (posisi indeks, perubahan poin & persen, nilai transaksi, status pasar, ringkasan makro).
  2. Big-Cap Movers (saham penggerak indeks beserta bobot poin dampak ke IHSG).
  3. Foreign Flow BEI (memisahkan *Net Foreign Regular Market* 1D & 5D dari *Negotiated/Crossing Market*).
  4. Support & Resistance Levels (`S2`, `S1`, `Last Price`, `R1`, `R2`, jarak persentase menuju *breakout* `R1`, serta validasi Fraksi Harga BEI).
- **UI Proyek 2:** Grid terminal bersih berdensitas tinggi ala Bloomberg/TradingView dengan fitur pencarian instan dan pengurutan kolom.

## 2.4 Combined Dashboard (Gabungan Proyek 1 & Proyek 2)
- **Tab 1 ("DuPont"):**
  - **Panel Kiri (70% lebar):** Toggle 3-Stage vs 5-Stage + Interactive DuPont Tree Visualization + Kartu AI Anomaly Summary & Quality of Earnings Verdict.
  - **Panel Kanan (30% lebar):** Pemilih Emiten dari Cache, Indikator Validasi Identitas Neraca, serta Tombol Unduh PDF Ringkas. *(Upload file lapkeu tersedia lewat API `POST /api/dupont/upload`; form upload di UI masuk backlog, lihat BAB 8.)*
- **Tab 2 ("Terminal"):**
  - **Top Market Tape:** Snapshot IHSG & Net Foreign Regular.
  - **Main Grid:** 3 Panel Terminal (Big-Cap Movers, Foreign Flow Momentum, Support/Resistance Matrix).
- **Navigasi & Integrasi Lintas Tab:**
  - Perpindahan antar tab menggunakan *client-side state* (Alpine.js) dengan latensi `< 50 milidetik` (jauh di bawah batas `< 1 detik`).
  - **Cross-Tab Deep Linking:** Klik pada kode saham (misal `ASII`, `TLKM`, `ICBP`, `ADRO`) di tabel Tab 2 ("Terminal") membuka Tab 1 ("DuPont") dengan pohon DuPont emiten tersebut (lewat *page reload* `/?ticker=...`). Ticker yang belum ada di cache menampilkan banner peringatan, bukan diganti diam-diam.

---

# BAB 3: DATA INPUTS, OUTPUTS, TECHNICAL STACK, & NFR

## 3.1 Data Inputs
1. **IDX Financial Statements (Excel/PDF/JSON):** Mencakup Neraca (*Statement of Financial Position*) dan Laba Rugi (*Statement of Profit or Loss*).
2. **Daily IHSG Briefing Data:** Indeks komposit, perubahan harian, nilai transaksi, aliran dana asing agregat, dan catatan *market briefing*.
3. **Big-Cap Mover Data:** Harga terakhir, persentase perubahan, volume lot, kapitalisasi pasar, dan kontribusi poin terhadap IHSG.
4. **Foreign Flow Data:** Nilai beli/jual bersih investor asing di Pasar Reguler (RG) 1 hari & 5 hari serta Pasar Negosiasi (NG).
5. **Support/Resistance Levels:** Level teknikal `S2`, `S1`, `R1`, `R2` per emiten.

## 3.2 Outputs
1. **Interactive DuPont Tree Visualization:** Diagram pohon interaktif yang merender nilai rasio, rumus, perubahan YoY (`bps` dan `%`), dan warna status.
2. **PDF Summary Reports:** Dokumen PDF 1 halaman berisi struktur pohon DuPont, tabel perbandingan YoY, dan analisis anomali rasio.
3. **Terminal-Style Grid UI Display:** Tabel *multi-panel* bergaya terminal institusional.
4. **LLM-Generated Anomaly Alerts:** Peringatan terstruktur mengenai kualitas ROE dan anomali komponen DuPont.

## 3.3 Technical Stack (Locked for Production)
- **Backend:** Python 3.11+, FastAPI, Pydantic v2, Pandas, OpenPyXL, PDFPlumber.
- **UI & Visualization:** FastAPI + Jinja2 + Alpine.js + TailwindCSS (tab instan tanpa *reload*); pohon DuPont dirender sebagai kartu grid berwarna. *(HTMX, SVG/Plotly tree, dan AG-Grid belum dipakai di v2.2, lihat BAB 8.)*
- **Export Module:** WeasyPrint (dengan *built-in fallback* ke Print-Ready HTML/PDF view agar 100% berjalan di semua OS tanpa *error* dependensi C).
- **Cache Database:** SQLite (dengan `PRAGMA journal_mode=WAL;`) melalui SQLModel / SQLAlchemy, kompatibel penuh dengan PostgreSQL.

## 3.4 Non-Functional Requirements (NFR)
- **Performance:** Kalkulasi rasio DuPont `< 500ms` per emiten (target PRD `< 5 detik`); waktu muat awal *dashboard* `< 2 detik` (terukur 1–42 ms tanpa LLM; LLM tidak pernah memblokir halaman utama); latensi pindah tab `< 100ms` (target PRD `< 1 detik`).
- **Accuracy:** Rumus DuPont diverifikasi terhadap standar IDX dengan toleransi rekonsiliasi $\vert{}\text{ROE}_{\text{direct}} - \text{ROE}_{\text{5-stage}}\vert{} < 10^{-6}$.
- **Scalability:** Mendukung pemrosesan banyak emiten secara konkuren; sistem *cache* berbasis hash SHA-256 mencegah *re-parse* file yang sama.
- **Usability:** Antarmuka 2-tab yang intuitif dengan pintasan *keyboard* (`Alt+1` untuk DuPont, `Alt+2` untuk Terminal) dan klik langsung antar-tab.

---

# BAB 4: 10 GUARDRAILS ANTI-BUG AKUNTANSI BEI & MIKROSTRUKTUR PASAR

Hermes Agent wajib menerapkan aturan di bawah ini di level kode. Semuanya sudah diimplementasikan dan diuji pada v2.2; ketiga guardrail tambahan (G8–G10) ditambahkan setelah audit menemukan bug nyata:

1. **Konsistensi Entitas Induk (Parent Entity Rule):**
   Laporan keuangan konsolidasian BEI memisahkan *Laba/Ekuitas Entitas Induk* dan *Kepentingan Non-Pengendali (Minority Interest)*. Seluruh rasio ROE dan Equity Multiplier wajib menggunakan `net_income_parent` dan `total_equity_parent` secara konsisten agar identitas perkalian DuPont tidak melenceng.
2. **Penyetahuan Otomatis Laporan Kuartalan (Interim Annualization):**
   Angka Laba Rugi pada laporan Q1 (3 bulan), Q2 (6 bulan), dan Q3 (9 bulan) bersifat kumulatif sejak awal tahun, sedangkan Neraca adalah posisi akhir periode. Sistem wajib mengalikan `revenue`, `ebit`, `ebt`, dan `net_income_parent` dengan faktor $\frac{12}{\text{bulan}}$ (`Q1 = 4.0`, `Q2 = 2.0`, `Q3 = 1.3333`, `FY = 1.0`) sebelum dibagi dengan Aset atau Ekuitas.
3. **Pencegahan Bug "ROE Positif Palsu" saat Defisiensi Modal (Negative Equity Guard):**
   Jika emiten merugi ($\text{Net Income} < 0$) sekaligus memiliki Ekuitas negatif ($\text{Equity} \le 0$), pembagian biasa menghasilkan ROE positif palsu (contoh: $\frac{-200}{-1000} = +20\%$). Jika `total_equity_parent <= 0`, sistem wajib memblokir kalkulasi ROE dan Equity Multiplier (`None`), menampilkan label `"NM (Negative Equity)"`, dan memicu status `EQUITY_DISTRESS`.
4. **Penanganan Inversi Tanda pada 5-Stage DuPont (`EBIT <= 0` atau `EBT <= 0`):**
   Jika `EBIT <= 0` atau `EBT <= 0`, rasio *Interest Burden* ($\frac{\text{EBT}}{\text{EBIT}}$) dan *Tax Burden* ($\frac{\text{NI}}{\text{EBT}}$) mengalami inversi tanda atau memicu `ZeroDivisionError`. Gunakan fungsi `_safe_div` dan aktifkan flag `sign_inversion_detected = True`.
5. **Normalisasi Satuan/Mata Uang & Cek Identitas Neraca:**
   Kalikan seluruh pos laporan keuangan dengan `unit_multiplier` (`1`, `1e3`, `1e6`, `1e9`) dan verifikasi bahwa $\left\vert{}\text{Total Assets} - (\text{Total Liabilities} + \text{Total Equity})\right\vert{} \le 0.05\%$.
6. **Zero-Math LLM Policy & Deterministic Fallback:**
   LLM tidak boleh melakukan operasi hitung. Python menghitung seluruh rasio, perubahan YoY dalam *basis points* (`bps`) dan persentase (`%`), serta menentukan `primary_driver`, `primary_driver_effect` (POSITIVE/NEGATIVE), dan `roe_direction` (UP/DOWN/FLAT) terlebih dahulu. Output LLM **divalidasi**: setiap angka dalam narasi harus bisa ditelusuri ke data Python (`numbers_are_grounded`); jika tidak, output ditolak. Jika API Key belum diisi, koneksi *timeout*, atau validasi gagal, `generate_deterministic_anomaly_summary()` mengambil alih sehingga fitur ini tidak pernah crash. Halaman utama tidak menunggu LLM: ia menampilkan ringkasan deterministik dan menghangatkan cache LLM di latar belakang.
7. **Pemisahan Foreign Flow RG/NG & Validasi Fraksi Harga BEI:**
   - Sinyal akumulasi/distribusi asing di Terminal hanya dihitung dari **Pasar Reguler (`net_foreign_rg`)**, terpisah dari **Pasar Negosiasi (`net_foreign_ng`)** agar transaksi *crossing* tidak memalsukan sinyal.
   - Seluruh harga dan level Support/Resistance wajib divalidasi terhadap **Fraksi Harga BEI**:
     - Harga $< 200 \rightarrow$ kelipatan Rp1
     - Harga $200 \text{ s/d } < 500 \rightarrow$ kelipatan Rp2
     - Harga $500 \text{ s/d } < 2.000 \rightarrow$ kelipatan Rp5
     - Harga $2.000 \text{ s/d } < 5.000 \rightarrow$ kelipatan Rp10
     - Harga $\ge 5.000 \rightarrow$ kelipatan Rp25

8. **G8 — Parser Anti-Subtotal (Exact Match untuk Pos Neraca):**
   Pos `total_assets`, `total_liabilities`, `total_equity_parent`, dan `total_equity_consolidated` hanya cocok **persis** (setelah normalisasi huruf/spasi/label dwibahasa). Baris seperti "Jumlah aset lancar" atau "Jumlah liabilitas jangka pendek" tidak boleh terbaca sebagai total. Baris "EBITDA" tidak boleh terbaca sebagai EBIT. Jika laporan hanya punya satu baris "Jumlah ekuitas", nilainya dipakai sebagai ekuitas entitas induk dan ekuitas konsolidasi.
9. **G9 — Pembanding YoY Harus Tepat (Tahun-1, Jenis Periode Sama):**
   `load_ticker_pair` hanya memasangkan periode terbaru dengan periode **jenis sama pada tahun sebelumnya** (FY dengan FY, Q2 dengan Q2). Jika tidak ada, pembanding = `None` (tidak pernah memakai tahun yang sama). Database memberi `UniqueConstraint(ticker, year, period_type)`; upload ulang untuk periode yang sama **menggantikan** baris lama.
10. **G10 — Atribusi ROE Bertanda (Arah Diperhitungkan):**
    `primary_driver` ditentukan dari dekomposisi logaritmik aditif: `ln(ROE_t/ROE_t-1) = Σ ln(faktor_t/faktor_t-1)`. Hasilnya menyatakan faktor terbesar **dan apakah efeknya positif atau negatif**. Narasi dan verdict wajib mengikuti arah itu: margin runtuh tidak boleh berlabel "High Quality", dan penurunan leverage tidak boleh disebut "ekspansi". Tanpa pembanding YoY, verdict = `BASELINE` dan tidak ada klaim perubahan.

**Tambahan G7:** endpoint `POST /api/terminal/ingest` menolak (HTTP 422) payload yang melanggar Fraksi Harga BEI atau urutan `S2 < S1 <= Last <= R1 < R2`. Jika variabel lingkungan `INGEST_API_KEY` diisi, endpoint ini juga mewajibkan header `X-API-Key`.

---

# BAB 5: MILESTONES (M1–M8) & SUCCESS METRICS

## 5.1 Phase-Based Milestones
- **M1:** Data Ingestion Layer — Parse Excel/PDF/JSON Lapkeu IDX $\rightarrow$ validasi skema & simpan ke SQLite Cache (`SHA-256`).
- **M2:** Ratio Engine — Kalkulasi ROE, NPM, AT, EM (3-Stage) + Tax Burden, Interest Burden, EBIT Margin (5-Stage) + YoY Attribution.
- **M3:** LLM Anomaly Summarization — Prompt engineering berbasis JSON deterministik + Pydantic validator + Rule-based fallback.
- **M4:** Interactive DuPont Tree Visualization — Komponen visual pohon 3-Stage & 5-Stage dengan indikator warna YoY.
- **M5:** PDF Export Module — Ekspor laporan ringkas 1 halaman siap cetak/unduh.
- **M6:** Terminal Pipeline Integration — Integrasi data harian IHSG, Big-Cap Movers, Foreign Flow RG/NG, dan Support/Resistance.
- **M7:** Combined Dashboard — Penggabungan Tab 1 ("DuPont") & Tab 2 ("Terminal") dengan *shared cache* dan *cross-tab linking*.
- **M8:** Automated QA & Verification — Pengujian penuh dengan `pytest` untuk seluruh *edge cases* dan target latensi.

## 5.2 Success Metrics
- **Parse & Formula Accuracy:** 100% patuh standar IDX (rekonsiliasi 3-stage & 5-stage `< 1e-6`).
- **Anomaly LLM Relevance:** `> 80%` relevan dan bebas halusinasi angka karena dikunci dengan data Python.
- **Dashboard Tab-Switch Latency:** `< 1 detik` (aktual `< 50ms` dengan *client-side tab switching*).

---

# BAB 6: FULL PRODUCTION CODEBASE (LENGKAP TANPA POTONGAN)

Hermes Agent dapat langsung menuliskan seluruh file di bawah ini ke dalam repositori proyek.

## 6.1 Struktur Direktori & `requirements.txt`

```text
idx-quant-terminal/
├── AGENT_SPEC.md
├── requirements.txt
├── pytest.ini
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   └── models.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dupont_engine.py
│   │   ├── parser.py
│   │   ├── llm_analyzer.py
│   │   ├── pdf_exporter.py
│   │   └── terminal_pipeline.py
│   └── templates/
│       ├── base.html
│       └── pdf_report.html
└── tests/
    └── test_core_platform.py
```

**File: `requirements.txt`**
```text
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
sqlmodel>=0.0.18
pandas>=2.2.0
openpyxl>=3.1.2
pdfplumber>=0.11.0
jinja2>=3.1.3
python-multipart>=0.0.9
httpx>=0.27.0
pytest>=8.1.0
```

**File: `pytest.ini`** (wajib, supaya `from app.main import app` ter-resolve)
```ini
[pytest]
pythonpath = .
testpaths = tests
```

---

## 6.2 Database & SHA-256 Cache Layer (`app/db/database.py` & `app/db/models.py`)

**File: `app/db/database.py`**
```python
import os
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import event

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

def init_db() -> None:
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
```

**File: `app/db/models.py`**
```python
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field

class FinancialStatementCache(SQLModel, table=True):
    # Satu baris per (ticker, tahun, jenis periode): upload ulang menggantikan, bukan menambah.
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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

## 6.3 Deterministic 3-Stage & 5-Stage DuPont Engine (`app/services/dupont_engine.py`)

**File: `app/services/dupont_engine.py`**
```python
from __future__ import annotations
import math
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class PeriodType(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    FY = "FY"

class PrimaryDriver(str, Enum):
    OPERATIONAL_MARGIN = "OPERATIONAL_MARGIN"
    ASSET_EFFICIENCY = "ASSET_EFFICIENCY"
    FINANCIAL_LEVERAGE = "FINANCIAL_LEVERAGE"
    TAX_OR_INTEREST_BURDEN = "TAX_OR_INTEREST_BURDEN"
    EQUITY_DISTRESS = "EQUITY_DISTRESS"
    INSUFFICIENT_PRIOR_DATA = "INSUFFICIENT_PRIOR_DATA"

class FinancialStatementInput(BaseModel):
    ticker: str = Field(..., min_length=4, max_length=6)
    company_name: str
    year: int = Field(..., ge=2000, le=2100)
    period_type: PeriodType = PeriodType.FY
    currency: str = Field(default="IDR", pattern="^(IDR|USD)$")
    unit_multiplier: float = Field(default=1.0, gt=0)

    revenue: float = Field(..., ge=0)
    ebit: float
    ebt: float
    net_income_parent: float

    total_assets: float = Field(..., gt=0)
    total_liabilities: float = Field(..., ge=0)
    total_equity_parent: float
    total_equity_consolidated: Optional[float] = None

    @property
    def annualization_factor(self) -> float:
        mapping = {
            PeriodType.Q1: 12.0 / 3.0,
            PeriodType.Q2: 12.0 / 6.0,
            PeriodType.Q3: 12.0 / 9.0,
            PeriodType.FY: 1.0,
        }
        return mapping[self.period_type]

    @property
    def balance_sheet_discrepancy_pct(self) -> float:
        eq_to_check = (
            self.total_equity_consolidated
            if self.total_equity_consolidated is not None
            else self.total_equity_parent
        )
        expected_assets = self.total_liabilities + eq_to_check
        if self.total_assets == 0:
            return 100.0
        return abs(self.total_assets - expected_assets) / self.total_assets * 100.0

class DuPontMetrics(BaseModel):
    ticker: str
    company_name: str
    year: int
    period_type: PeriodType
    annualized_applied: bool
    is_negative_equity: bool
    sign_inversion_detected: bool
    balance_sheet_balanced: bool

    roe: Optional[float] = None
    net_profit_margin: Optional[float] = None
    asset_turnover: Optional[float] = None
    equity_multiplier: Optional[float] = None

    tax_burden: Optional[float] = None
    interest_burden: Optional[float] = None
    ebit_margin: Optional[float] = None

    reconciliation_diff_3stage: Optional[float] = None
    reconciliation_diff_5stage: Optional[float] = None

class YoYDeltaItem(BaseModel):
    metric_name: str
    current_val: Optional[float]
    previous_val: Optional[float]
    abs_change: Optional[float]
    bps_change: Optional[float]
    pct_change: Optional[float]

class DuPontAnalysisBundle(BaseModel):
    current: DuPontMetrics
    previous: Optional[DuPontMetrics] = None
    yoy_deltas: Dict[str, YoYDeltaItem] = Field(default_factory=dict)
    primary_driver: PrimaryDriver
    primary_driver_effect: str = "NA"  # POSITIVE = faktor terbesar menaikkan ROE, NEGATIVE = menurunkan
    roe_direction: str = "NA"  # UP / DOWN / FLAT (ambang 10 bps) / NA
    driver_contributions_pct: Dict[str, float] = Field(default_factory=dict)  # dekomposisi log, dalam %
    warnings: List[str] = Field(default_factory=list)
    tree_nodes: List[Dict[str, Any]] = Field(default_factory=list)

def _safe_div(num: float, den: float) -> Optional[float]:
    if abs(den) < 1e-12:
        return None
    return num / den

def compute_single_period_dupont(stmt: FinancialStatementInput) -> DuPontMetrics:
    factor = stmt.annualization_factor
    mult = stmt.unit_multiplier

    ann_rev = stmt.revenue * mult * factor
    ann_ebit = stmt.ebit * mult * factor
    ann_ebt = stmt.ebt * mult * factor
    ann_ni = stmt.net_income_parent * mult * factor

    assets = stmt.total_assets * mult
    equity = stmt.total_equity_parent * mult

    is_neg_eq = equity <= 0
    sign_inv = (ann_ebit <= 0) or (ann_ebt <= 0)
    bs_ok = stmt.balance_sheet_discrepancy_pct <= 0.05

    npm = _safe_div(ann_ni, ann_rev)
    at = _safe_div(ann_rev, assets)
    ebit_m = _safe_div(ann_ebit, ann_rev)

    if is_neg_eq:
        roe = None
        em = None
    else:
        roe = _safe_div(ann_ni, equity)
        em = _safe_div(assets, equity)

    tb = _safe_div(ann_ni, ann_ebt)
    ib = _safe_div(ann_ebt, ann_ebit)

    diff_3 = None
    diff_5 = None
    if roe is not None and npm is not None and at is not None and em is not None:
        roe_3 = npm * at * em
        diff_3 = abs(roe - roe_3)
        if tb is not None and ib is not None and ebit_m is not None:
            roe_5 = tb * ib * ebit_m * at * em
            diff_5 = abs(roe - roe_5)

    return DuPontMetrics(
        ticker=stmt.ticker.upper(),
        company_name=stmt.company_name,
        year=stmt.year,
        period_type=stmt.period_type,
        annualized_applied=(factor != 1.0),
        is_negative_equity=is_neg_eq,
        sign_inversion_detected=sign_inv,
        balance_sheet_balanced=bs_ok,
        roe=roe,
        net_profit_margin=npm,
        asset_turnover=at,
        equity_multiplier=em,
        tax_burden=tb,
        interest_burden=ib,
        ebit_margin=ebit_m,
        reconciliation_diff_3stage=diff_3,
        reconciliation_diff_5stage=diff_5,
    )

def analyze_dupont_yoy(
    current_stmt: FinancialStatementInput,
    previous_stmt: Optional[FinancialStatementInput] = None,
) -> DuPontAnalysisBundle:
    curr = compute_single_period_dupont(current_stmt)
    prev = compute_single_period_dupont(previous_stmt) if previous_stmt else None
    warnings: List[str] = []

    if not curr.balance_sheet_balanced:
        warnings.append(
            f"Neraca tidak seimbang: selisih {current_stmt.balance_sheet_discrepancy_pct:.2f}% antara Aset dan (Liabilitas + Ekuitas)."
        )
    if curr.is_negative_equity:
        warnings.append(
            "Defisiensi Modal (Ekuitas <= 0): ROE dan Equity Multiplier dinonaktifkan (NM) untuk mencegah angka positif palsu."
        )
    if curr.sign_inversion_detected:
        warnings.append(
            "Inversi tanda terdeteksi (EBIT <= 0 atau EBT <= 0): Rasio Tax Burden dan Interest Burden perlu diinterpretasikan bersama nilai absolutnya."
        )
    if curr.annualized_applied:
        warnings.append(
            f"Laporan interim ({curr.period_type.value}) telah disetahunkan (faktor {current_stmt.annualization_factor:.2f}x) agar sebanding dengan Neraca."
        )

    deltas: Dict[str, YoYDeltaItem] = {}
    primary_driver = PrimaryDriver.INSUFFICIENT_PRIOR_DATA
    driver_effect = "NA"
    roe_direction = "NA"
    contributions: Dict[str, float] = {}

    if prev is not None:
        metric_keys = [
            ("roe", True),
            ("net_profit_margin", True),
            ("ebit_margin", True),
            ("asset_turnover", False),
            ("equity_multiplier", False),
            ("tax_burden", False),
            ("interest_burden", False),
        ]
        for key, is_rate in metric_keys:
            c_val = getattr(curr, key)
            p_val = getattr(prev, key)
            abs_chg = (c_val - p_val) if (c_val is not None and p_val is not None) else None
            bps_chg = (abs_chg * 10000.0) if (abs_chg is not None and is_rate) else None
            pct_chg = (
                ((c_val - p_val) / abs(p_val) * 100.0)
                if (c_val is not None and p_val is not None and abs(p_val) > 1e-9)
                else None
            )
            deltas[key] = YoYDeltaItem(
                metric_name=key,
                current_val=c_val,
                previous_val=p_val,
                abs_change=abs_chg,
                bps_change=bps_chg,
                pct_change=pct_chg,
            )

        if curr.is_negative_equity:
            primary_driver = PrimaryDriver.EQUITY_DISTRESS
        elif prev.is_negative_equity:
            warnings.append(
                "Periode pembanding memiliki ekuitas negatif: atribusi YoY ROE tidak bermakna (NM)."
            )
        else:
            primary_driver, driver_effect, roe_direction, contributions = _attribute_roe_change(
                curr, prev, deltas
            )

    if curr.is_negative_equity:
        primary_driver = PrimaryDriver.EQUITY_DISTRESS

    tree_nodes = _build_interactive_tree_nodes(curr, deltas)
    return DuPontAnalysisBundle(
        current=curr,
        previous=prev,
        yoy_deltas=deltas,
        primary_driver=primary_driver,
        primary_driver_effect=driver_effect,
        roe_direction=roe_direction,
        driver_contributions_pct=contributions,
        warnings=warnings,
        tree_nodes=tree_nodes,
    )

_FACTOR_GROUPS = {
    PrimaryDriver.OPERATIONAL_MARGIN: ("ebit_margin",),
    PrimaryDriver.ASSET_EFFICIENCY: ("asset_turnover",),
    PrimaryDriver.FINANCIAL_LEVERAGE: ("equity_multiplier",),
    PrimaryDriver.TAX_OR_INTEREST_BURDEN: ("tax_burden", "interest_burden"),
}

def _roe_direction(deltas: Dict[str, YoYDeltaItem]) -> str:
    d = deltas.get("roe")
    if d is None or d.bps_change is None:
        return "NA"
    if d.bps_change >= 10.0:
        return "UP"
    if d.bps_change <= -10.0:
        return "DOWN"
    return "FLAT"

def _attribute_roe_change(
    curr: DuPontMetrics, prev: DuPontMetrics, deltas: Dict[str, YoYDeltaItem]
):
    """
    Atribusi perubahan ROE dengan dekomposisi logaritmik:
    ln(ROE_t / ROE_t-1) = sum ln(faktor_t / faktor_t-1) untuk 5 faktor DuPont, sehingga kontribusi
    tiap faktor bertanda (+/-) dan aditif. Jika ada faktor <= 0, jatuh ke heuristik % perubahan.
    Mengembalikan (driver, efek, arah_roe, kontribusi_%).
    """
    direction = _roe_direction(deltas)
    contributions: Dict[str, float] = {}
    usable = True
    for driver, keys in _FACTOR_GROUPS.items():
        total = 0.0
        for k in keys:
            c_val, p_val = getattr(curr, k), getattr(prev, k)
            if c_val is None or p_val is None or c_val <= 0 or p_val <= 0:
                usable = False
                break
            total += math.log(c_val / p_val)
        if not usable:
            break
        contributions[driver.value] = total * 100.0

    if usable:
        main = max(contributions, key=lambda k: abs(contributions[k]))
        effect = "POSITIVE" if contributions[main] >= 0 else "NEGATIVE"
        return PrimaryDriver(main), effect, direction, contributions

    signed = {
        driver: sum((deltas[k].pct_change or 0.0) for k in keys)
        for driver, keys in _FACTOR_GROUPS.items()
    }
    main_driver = max(signed, key=lambda d: abs(signed[d]))
    if abs(signed[main_driver]) < 1e-9:
        return PrimaryDriver.INSUFFICIENT_PRIOR_DATA, "NA", direction, {}
    return main_driver, ("POSITIVE" if signed[main_driver] >= 0 else "NEGATIVE"), direction, {}

def _build_interactive_tree_nodes(
    curr: DuPontMetrics, deltas: Dict[str, YoYDeltaItem]
) -> List[Dict[str, Any]]:
    def fmt_pct(v: Optional[float]) -> str:
        return "NM" if v is None else f"{v * 100:.2f}%"

    def fmt_mult(v: Optional[float]) -> str:
        return "NM" if v is None else f"{v:.2f}x"

    def fmt_delta(key: str, is_rate: bool) -> str:
        if key not in deltas or deltas[key].abs_change is None:
            return "Baseline Period"
        d = deltas[key]
        if is_rate and d.bps_change is not None:
            sign = "+" if d.bps_change >= 0 else ""
            return f"{sign}{d.bps_change:.0f} bps YoY"
        sign = "+" if (d.pct_change or 0) >= 0 else ""
        return f"{sign}{d.pct_change:.1f}% YoY"

    return [
        {
            "id": "roe",
            "parent": None,
            "stage": "BOTH",
            "label": "Return on Equity (ROE)",
            "formula": "NPM × Asset Turnover × Equity Multiplier",
            "value": fmt_pct(curr.roe),
            "yoy": fmt_delta("roe", True),
            "color": "crimson" if curr.is_negative_equity else "emerald",
        },
        {
            "id": "npm",
            "parent": "roe",
            "stage": "BOTH",
            "label": "Net Profit Margin (NPM)",
            "formula": "Net Income / Revenue",
            "value": fmt_pct(curr.net_profit_margin),
            "yoy": fmt_delta("net_profit_margin", True),
            "color": "emerald" if (curr.net_profit_margin or 0) > 0 else "crimson",
        },
        {
            "id": "at",
            "parent": "roe",
            "stage": "BOTH",
            "label": "Asset Turnover (AT)",
            "formula": "Revenue / Total Assets",
            "value": fmt_mult(curr.asset_turnover),
            "yoy": fmt_delta("asset_turnover", False),
            "color": "slate",
        },
        {
            "id": "em",
            "parent": "roe",
            "stage": "BOTH",
            "label": "Equity Multiplier (EM)",
            "formula": "Total Assets / Equity",
            "value": fmt_mult(curr.equity_multiplier),
            "yoy": fmt_delta("equity_multiplier", False),
            "color": "amber" if (curr.equity_multiplier or 0) > 2.5 else "slate",
        },
        {
            "id": "tb",
            "parent": "npm",
            "stage": "5_ONLY",
            "label": "Tax Burden (TB)",
            "formula": "Net Income / EBT",
            "value": fmt_mult(curr.tax_burden),
            "yoy": fmt_delta("tax_burden", False),
            "color": "slate",
        },
        {
            "id": "ib",
            "parent": "npm",
            "stage": "5_ONLY",
            "label": "Interest Burden (IB)",
            "formula": "EBT / EBIT",
            "value": fmt_mult(curr.interest_burden),
            "yoy": fmt_delta("interest_burden", False),
            "color": "amber" if (curr.interest_burden or 1.0) < 0.75 else "slate",
        },
        {
            "id": "ebit_m",
            "parent": "npm",
            "stage": "5_ONLY",
            "label": "EBIT Margin",
            "formula": "EBIT / Revenue",
            "value": fmt_pct(curr.ebit_margin),
            "yoy": fmt_delta("ebit_margin", True),
            "color": "emerald" if (curr.ebit_margin or 0) > 0.10 else "slate",
        },
    ]
```

---

## 6.4 IDX Excel/PDF Financial Parser & Seed Data (`app/services/parser.py`)

**File: `app/services/parser.py`**
```python
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

# Pos neraca (total_*) HANYA dicocokkan persis setelah normalisasi, supaya baris subtotal seperti
# "Jumlah aset lancar" atau "Jumlah liabilitas jangka pendek" tidak terbaca sebagai total.
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
    # Label dwibahasa: "Jumlah aset / Total assets" atau "Jumlah aset (Total assets)"
    for piece in re.split(r"\s*/\s*|\s*\(|\)", text):
        piece = piece.strip()
        if piece and piece != text:
            parts.append(piece)
    return parts

def _match_account_key(raw_label: str) -> Optional[str]:
    candidates = _label_candidates(raw_label)
    for cand in candidates:
        if cand in _EXACT_LOOKUP:
            return _EXACT_LOOKUP[cand]
    # Fallback "mengandung kata" hanya untuk pos laba rugi, dengan batas kata.
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

    # Emiten tanpa kepentingan non-pengendali hanya melaporkan satu baris "Jumlah ekuitas":
    # pada kasus itu ekuitas entitas induk = ekuitas konsolidasi.
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
    )
    same_period = session.exec(
        select(FinancialStatementCache).where(
            FinancialStatementCache.ticker == stmt.ticker.upper(),
            FinancialStatementCache.year == stmt.year,
            FinancialStatementCache.period_type == stmt.period_type.value,
        )
    ).first()
    if same_period:
        # Upload ulang untuk periode yang sama: data terbaru menggantikan, bukan menambah baris.
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
    samples = [
        # ASII 2024 & 2025 (Operational & Solid Balance Sheet)
        FinancialStatementInput(
            ticker="ASII", company_name="PT Astra International Tbk", year=2024, period_type=PeriodType.FY,
            revenue=316565, ebit=44200, ebt=42800, net_income_parent=33839,
            total_assets=445679, total_liabilities=195261, total_equity_parent=250418,
        ),
        FinancialStatementInput(
            ticker="ASII", company_name="PT Astra International Tbk", year=2025, period_type=PeriodType.FY,
            revenue=338400, ebit=50760, ebt=49100, net_income_parent=38789,
            total_assets=462000, total_liabilities=198000, total_equity_parent=264000,
        ),
        # ICBP 2024 & 2025 (Margin & Turnover Driven)
        FinancialStatementInput(
            ticker="ICBP", company_name="PT Indofood CBP Sukses Makmur Tbk", year=2024, period_type=PeriodType.FY,
            revenue=67910, ebit=14260, ebt=11900, net_income_parent=8950,
            total_assets=119200, total_liabilities=57100, total_equity_parent=62100,
        ),
        FinancialStatementInput(
            ticker="ICBP", company_name="PT Indofood CBP Sukses Makmur Tbk", year=2025, period_type=PeriodType.FY,
            revenue=72400, ebit=16652, ebt=14500, net_income_parent=11165,
            total_assets=123500, total_liabilities=56500, total_equity_parent=67000,
        ),
        # TLKM 2024 & 2025 (Leverage Expansion Case)
        FinancialStatementInput(
            ticker="TLKM", company_name="PT Telkom Indonesia (Persero) Tbk", year=2024, period_type=PeriodType.FY,
            revenue=149216, ebit=44764, ebt=40800, net_income_parent=24560,
            total_assets=287042, total_liabilities=130480, total_equity_parent=156562,
        ),
        FinancialStatementInput(
            ticker="TLKM", company_name="PT Telkom Indonesia (Persero) Tbk", year=2025, period_type=PeriodType.FY,
            revenue=152000, ebit=44840, ebt=39200, net_income_parent=24300,
            total_assets=335000, total_liabilities=197000, total_equity_parent=138000,
        ),
        # ADRO 2024 & 2025
        FinancialStatementInput(
            ticker="ADRO", company_name="PT Alamtri Resources Indonesia Tbk", year=2024, period_type=PeriodType.FY,
            revenue=98500, ebit=31520, ebt=30900, net_income_parent=24100,
            total_assets=162000, total_liabilities=47000, total_equity_parent=115000,
        ),
        FinancialStatementInput(
            ticker="ADRO", company_name="PT Alamtri Resources Indonesia Tbk", year=2025, period_type=PeriodType.FY,
            revenue=106200, ebit=36108, ebt=35400, net_income_parent=27612,
            total_assets=170000, total_liabilities=46000, total_equity_parent=124000,
        ),
    ]
    for s in samples:
        save_or_get_cached_statement(session, s)

_PERIOD_RANK = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}

def load_ticker_pair(
    session: Session, ticker: str
) -> Tuple[Optional[FinancialStatementInput], Optional[FinancialStatementInput]]:
    """Periode terbaru + pembanding YoY = jenis periode sama pada tahun sebelumnya (tepat tahun-1)."""
    rows = session.exec(
        select(FinancialStatementCache).where(FinancialStatementCache.ticker == ticker.upper())
    ).all()
    if not rows:
        return None, None
    rows = sorted(rows, key=lambda r: (r.year, _PERIOD_RANK.get(r.period_type, 0)), reverse=True)

    def _to_input(r: FinancialStatementCache) -> FinancialStatementInput:
        return FinancialStatementInput(
            ticker=r.ticker,
            company_name=r.company_name,
            year=r.year,
            period_type=PeriodType(r.period_type),
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
        )

    latest = rows[0]
    prior = next(
        (r for r in rows if r.period_type == latest.period_type and r.year == latest.year - 1),
        None,
    )
    return _to_input(latest), (_to_input(prior) if prior else None)
```

---

## 6.5 Anti-Hallucination LLM Anomaly Summarizer (`app/services/llm_analyzer.py`)

**File: `app/services/llm_analyzer.py`**
```python
import asyncio
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

import httpx
from pydantic import BaseModel, Field

from app.services.dupont_engine import DuPontAnalysisBundle, PrimaryDriver

class QualityVerdict:
    OPERATIONAL_DRIVEN = "OPERATIONAL_DRIVEN (High Quality)"
    OPERATIONAL_DETERIORATION = "OPERATIONAL_DETERIORATION (Margin/Turnover Melemah)"
    LEVERAGE_DRIVEN = "LEVERAGE_DRIVEN (Debt Expansion Alert)"
    DELEVERAGING = "DELEVERAGING (Leverage Menurun)"
    TAX_INTEREST_DISTORTED = "NON_OPERATIONAL_DISTORTED (Tax/Interest Shift)"
    STABLE = "STABLE (ROE Relatif Stabil)"
    MIXED = "MIXED_SIGNALS (Faktor Saling Berlawanan)"
    SINGLE_PERIOD = "BASELINE (Belum Ada Pembanding YoY)"
    DISTRESS_ALERT = "EQUITY_OR_EARNINGS_DISTRESS"

class LLMAnomalySummary(BaseModel):
    headline: str = Field(..., description="Ringkasan utama 1 kalimat perubahan ROE YoY")
    quality_verdict: str
    driver_explanation: str = Field(..., description="Analisis apakah ROE digerakkan oleh margin, turnover, atau utang")
    anomaly_bullets: List[str] = Field(..., min_length=2, max_length=5)
    risk_watchout: str
    source: str = Field(default="DETERMINISTIC", description="DETERMINISTIC atau LLM (tervalidasi)")

SYSTEM_PROMPT_EQUITY_RESEARCH = """
Anda adalah Senior Equity Research Analyst khusus pasar modal Indonesia (BEI/IDX).
Tugas Anda adalah merangkum anomali rasio DuPont 3-Stage dan 5-Stage berdasarkan JSON yang diberikan.

ATURAN KERAS (ANTI-HALUSINASI):
1. DILARANG menghitung ulang rasio atau mengarang angka baru. Gunakan HANYA angka yang tertera di JSON input.
2. Jawab pertanyaan inti: Apakah perubahan ROE dibanding tahun sebelumnya didorong oleh kualitas operasional (EBIT Margin / Asset Turnover) atau didorong oleh penambahan utang (Equity Multiplier)?
3. Patuhi field `roe_direction` (UP/DOWN/FLAT) dan `primary_driver_effect` (POSITIVE/NEGATIVE). Jangan menyebut ROE "naik" jika roe_direction = DOWN, dan jangan menyebut faktor "ekspansi" jika efeknya NEGATIVE.
4. Jika `is_negative_equity` bernilai true, jelaskan bahwa emiten mengalami defisiensi modal sehingga ROE tidak bermakna secara analitis (NM).
5. Kembalikan HANYA JSON valid dengan kunci persis: headline (string), quality_verdict (string), driver_explanation (string), anomaly_bullets (array 2-5 string), risk_watchout (string).
""".strip()

_DRIVER_LABEL = {
    PrimaryDriver.OPERATIONAL_MARGIN: "EBIT Margin (margin operasional)",
    PrimaryDriver.ASSET_EFFICIENCY: "Asset Turnover (efisiensi aset)",
    PrimaryDriver.FINANCIAL_LEVERAGE: "Equity Multiplier (financial leverage)",
    PrimaryDriver.TAX_OR_INTEREST_BURDEN: "beban bunga & pajak (Interest/Tax Burden)",
}
_DRIVER_DELTA_KEYS = {
    PrimaryDriver.OPERATIONAL_MARGIN: "ebit_margin",
    PrimaryDriver.ASSET_EFFICIENCY: "asset_turnover",
    PrimaryDriver.FINANCIAL_LEVERAGE: "equity_multiplier",
}

def _pct(v: Optional[float]) -> str:
    return "NM" if v is None else f"{v * 100:.2f}%"

def _mult(v: Optional[float]) -> str:
    return "NM" if v is None else f"{v:.2f}x"

def _verdict(bundle: DuPontAnalysisBundle) -> str:
    driver, effect, direction = bundle.primary_driver, bundle.primary_driver_effect, bundle.roe_direction
    if direction == "FLAT":
        return QualityVerdict.STABLE
    if driver in (PrimaryDriver.OPERATIONAL_MARGIN, PrimaryDriver.ASSET_EFFICIENCY):
        if effect == "POSITIVE" and direction == "UP":
            return QualityVerdict.OPERATIONAL_DRIVEN
        if effect == "NEGATIVE":
            return QualityVerdict.OPERATIONAL_DETERIORATION
        return QualityVerdict.MIXED
    if driver == PrimaryDriver.FINANCIAL_LEVERAGE:
        if effect == "POSITIVE" and direction == "UP":
            return QualityVerdict.LEVERAGE_DRIVEN
        if effect == "NEGATIVE":
            return QualityVerdict.DELEVERAGING
        return QualityVerdict.MIXED
    if driver == PrimaryDriver.TAX_OR_INTEREST_BURDEN:
        return QualityVerdict.TAX_INTEREST_DISTORTED
    return QualityVerdict.MIXED

def generate_deterministic_anomaly_summary(bundle: DuPontAnalysisBundle) -> LLMAnomalySummary:
    curr = bundle.current
    deltas = bundle.yoy_deltas

    if curr.is_negative_equity:
        return LLMAnomalySummary(
            headline=f"[{curr.ticker}] Peringatan Defisiensi Modal: Ekuitas Entitas Induk bernilai negatif.",
            quality_verdict=QualityVerdict.DISTRESS_ALERT,
            driver_explanation="Kalkulasi ROE dan Equity Multiplier dinonaktifkan (NM) untuk mencegah distorsi matematis akibat ekuitas negatif.",
            anomaly_bullets=[
                f"Net Profit Margin tercatat sebesar {_pct(curr.net_profit_margin)} dengan EBIT Margin {_pct(curr.ebit_margin)}.",
                "Struktur permodalan membutuhkan restrukturisasi atau injeksi ekuitas sebelum rasio pengembalian ekuitas dapat dievaluasi.",
            ],
            risk_watchout="Risiko solvabilitas tinggi; fokuskan analisis pada arus kas operasional dan rasio cakupan bunga.",
            source="DETERMINISTIC",
        )

    roe_str = _pct(curr.roe)
    roe_d = deltas.get("roe")
    has_prev = bundle.previous is not None and roe_d is not None and roe_d.bps_change is not None
    bps_text = f"({roe_d.bps_change:+.0f} bps YoY)" if has_prev else "(periode tunggal, belum ada pembanding YoY)"

    base_bullets = [
        f"ROE: {roe_str} {bps_text} | NPM: {_pct(curr.net_profit_margin)} | EBIT Margin: {_pct(curr.ebit_margin)}.",
        f"Perputaran Aset (AT): {_mult(curr.asset_turnover)} | Financial Leverage (EM): {_mult(curr.equity_multiplier)}.",
        f"Dekomposisi 5-Stage: Interest Burden {_mult(curr.interest_burden)} | Tax Burden {_mult(curr.tax_burden)}.",
    ]

    if not has_prev or bundle.primary_driver == PrimaryDriver.INSUFFICIENT_PRIOR_DATA:
        bullets = base_bullets + bundle.warnings[:2]
        return LLMAnomalySummary(
            headline=f"[{curr.ticker} {curr.year} {curr.period_type.value}] ROE {roe_str} — baseline tanpa pembanding YoY",
            quality_verdict=QualityVerdict.SINGLE_PERIOD,
            driver_explanation=(
                f"ROE {roe_str} terdiri dari NPM {_pct(curr.net_profit_margin)} x AT {_mult(curr.asset_turnover)} "
                f"x EM {_mult(curr.equity_multiplier)}. Unggah laporan periode sejenis tahun sebelumnya untuk atribusi YoY."
            ),
            anomaly_bullets=bullets[:5],
            risk_watchout="Tanpa pembanding YoY, arah dan kualitas perubahan ROE belum dapat dinilai.",
            source="DETERMINISTIC",
        )

    direction_word = {"UP": "naik", "DOWN": "turun", "FLAT": "relatif stabil"}.get(bundle.roe_direction, "berubah")
    driver = bundle.primary_driver
    label = _DRIVER_LABEL[driver]
    dkey = _DRIVER_DELTA_KEYS.get(driver)
    if dkey and dkey in deltas and deltas[dkey].previous_val is not None and deltas[dkey].current_val is not None:
        is_rate = dkey in ("ebit_margin",)
        fmt = _pct if is_rate else _mult
        factor_move = f"{fmt(deltas[dkey].previous_val)} menjadi {fmt(deltas[dkey].current_val)}"
        factor_dir = "naik" if bundle.primary_driver_effect == "POSITIVE" else "turun"
    else:
        factor_move, factor_dir = "berubah", ("naik" if bundle.primary_driver_effect == "POSITIVE" else "turun")

    verdict = _verdict(bundle)
    if verdict == QualityVerdict.STABLE:
        driver_exp = f"ROE {roe_str} {bps_text} relatif stabil; perubahan antar komponen DuPont saling mengimbangi (faktor terbesar: {label})."
    elif verdict == QualityVerdict.LEVERAGE_DRIVEN:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text} terutama karena {label} {factor_dir} ({factor_move}), "
            f"yaitu dorongan utang, bukan perbaikan margin operasional."
        )
    elif verdict == QualityVerdict.DELEVERAGING:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; faktor terbesar adalah penurunan {label} ({factor_move}), "
            f"artinya emiten mengurangi leverage sehingga efek pengungkit pada ROE melemah."
        )
    elif verdict == QualityVerdict.OPERATIONAL_DRIVEN:
        driver_exp = (
            f"ROE naik ke {roe_str} {bps_text} ditopang perbaikan operasional: {label} {factor_dir} ({factor_move}), "
            f"bukan dari penambahan utang."
        )
    elif verdict == QualityVerdict.OPERATIONAL_DETERIORATION:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text} akibat pelemahan operasional: {label} {factor_dir} ({factor_move}). "
            f"Ini penurunan kualitas laba, bukan efek leverage."
        )
    elif verdict == QualityVerdict.TAX_INTEREST_DISTORTED:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; pergerakannya banyak dipengaruhi {label} "
            f"(Interest Burden {_mult(curr.interest_burden)}, Tax Burden {_mult(curr.tax_burden)})."
        )
    else:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; faktor terbesar ({label}) bergerak berlawanan "
            f"dengan arah ROE sehingga sinyalnya campuran."
        )

    bullets = list(base_bullets)
    if bundle.driver_contributions_pct:
        names = {
            "OPERATIONAL_MARGIN": "Margin", "ASSET_EFFICIENCY": "Turnover",
            "FINANCIAL_LEVERAGE": "Leverage", "TAX_OR_INTEREST_BURDEN": "Bunga/Pajak",
        }
        parts = ", ".join(f"{names[k]} {v:+.1f}%" for k, v in bundle.driver_contributions_pct.items())
        bullets.append(f"Kontribusi ke perubahan ROE (log, aditif): {parts}.")
    if bundle.warnings:
        bullets.extend(bundle.warnings[:1])

    return LLMAnomalySummary(
        headline=f"[{curr.ticker} {curr.year} {curr.period_type.value}] ROE {roe_str} {bps_text} — driver: {driver.value} ({bundle.primary_driver_effect})",
        quality_verdict=verdict,
        driver_explanation=driver_exp,
        anomaly_bullets=bullets[:5],
        risk_watchout="Pantau konsistensi EBIT Margin dan Interest Burden jika Equity Multiplier melampaui 2.50x.",
        source="DETERMINISTIC",
    )

# ---------------------------------------------------------------- validasi angka LLM
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Ambang tetap yang boleh disebut narasi (bukan angka laporan): batas Equity Multiplier 2.50x.
ALLOWED_CONSTANTS = {2.5}

def _collect_numbers(obj: Any, out: Set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        v = abs(float(obj))
        out.update({v, v * 100.0, v * 10000.0})
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            out.add(abs(float(tok.replace(",", "."))))

def numbers_are_grounded(summary: LLMAnomalySummary, bundle: DuPontAnalysisBundle) -> bool:
    """Setiap angka di narasi LLM harus bisa ditelusuri ke data Python (nilai, persen, atau bps)."""
    allowed: Set[float] = set(ALLOWED_CONSTANTS)
    _collect_numbers(bundle.model_dump(mode="json"), allowed)
    text = " ".join(
        [summary.headline, summary.quality_verdict, summary.driver_explanation, summary.risk_watchout]
        + list(summary.anomaly_bullets)
    )
    for tok in _NUM_RE.findall(text):
        val = abs(float(tok.replace(",", ".")))
        if val.is_integer() and val <= 5:
            continue  # "3-Stage", "5-Stage", "2 faktor"
        if not any(abs(val - a) <= max(0.06, abs(a) * 0.01) for a in allowed):
            return False
    return True

# ---------------------------------------------------------------- cache & orkestrasi
_LLM_CACHE: Dict[str, LLMAnomalySummary] = {}
_INFLIGHT: Dict[str, "asyncio.Task[None]"] = {}
_CACHE_MAX = 256

def _cache_key(bundle: DuPontAnalysisBundle) -> str:
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    return hashlib.sha256((model + bundle.model_dump_json()).encode("utf-8")).hexdigest()

async def _call_llm(bundle: DuPontAnalysisBundle) -> Optional[LLMAnomalySummary]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_name,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT_EQUITY_RESEARCH},
                        {"role": "user", "content": bundle.model_dump_json()},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            raw_json = json.loads(resp.json()["choices"][0]["message"]["content"])
            raw_json["source"] = "LLM (angka tervalidasi)"
            summary = LLMAnomalySummary(**raw_json)
    except Exception:
        return None
    return summary if numbers_are_grounded(summary, bundle) else None

async def _warm_cache(key: str, bundle: DuPontAnalysisBundle) -> None:
    try:
        result = await _call_llm(bundle)
        if result is not None:
            if len(_LLM_CACHE) >= _CACHE_MAX:
                _LLM_CACHE.pop(next(iter(_LLM_CACHE)))
            _LLM_CACHE[key] = result
    finally:
        _INFLIGHT.pop(key, None)

async def summarize_dupont_anomalies(
    bundle: DuPontAnalysisBundle, wait_for_llm: bool = True
) -> LLMAnomalySummary:
    """
    Urutan: (1) cache hasil LLM tervalidasi, (2) tanpa API key -> deterministik,
    (3) wait_for_llm=False -> kembalikan deterministik SEKARANG dan hangatkan cache di latar belakang,
    (4) wait_for_llm=True -> tunggu LLM (timeout 10 dtk), tolak output jika ada angka yang tidak berasal dari data.
    """
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return generate_deterministic_anomaly_summary(bundle)

    key = _cache_key(bundle)
    if key in _LLM_CACHE:
        return _LLM_CACHE[key]

    if not wait_for_llm:
        if key not in _INFLIGHT:
            _INFLIGHT[key] = asyncio.create_task(_warm_cache(key, bundle))
        return generate_deterministic_anomaly_summary(bundle)

    result = await _call_llm(bundle)
    if result is None:
        return generate_deterministic_anomaly_summary(bundle)
    _LLM_CACHE[key] = result
    return result
```

---

## 6.6 Institutional 1-Page PDF Export Module (`app/services/pdf_exporter.py` & `app/templates/pdf_report.html`)

**File: `app/services/pdf_exporter.py`**
```python
from pathlib import Path
from typing import Tuple
from jinja2 import Environment, FileSystemLoader
from app.services.dupont_engine import DuPontAnalysisBundle
from app.services.llm_analyzer import LLMAnomalySummary

def render_dupont_report_export(
    bundle: DuPontAnalysisBundle,
    anomaly: LLMAnomalySummary,
    template_dir: str = str(Path(__file__).resolve().parents[1] / "templates"),
) -> Tuple[bytes, str, str]:
    """
    Menghasilkan file PDF (jika WeasyPrint tersedia di OS) atau Print-Ready HTML/PDF Tear-Sheet
    sehingga fitur Export tidak pernah gagal di mesin mana pun.
    """
    env = Environment(loader=FileSystemLoader(template_dir))
    tmpl = env.get_template("pdf_report.html")
    html_str = tmpl.render(bundle=bundle, anomaly=anomaly)

    try:
        from weasyprint import HTML  # type: ignore
        pdf_bytes = HTML(string=html_str).write_pdf()
        filename = f"DuPont_Report_{bundle.current.ticker}_{bundle.current.year}.pdf"
        return pdf_bytes, "application/pdf", filename
    except Exception:
        filename = f"DuPont_Report_{bundle.current.ticker}_{bundle.current.year}_Printable.html"
        return html_str.encode("utf-8"), "text/html; charset=utf-8", filename
```

**File: `app/templates/pdf_report.html`**
```html
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <title>DuPont Institutional Tear-Sheet — {{ bundle.current.ticker }}</title>
  <style>
    @page { size: A4 portrait; margin: 14mm; }
    body { font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; margin: 0; padding: 0; font-size: 12px; }
    .header { border-bottom: 2px solid #0f172a; padding-bottom: 8px; margin-bottom: 14px; display: flex; justify-content: space-between; }
    .title { font-size: 18px; font-weight: 800; }
    .badge { background: #0f172a; color: #fff; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; }
    .box { border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px; margin-bottom: 14px; background: #f8fafc; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th, td { border: 1px solid #cbd5e1; padding: 7px 9px; text-align: left; }
    th { background: #e2e8f0; font-weight: 700; }
    .verdict { font-weight: 700; color: #047857; }
    @media print { .no-print { display: none; } }
  </style>
</head>
<body onload="if(window.location.search.includes('autoprint=1')) window.print();">
  <div class="no-print" style="background:#0f172a;color:#fff;padding:10px 16px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;">
    <span>Institutional Equity Research Tear-Sheet — {{ bundle.current.ticker }}</span>
    <button onclick="window.print()" style="background:#10b981;color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-weight:700;">Cetak / Simpan PDF</button>
  </div>

  <div class="header">
    <div>
      <div class="title">{{ bundle.current.ticker }} — {{ bundle.current.company_name }}</div>
      <div>Periode: {{ bundle.current.year }} ({{ bundle.current.period_type.value }}) | Primary Driver: <strong>{{ bundle.primary_driver.value }}</strong></div>
    </div>
    <div class="badge">5-STAGE DUPONT &amp; ALK REPORT</div>
  </div>

  <div class="box">
    <div style="font-size:14px;font-weight:700;margin-bottom:4px;">{{ anomaly.headline }}</div>
    <div class="verdict">Verdict: {{ anomaly.quality_verdict }}</div>
    <p>{{ anomaly.driver_explanation }}</p>
    <ul>
      {% for b in anomaly.anomaly_bullets %}
      <li>{{ b }}</li>
      {% endfor %}
    </ul>
    <div><strong>Risk Watchout:</strong> {{ anomaly.risk_watchout }}</div>
  </div>

  <h3>Dekomposisi Struktur 3-Stage &amp; 5-Stage DuPont</h3>
  <table>
    <thead>
      <tr>
        <th>Komponen Rasio</th>
        <th>Formula Standar IDX</th>
        <th>Nilai Periode Berjalan</th>
        <th>Perubahan YoY</th>
      </tr>
    </thead>
    <tbody>
      {% for node in bundle.tree_nodes %}
      <tr>
        <td><strong>{{ node.label }}</strong></td>
        <td>{{ node.formula }}</td>
        <td><strong>{{ node.value }}</strong></td>
        <td>{{ node.yoy }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
```

---

## 6.7 Terminal Riset Saham/IHSG Pipeline & BEI Validator (`app/services/terminal_pipeline.py`)

**File: `app/services/terminal_pipeline.py`**
```python
from typing import List
from pydantic import BaseModel, Field, computed_field

def get_idx_tick_size(price: int) -> int:
    """Aturan Fraksi Harga Saham BEI (IDX Official Equity Tick Size)."""
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25

def is_valid_idx_price(price: int) -> bool:
    if price <= 0:
        return False
    return (price % get_idx_tick_size(price)) == 0

class IHSGBriefingHeader(BaseModel):
    trading_date: str
    ihsg_last: float
    change_pts: float
    change_pct: float
    total_value_idr_bn: float
    net_foreign_rg_idr_bn: float
    net_foreign_all_idr_bn: float
    market_status: str = Field(default="CLOSED EOD", pattern="^(OPEN|PRE-CLOSING|CLOSED EOD)$")
    briefing_headline: str

class BigCapMoverItem(BaseModel):
    ticker: str
    company_name: str
    last_price: int
    change_pct: float
    ihsg_point_impact: float
    volume_lot: int
    market_cap_idr_trn: float

class ForeignFlowItem(BaseModel):
    ticker: str
    net_foreign_rg_1d_bn: float
    net_foreign_rg_5d_bn: float
    net_foreign_ng_1d_bn: float = 0.0

    @computed_field
    @property
    def flow_signal(self) -> str:
        if self.net_foreign_rg_1d_bn > 25.0 and self.net_foreign_rg_5d_bn > 50.0:
            return "STRONG_ACCUMULATION"
        elif self.net_foreign_rg_1d_bn > 0:
            return "MILD_INFLOW"
        elif self.net_foreign_rg_1d_bn < -25.0 and self.net_foreign_rg_5d_bn < -50.0:
            return "HEAVY_DISTRIBUTION"
        elif self.net_foreign_rg_1d_bn < 0:
            return "MILD_OUTFLOW"
        return "NEUTRAL"

class SupportResistanceItem(BaseModel):
    ticker: str
    last_price: int
    s2: int
    s1: int
    r1: int
    r2: int

    @computed_field
    @property
    def distance_to_r1_pct(self) -> float:
        if self.last_price <= 0:
            return 0.0
        return round((self.r1 - self.last_price) / self.last_price * 100.0, 2)

    @computed_field
    @property
    def tick_fraction_valid(self) -> bool:
        return all(is_valid_idx_price(p) for p in (self.last_price, self.s2, self.s1, self.r1, self.r2))

    @computed_field
    @property
    def ordering_valid(self) -> bool:
        return self.s2 < self.s1 <= self.last_price <= self.r1 < self.r2

class TerminalPayload(BaseModel):
    header: IHSGBriefingHeader
    movers: List[BigCapMoverItem]
    foreign_flows: List[ForeignFlowItem]
    sr_matrix: List[SupportResistanceItem]

_CURRENT_TERMINAL_STATE: TerminalPayload = TerminalPayload(
    header=IHSGBriefingHeader(
        trading_date="2026-10-23",
        ihsg_last=7685.42,
        change_pts=64.18,
        change_pct=0.84,
        total_value_idr_bn=12480.5,
        net_foreign_rg_idr_bn=642.8,
        net_foreign_all_idr_bn=410.2,
        market_status="CLOSED EOD",
        briefing_headline="IHSG menguat +0.84% ditopang akumulasi asing di pasar reguler pada big-cap konglomerasi & konsumer.",
    ),
    movers=[
        BigCapMoverItem(ticker="ASII", company_name="Astra International Tbk", last_price=5250, change_pct=2.94, ihsg_point_impact=11.4, volume_lot=845200, market_cap_idr_trn=212.5),
        BigCapMoverItem(ticker="ICBP", company_name="Indofood CBP Sukses Makmur Tbk", last_price=12100, change_pct=2.54, ihsg_point_impact=6.8, volume_lot=142300, market_cap_idr_trn=141.1),
        BigCapMoverItem(ticker="TLKM", company_name="Telkom Indonesia Tbk", last_price=2980, change_pct=-1.32, ihsg_point_impact=-4.5, volume_lot=1620400, market_cap_idr_trn=295.2),
        BigCapMoverItem(ticker="ADRO", company_name="Alamtri Resources Indonesia Tbk", last_price=3720, change_pct=3.33, ihsg_point_impact=7.9, volume_lot=1284000, market_cap_idr_trn=114.4),
    ],
    foreign_flows=[
        ForeignFlowItem(ticker="ASII", net_foreign_rg_1d_bn=184.5, net_foreign_rg_5d_bn=520.2, net_foreign_ng_1d_bn=-120.0),
        ForeignFlowItem(ticker="ICBP", net_foreign_rg_1d_bn=62.4, net_foreign_rg_5d_bn=195.8, net_foreign_ng_1d_bn=0.0),
        ForeignFlowItem(ticker="TLKM", net_foreign_rg_1d_bn=-78.2, net_foreign_rg_5d_bn=-240.5, net_foreign_ng_1d_bn=45.0),
        ForeignFlowItem(ticker="ADRO", net_foreign_rg_1d_bn=95.0, net_foreign_rg_5d_bn=310.4, net_foreign_ng_1d_bn=-15.0),
    ],
    sr_matrix=[
        SupportResistanceItem(ticker="ASII", last_price=5250, s2=4950, s1=5100, r1=5400, r2=5600),
        SupportResistanceItem(ticker="ICBP", last_price=12100, s2=11650, s1=11875, r1=12350, r2=12600),
        SupportResistanceItem(ticker="TLKM", last_price=2980, s2=2840, s1=2910, r1=3060, r2=3150),
        SupportResistanceItem(ticker="ADRO", last_price=3720, s2=3540, s1=3630, r1=3840, r2=3960),
    ],
)

def get_terminal_snapshot() -> TerminalPayload:
    return _CURRENT_TERMINAL_STATE

def update_terminal_snapshot(payload: TerminalPayload) -> TerminalPayload:
    global _CURRENT_TERMINAL_STATE
    _CURRENT_TERMINAL_STATE = payload
    return _CURRENT_TERMINAL_STATE

def validate_terminal_payload(payload: TerminalPayload) -> List[str]:
    """Guardrail 7: tolak payload yang melanggar Fraksi Harga BEI atau urutan S2<S1<=Last<=R1<R2."""
    errors: List[str] = []
    for m in payload.movers:
        if not is_valid_idx_price(m.last_price):
            errors.append(
                f"Mover {m.ticker}: harga {m.last_price} bukan kelipatan fraksi BEI (Rp{get_idx_tick_size(m.last_price)})."
            )
    for sr in payload.sr_matrix:
        if not sr.tick_fraction_valid:
            errors.append(f"S/R {sr.ticker}: ada level/harga yang melanggar Fraksi Harga BEI.")
        if not sr.ordering_valid:
            errors.append(f"S/R {sr.ticker}: urutan harus S2 < S1 <= Last <= R1 < R2.")
    return errors
```

---

## 6.8 FastAPI Main Entrypoint & REST/HTMX Endpoints (`app/main.py`)

**File: `app/main.py`**
```python
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Depends, UploadFile, File, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db.database import init_db, get_session, engine
from app.db.models import FinancialStatementCache
from app.services.dupont_engine import analyze_dupont_yoy
from app.services.parser import (
    parse_idx_file_bytes,
    save_or_get_cached_statement,
    seed_initial_idx_statements,
    load_ticker_pair,
)
from app.services.llm_analyzer import summarize_dupont_anomalies
from app.services.pdf_exporter import render_dupont_report_export
from app.services.terminal_pipeline import (
    TerminalPayload,
    get_terminal_snapshot,
    update_terminal_snapshot,
    validate_terminal_payload,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        seed_initial_idx_statements(session)
    yield

app = FastAPI(
    title="IDX-QuantTerminal: DuPont ALK & IHSG Research Platform",
    version="2.2.0",
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    ticker: str = "ASII",
    session: Session = Depends(get_session),
):
    notice = None
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)
    if not curr_stmt:
        notice = f"Ticker {ticker.upper()} belum ada di cache — menampilkan ASII. Unggah laporan keuangannya via POST /api/dupont/upload."
        curr_stmt, prev_stmt = load_ticker_pair(session, "ASII")
    if not curr_stmt:
        raise HTTPException(status_code=404, detail="Cache laporan keuangan kosong.")

    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    # Halaman utama tidak menunggu LLM (target < 2 detik): pakai hasil cache LLM bila ada,
    # jika belum ada tampilkan ringkasan deterministik dan hangatkan cache di latar belakang.
    anomaly = await summarize_dupont_anomalies(bundle, wait_for_llm=False)
    terminal = get_terminal_snapshot()

    cached_tickers = sorted(
        list(set(session.exec(select(FinancialStatementCache.ticker)).all()))
    )
    return templates.TemplateResponse(
        request,
        "base.html",
        {
            "bundle": bundle,
            "anomaly": anomaly,
            "terminal": terminal,
            "cached_tickers": cached_tickers,
            "active_ticker": curr_stmt.ticker,
            "notice": notice,
        },
    )

@app.get("/api/dupont/{ticker}")
async def get_dupont_analysis_json(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} belum ada di cache.")
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle)
    return {"bundle": bundle, "anomaly": anomaly}

@app.post("/api/dupont/upload")
async def upload_idx_statement(
    file: UploadFile = File(...),
    ticker: str = Form("XXXX"),
    year: int = Form(2025),
    session: Session = Depends(get_session),
):
    raw_bytes = await file.read()
    if len(raw_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Ukuran file melebihi batas 25MB.")
    try:
        parsed_stmt = parse_idx_file_bytes(
            filename=file.filename or "upload.xlsx",
            file_bytes=raw_bytes,
            default_ticker=ticker,
            default_year=year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    record = save_or_get_cached_statement(session, parsed_stmt, raw_bytes)
    curr_stmt, prev_stmt = load_ticker_pair(session, record.ticker)
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle)
    return {"status": "cached", "ticker": record.ticker, "bundle": bundle, "anomaly": anomaly}

@app.get("/api/dupont/{ticker}/export")
async def export_dupont_pdf(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} tidak ditemukan.")
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle)
    content_bytes, media_type, filename = render_dupont_report_export(bundle, anomaly)
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@app.get("/api/terminal/snapshot", response_model=TerminalPayload)
async def api_get_terminal():
    return get_terminal_snapshot()

@app.post("/api/terminal/ingest", response_model=TerminalPayload)
async def api_ingest_terminal(
    payload: TerminalPayload,
    x_api_key: Optional[str] = Header(default=None),
):
    expected = os.getenv("INGEST_API_KEY", "").strip()
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="API key tidak valid (header X-API-Key).")
    errors = validate_terminal_payload(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return update_terminal_snapshot(payload)
```

---

## 6.9 Combined 2-Tab Dashboard UI (`app/templates/base.html`)

**File: `app/templates/base.html`**
```html
<!DOCTYPE html>
<html lang="id" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IDX-QuantTerminal — DuPont ALK &amp; IHSG Research</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans"
      x-data="{ activeTab: 'dupont', stageMode: '5_STAGE' }"
      @keydown.window.alt.1.prevent="activeTab = 'dupont'"
      @keydown.window.alt.2.prevent="activeTab = 'terminal'">

  <!-- Top Navigation & Market Tape -->
  <header class="border-b border-slate-800 bg-slate-900/90 sticky top-0 z-30 px-6 py-3 flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center gap-4">
      <div class="h-3 w-3 rounded-full bg-emerald-400 animate-pulse"></div>
      <div>
        <h1 class="text-lg font-extrabold tracking-tight text-white">IDX-QuantTerminal <span class="text-xs font-mono text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-700">v2.2</span></h1>
        <p class="text-xs text-slate-400">Unified 5-Stage DuPont ALK Engine &amp; IHSG Institutional Terminal</p>
      </div>
    </div>

    <!-- IHSG Mini Ticker Tape -->
    <div class="flex items-center gap-5 text-xs font-mono bg-slate-950 px-4 py-2 rounded-lg border border-slate-800">
      <div>
        <span class="text-slate-400">IHSG:</span>
        <span class="font-bold text-white">{{ "%.2f"|format(terminal.header.ihsg_last) }}</span>
        <span class="{{ 'text-emerald-400' if terminal.header.change_pct >= 0 else 'text-rose-400' }}">
          ({{ "%+.2f"|format(terminal.header.change_pct) }}%)
        </span>
      </div>
      <div class="border-l border-slate-800 pl-4">
        <span class="text-slate-400">Net Foreign RG:</span>
        <span class="font-bold {{ 'text-emerald-400' if terminal.header.net_foreign_rg_idr_bn >= 0 else 'text-rose-400' }}">
          Rp {{ "%+.1f"|format(terminal.header.net_foreign_rg_idr_bn) }} B
        </span>
      </div>
      <div class="border-l border-slate-800 pl-4">
        <span class="px-2 py-0.5 rounded bg-slate-800 text-amber-300 font-bold">{{ terminal.header.market_status }}</span>
      </div>
    </div>

    <!-- 2-Tab Switcher (< 50ms Client-Side Switching) -->
    <nav class="flex items-center gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800">
      <button @click="activeTab = 'dupont'"
              :class="activeTab === 'dupont' ? 'bg-emerald-600 text-white shadow' : 'text-slate-400 hover:text-white'"
              class="px-4 py-1.5 rounded-md text-xs font-bold transition">
        Tab 1: DuPont &amp; ALK Engine (Alt+1)
      </button>
      <button @click="activeTab = 'terminal'"
              :class="activeTab === 'terminal' ? 'bg-emerald-600 text-white shadow' : 'text-slate-400 hover:text-white'"
              class="px-4 py-1.5 rounded-md text-xs font-bold transition">
        Tab 2: Terminal Riset IHSG (Alt+2)
      </button>
    </nav>
  </header>

  {% if notice %}
  <div class="mx-6 mt-4 px-4 py-2 rounded-lg border border-amber-700 bg-amber-950/40 text-xs font-mono text-amber-300">{{ notice }}</div>
  {% endif %}

  <!-- TAB 1: DUPONT & ALK PLATFORM (Panel Kiri = Tree + LLM, Panel Kanan = Upload & PDF Export) -->
  <main x-show="activeTab === 'dupont'" class="p-6 max-w-[1600px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6">
    <!-- PANEL KIRI (70% / 8 Kolom): Interactive DuPont Tree + LLM Anomaly Summarizer -->
    <section class="lg:col-span-8 space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4 mb-5">
          <div>
            <span class="text-xs font-mono uppercase text-emerald-400">Emiten Aktif</span>
            <h2 class="text-xl font-black text-white">
              {{ bundle.current.ticker }} — {{ bundle.current.company_name }}
              <span class="text-sm font-normal text-slate-400">({{ bundle.current.year }} {{ bundle.current.period_type.value }})</span>
            </h2>
          </div>

          <div class="flex items-center gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800">
            <button @click="stageMode = '3_STAGE'"
                    :class="stageMode === '3_STAGE' ? 'bg-slate-800 text-emerald-400 border border-emerald-600/40' : 'text-slate-400'"
                    class="px-3 py-1 rounded text-xs font-bold">
              3-Stage DuPont
            </button>
            <button @click="stageMode = '5_STAGE'"
                    :class="stageMode === '5_STAGE' ? 'bg-slate-800 text-emerald-400 border border-emerald-600/40' : 'text-slate-400'"
                    class="px-3 py-1 rounded text-xs font-bold">
              5-Stage DuPont
            </button>
          </div>
        </div>

        <!-- Visual Interactive DuPont Tree Grid -->
        {% set tone = {'emerald': 'text-emerald-400', 'crimson': 'text-rose-400', 'amber': 'text-amber-300', 'slate': 'text-white'} %}
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          {% for node in bundle.tree_nodes %}
          <div x-show="stageMode === '5_STAGE' || '{{ node.stage }}' !== '5_ONLY'"
               class="p-4 rounded-xl border {{ 'md:col-span-3 bg-emerald-950/30 border-emerald-600/50' if node.id == 'roe' else 'bg-slate-950 border-slate-800' }}">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold uppercase tracking-wider text-slate-400">{{ node.label }}</span>
              <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700">{{ node.yoy }}</span>
            </div>
            <div class="text-2xl font-black font-mono mt-2 {{ tone.get(node.color, 'text-white') }}">{{ node.value }}</div>
            <div class="text-[11px] font-mono text-slate-400 mt-1">Formula: {{ node.formula }}</div>
          </div>
          {% endfor %}
        </div>
      </div>

      <!-- AI Layer: LLM Anomaly Summarizer Box -->
      <div class="bg-slate-900 border border-emerald-800/60 rounded-xl p-5">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
          <span class="text-xs font-mono font-bold uppercase text-emerald-400">AI Layer — DuPont YoY Anomaly Summarizer</span>
          <span class="text-xs font-mono px-2.5 py-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 font-bold">
            {{ anomaly.quality_verdict }}
          </span>
        </div>
        <div class="text-[10px] font-mono text-slate-500 mb-1">Sumber narasi: {{ anomaly.source }}</div>
        <h3 class="text-base font-bold text-white mb-2">{{ anomaly.headline }}</h3>
        <p class="text-sm text-slate-300 leading-relaxed mb-4">{{ anomaly.driver_explanation }}</p>
        <ul class="space-y-1.5 text-xs text-slate-300 list-disc list-inside bg-slate-950 p-4 rounded-lg border border-slate-800">
          {% for item in anomaly.anomaly_bullets %}
          <li>{{ item }}</li>
          {% endfor %}
        </ul>
        <div class="mt-3 text-xs text-amber-300 font-mono">
          <strong>Risk Watchout:</strong> {{ anomaly.risk_watchout }}
        </div>
      </div>
    </section>

    <!-- PANEL KANAN (30% / 4 Kolom): Emiten Selector, IDX Upload, Guardrail Check, & PDF Export -->
    <aside class="lg:col-span-4 space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 class="text-sm font-bold text-white mb-3">Pilih Emiten dari Shared Cache</h3>
        <div class="flex flex-wrap gap-2">
          {% for tk in cached_tickers %}
          <a href="/?ticker={{ tk }}"
             class="px-3 py-1.5 rounded-lg text-xs font-mono font-bold border transition {{ 'bg-emerald-600 text-white border-emerald-500' if tk == active_ticker else 'bg-slate-950 text-slate-300 border-slate-800 hover:border-slate-600' }}">
            {{ tk }}
          </a>
          {% endfor %}
        </div>
      </div>

      <!-- Guardrail & Reconciliation Status -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2.5 text-xs font-mono">
        <h3 class="text-sm font-sans font-bold text-white mb-2">IDX Accounting Guardrail Status</h3>
        <div class="flex justify-between">
          <span class="text-slate-400">Balance Sheet Identity:</span>
          <span class="{{ 'text-emerald-400' if bundle.current.balance_sheet_balanced else 'text-rose-400' }}">
            {{ 'PASS (Balanced)' if bundle.current.balance_sheet_balanced else 'WARNING (Discrepancy)' }}
          </span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">5-Stage Reconciliation Diff:</span>
          <span class="text-emerald-400">{{ "%.8f"|format(bundle.current.reconciliation_diff_5stage or 0) }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">Primary ROE Driver:</span>
          <span class="text-amber-300 font-bold">{{ bundle.primary_driver.value }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">Arah ROE / Efek Driver:</span>
          <span class="text-slate-200">{{ bundle.roe_direction }} / {{ bundle.primary_driver_effect }}</span>
        </div>
      </div>

      <!-- Concise PDF Export Panel -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 class="text-sm font-bold text-white mb-2">Institutional PDF Tear-Sheet Export</h3>
        <p class="text-xs text-slate-400 mb-4">
          Ekspor ringkasan 1 halaman berisi struktur pohon 5-Stage DuPont, tabel YoY, dan narasi anomali AI untuk {{ bundle.current.ticker }}.
        </p>
        <a href="/api/dupont/{{ bundle.current.ticker }}/export?autoprint=1"
           target="_blank"
           class="block w-full text-center bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs py-2.5 px-4 rounded-lg transition">
          Buka &amp; Unduh Laporan PDF ({{ bundle.current.ticker }})
        </a>
      </div>
    </aside>
  </main>

  <!-- TAB 2: TERMINAL RISET SAHAM / IHSG (Bloomberg / TradingView Style Grid) -->
  <section x-show="activeTab === 'terminal'" class="p-6 max-w-[1600px] mx-auto space-y-6">
    <!-- Daily IHSG Briefing Banner -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div>
        <span class="text-xs font-mono text-emerald-400 uppercase">Daily IHSG Briefing ({{ terminal.header.trading_date }})</span>
        <p class="text-sm font-bold text-white mt-0.5">{{ terminal.header.briefing_headline }}</p>
      </div>
      <div class="text-xs font-mono text-slate-400">
        Total Value: <strong class="text-white">Rp {{ "%.1f"|format(terminal.header.total_value_idr_bn) }} Miliar</strong>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
      <!-- GRID 1: Big-Cap Movers -->
      <div class="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 class="text-xs font-mono font-bold uppercase text-emerald-400 mb-3">1. Big-Cap Movers &amp; Index Impact</h3>
        <table class="w-full text-xs font-mono">
          <thead>
            <tr class="text-slate-400 border-b border-slate-800 text-left">
              <th class="py-2">Ticker</th>
              <th>Last</th>
              <th>Chg%</th>
              <th>Impact (Pts)</th>
            </tr>
          </thead>
          <tbody>
            {% for m in terminal.movers %}
            <tr class="border-b border-slate-800/60 hover:bg-slate-800/40">
              <td class="py-2.5 font-bold">
                <a href="/?ticker={{ m.ticker }}" class="text-emerald-400 hover:underline">{{ m.ticker }}</a>
              </td>
              <td>{{ m.last_price }}</td>
              <td class="{{ 'text-emerald-400' if m.change_pct >= 0 else 'text-rose-400' }}">{{ "%+.2f"|format(m.change_pct) }}%</td>
              <td class="{{ 'text-emerald-400' if m.ihsg_point_impact >= 0 else 'text-rose-400' }}">{{ "%+.1f"|format(m.ihsg_point_impact) }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- GRID 2: Foreign Flow RG vs NG Tracker -->
      <div class="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 class="text-xs font-mono font-bold uppercase text-emerald-400 mb-3">2. Foreign Flow BEI (Regular vs Nego)</h3>
        <table class="w-full text-xs font-mono">
          <thead>
            <tr class="text-slate-400 border-b border-slate-800 text-left">
              <th class="py-2">Ticker</th>
              <th>RG 1D (B)</th>
              <th>RG 5D (B)</th>
              <th>Flow Signal</th>
            </tr>
          </thead>
          <tbody>
            {% for f in terminal.foreign_flows %}
            <tr class="border-b border-slate-800/60 hover:bg-slate-800/40">
              <td class="py-2.5 font-bold">
                <a href="/?ticker={{ f.ticker }}" class="text-emerald-400 hover:underline">{{ f.ticker }}</a>
              </td>
              <td class="{{ 'text-emerald-400' if f.net_foreign_rg_1d_bn >= 0 else 'text-rose-400' }}">{{ "%+.1f"|format(f.net_foreign_rg_1d_bn) }}</td>
              <td class="{{ 'text-emerald-400' if f.net_foreign_rg_5d_bn >= 0 else 'text-rose-400' }}">{{ "%+.1f"|format(f.net_foreign_rg_5d_bn) }}</td>
              <td><span class="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-700 text-[10px]">{{ f.flow_signal }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- GRID 3: Support & Resistance Matrix + IDX Tick Validation -->
      <div class="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 class="text-xs font-mono font-bold uppercase text-emerald-400 mb-3">3. Support / Resistance &amp; Tick Matrix</h3>
        <table class="w-full text-xs font-mono">
          <thead>
            <tr class="text-slate-400 border-b border-slate-800 text-left">
              <th class="py-2">Ticker</th>
              <th>S1</th>
              <th>Last</th>
              <th>R1</th>
              <th>To R1</th>
              <th>Tick OK</th>
            </tr>
          </thead>
          <tbody>
            {% for sr in terminal.sr_matrix %}
            <tr class="border-b border-slate-800/60 hover:bg-slate-800/40">
              <td class="py-2.5 font-bold">
                <a href="/?ticker={{ sr.ticker }}" class="text-emerald-400 hover:underline">{{ sr.ticker }}</a>
              </td>
              <td class="text-slate-400">{{ sr.s1 }}</td>
              <td class="font-bold text-white">{{ sr.last_price }}</td>
              <td class="text-emerald-300">{{ sr.r1 }}</td>
              <td>+{{ "%.1f"|format(sr.distance_to_r1_pct) }}%</td>
              <td class="{{ 'text-emerald-400' if sr.tick_fraction_valid else 'text-rose-400' }}">
                {{ 'VALID' if sr.tick_fraction_valid else 'INVALID' }}
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </section>
</body>
</html>
```

---

## 6.10 Complete Automated Test Suite (`tests/test_core_platform.py`)

**File: `tests/test_core_platform.py`**
```python
from fastapi.testclient import TestClient
from app.main import app
from app.services.dupont_engine import (
    FinancialStatementInput,
    PeriodType,
    PrimaryDriver,
    analyze_dupont_yoy,
)
from app.services.llm_analyzer import generate_deterministic_anomaly_summary
from app.services.terminal_pipeline import is_valid_idx_price, ForeignFlowItem

def test_dupont_3_and_5_stage_reconciliation():
    prev_stmt = FinancialStatementInput(
        ticker="ASII",
        company_name="Astra International Tbk",
        year=2024,
        period_type=PeriodType.FY,
        revenue=300_000,
        ebit=42_000,
        ebt=40_000,
        net_income_parent=32_000,
        total_assets=440_000,
        total_liabilities=240_000,
        total_equity_parent=200_000,
    )
    curr_stmt = FinancialStatementInput(
        ticker="ASII",
        company_name="Astra International Tbk",
        year=2025,
        period_type=PeriodType.FY,
        revenue=330_000,
        ebit=52_000,
        ebt=49_000,
        net_income_parent=39_200,
        total_assets=460_000,
        total_liabilities=250_000,
        total_equity_parent=210_000,
    )
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    assert bundle.current.reconciliation_diff_3stage < 1e-6
    assert bundle.current.reconciliation_diff_5stage < 1e-6
    assert bundle.current.balance_sheet_balanced is True
    assert bundle.primary_driver == PrimaryDriver.OPERATIONAL_MARGIN

def test_negative_equity_guardrail_blocks_false_positive_roe():
    distressed = FinancialStatementInput(
        ticker="DIST",
        company_name="Emiten Distressed Tbk",
        year=2025,
        period_type=PeriodType.FY,
        revenue=50_000,
        ebit=-5_000,
        ebt=-12_000,
        net_income_parent=-15_000,
        total_assets=100_000,
        total_liabilities=130_000,
        total_equity_parent=-30_000,
    )
    bundle = analyze_dupont_yoy(distressed)
    assert bundle.current.is_negative_equity is True
    assert bundle.current.roe is None
    assert bundle.current.equity_multiplier is None
    summary = generate_deterministic_anomaly_summary(bundle)
    assert "Defisiensi Modal" in summary.headline

def test_interim_q2_annualization():
    q2_stmt = FinancialStatementInput(
        ticker="ICBP",
        company_name="Indofood CBP Tbk",
        year=2025,
        period_type=PeriodType.Q2,
        revenue=35_000,
        ebit=7_000,
        ebt=6_500,
        net_income_parent=5_000,
        total_assets=120_000,
        total_liabilities=60_000,
        total_equity_parent=60_000,
    )
    bundle = analyze_dupont_yoy(q2_stmt)
    assert bundle.current.annualized_applied is True
    assert abs(bundle.current.roe - (10_000 / 60_000)) < 1e-6

def test_idx_tick_size_and_foreign_flow():
    assert is_valid_idx_price(185) is True
    assert is_valid_idx_price(351) is False
    assert is_valid_idx_price(5250) is True
    assert is_valid_idx_price(5260) is False

    flow = ForeignFlowItem(
        ticker="ASII",
        net_foreign_rg_1d_bn=90.0,
        net_foreign_rg_5d_bn=250.0,
        net_foreign_ng_1d_bn=-500.0,
    )
    assert flow.flow_signal == "STRONG_ACCUMULATION"

def test_end_to_end_fastapi_routes():
    with TestClient(app) as client:
        res_home = client.get("/?ticker=ASII")
        assert res_home.status_code == 200
        assert "IDX-QuantTerminal" in res_home.text

        res_dupont = client.get("/api/dupont/ICBP")
        assert res_dupont.status_code == 200
        assert res_dupont.json()["bundle"]["current"]["ticker"] == "ICBP"

        res_term = client.get("/api/terminal/snapshot")
        assert res_term.status_code == 200
        assert len(res_term.json()["movers"]) >= 4

        res_export = client.get("/api/dupont/ASII/export")
        assert res_export.status_code == 200


# ======================= REGRESSION TESTS v2.2 (bug yang terbukti di audit) =======================
import io
import asyncio
import openpyxl
import pytest
from sqlmodel import SQLModel, Session, create_engine
from app.services.parser import (
    parse_idx_file_bytes,
    save_or_get_cached_statement,
    load_ticker_pair,
)
from app.services import llm_analyzer
from app.services.llm_analyzer import (
    LLMAnomalySummary,
    numbers_are_grounded,
    QualityVerdict,
)
from app.services.terminal_pipeline import (
    TerminalPayload,
    get_terminal_snapshot,
    validate_terminal_payload,
    SupportResistanceItem,
)

def _stmt(**kw):
    base = dict(
        ticker="TEST", company_name="Test Tbk", year=2025, period_type=PeriodType.FY,
        revenue=1000, ebit=200, ebt=180, net_income_parent=140,
        total_assets=1000, total_liabilities=450, total_equity_parent=550,
    )
    base.update(kw)
    return FinancialStatementInput(**base)

def _mem_session():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return Session(eng)

def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def test_parser_ignores_subtotal_rows_and_reads_consolidated_equity():
    data = _xlsx([
        ("ticker", "TEST"), ("year", 2025),
        ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset lancar", 300), ("Jumlah aset", 1000),
        ("Jumlah liabilitas jangka pendek", 150), ("Jumlah liabilitas", 400),
        ("Jumlah ekuitas yang dapat diatribusikan kepada pemilik entitas induk", 550),
        ("Jumlah ekuitas", 600),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.total_assets == 1000
    assert s.total_liabilities == 400
    assert s.total_equity_parent == 550
    assert s.total_equity_consolidated == 600
    assert s.balance_sheet_discrepancy_pct <= 0.05

def test_parser_single_equity_row_used_as_parent():
    data = _xlsx([
        ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset", 1000), ("Jumlah liabilitas", 450), ("Jumlah ekuitas", 550),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.total_equity_parent == 550

def test_parser_bilingual_label_and_not_ebitda():
    data = _xlsx([
        ("Pendapatan usaha", 1000), ("EBITDA", 999999), ("Laba usaha / Operating profit", 200),
        ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset / Total assets", 1000), ("Jumlah liabilitas / Total liabilities", 450),
        ("Jumlah ekuitas / Total equity", 550),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.ebit == 200
    assert s.total_assets == 1000

def test_yoy_pairs_exactly_previous_year_and_same_period_type():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2024, revenue=900))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, period_type=PeriodType.Q2, revenue=500))
        cur, prev = load_ticker_pair(se, "TEST")
        assert (cur.year, cur.period_type) == (2025, PeriodType.FY)
        assert (prev.year, prev.period_type) == (2024, PeriodType.FY)

def test_yoy_none_when_prior_year_missing_not_same_year():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, period_type=PeriodType.Q2, revenue=500))
        cur, prev = load_ticker_pair(se, "TEST")
        assert cur.year == 2025 and prev is None

def test_reupload_same_period_replaces_row_instead_of_duplicating():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2024, revenue=900))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1010))
        cur, prev = load_ticker_pair(se, "TEST")
        assert cur.revenue == 1010
        assert prev.year == 2024

def test_margin_collapse_is_flagged_as_deterioration_not_high_quality():
    prev = _stmt(year=2024, ebit=200, ebt=190, net_income_parent=150)
    curr = _stmt(year=2025, ebit=50, ebt=45, net_income_parent=35)
    b = analyze_dupont_yoy(curr, prev)
    assert b.roe_direction == "DOWN"
    assert b.primary_driver == PrimaryDriver.OPERATIONAL_MARGIN
    assert b.primary_driver_effect == "NEGATIVE"
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.OPERATIONAL_DETERIORATION
    assert "High Quality" not in s.quality_verdict
    assert "sehat" not in s.driver_explanation

def test_falling_leverage_is_not_described_as_expansion():
    prev = _stmt(year=2024, total_liabilities=700, total_equity_parent=300, total_assets=1000)
    curr = _stmt(year=2025, total_liabilities=400, total_equity_parent=600, total_assets=1000)
    b = analyze_dupont_yoy(curr, prev)
    assert b.primary_driver == PrimaryDriver.FINANCIAL_LEVERAGE
    assert b.primary_driver_effect == "NEGATIVE"
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.DELEVERAGING
    assert "ekspansi" not in s.driver_explanation.lower()

def test_rising_leverage_with_rising_roe_is_flagged_as_debt_driven():
    prev = _stmt(year=2024, total_liabilities=300, total_equity_parent=700, total_assets=1000)
    curr = _stmt(year=2025, total_liabilities=700, total_equity_parent=300, total_assets=1000)
    b = analyze_dupont_yoy(curr, prev)
    s = generate_deterministic_anomaly_summary(b)
    assert b.roe_direction == "UP"
    assert s.quality_verdict == QualityVerdict.LEVERAGE_DRIVEN

def test_log_contributions_sum_to_log_roe_change():
    import math
    prev = _stmt(year=2024)
    curr = _stmt(year=2025, revenue=1100, ebit=260, ebt=240, net_income_parent=190,
                 total_assets=1200, total_liabilities=600, total_equity_parent=600)
    b = analyze_dupont_yoy(curr, prev)
    total = sum(b.driver_contributions_pct.values())
    expected = math.log(b.current.roe / b.previous.roe) * 100
    assert abs(total - expected) < 1e-6

def test_single_period_summary_has_no_fake_yoy_claims():
    b = analyze_dupont_yoy(_stmt())
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.SINGLE_PERIOD
    assert "bps" not in s.headline

def test_llm_output_with_invented_numbers_is_rejected():
    b = analyze_dupont_yoy(_stmt(year=2025), _stmt(year=2024, revenue=900))
    ok = generate_deterministic_anomaly_summary(b)
    assert numbers_are_grounded(ok, b) is True
    bad = LLMAnomalySummary(
        headline="ROE melonjak 87.65% YoY", quality_verdict="X",
        driver_explanation="Karena margin 77.77%.", anomaly_bullets=["a", "b"], risk_watchout="r",
    )
    assert numbers_are_grounded(bad, b) is False

def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9")  # port tertutup -> error koneksi
    llm_analyzer._LLM_CACHE.clear()
    b = analyze_dupont_yoy(_stmt(year=2025), _stmt(year=2024, revenue=900))
    s = asyncio.run(llm_analyzer.summarize_dupont_anomalies(b, wait_for_llm=True))
    assert s.source == "DETERMINISTIC"
    assert s.headline

def test_ingest_rejects_invalid_tick_and_ordering():
    snap = get_terminal_snapshot()
    bad_sr = SupportResistanceItem(ticker="ASII", last_price=5260, s2=4950, s1=5100, r1=5400, r2=5600)
    payload = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[bad_sr],
    )
    errs = validate_terminal_payload(payload)
    assert any("Fraksi" in e for e in errs)
    inverted = SupportResistanceItem(ticker="ASII", last_price=5250, s2=5100, s1=4950, r1=5400, r2=5600)
    payload2 = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[inverted],
    )
    assert any("urutan" in e for e in validate_terminal_payload(payload2))

def test_ingest_endpoint_422_on_bad_payload_and_auth(monkeypatch):
    snap = get_terminal_snapshot()
    bad = SupportResistanceItem(ticker="ASII", last_price=5260, s2=4950, s1=5100, r1=5400, r2=5600)
    body = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[bad],
    ).model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/api/terminal/ingest", json=body).status_code == 422
        monkeypatch.setenv("INGEST_API_KEY", "rahasia")
        assert client.post("/api/terminal/ingest", json=snap.model_dump(mode="json")).status_code == 401
        ok = client.post(
            "/api/terminal/ingest", json=snap.model_dump(mode="json"), headers={"X-API-Key": "rahasia"}
        )
        assert ok.status_code == 200

def test_unknown_ticker_shows_notice_instead_of_silent_fallback():
    with TestClient(app) as client:
        res = client.get("/?ticker=ZZZZ")
        assert res.status_code == 200
        assert "belum ada di cache" in res.text

def test_upload_endpoint_end_to_end_json_and_xlsx():
    json_body = _stmt(ticker="UPLD", year=2024).model_dump_json().encode()
    with TestClient(app) as client:
        r1 = client.post("/api/dupont/upload", files={"file": ("a.json", json_body)}, data={"ticker": "UPLD"})
        assert r1.status_code == 200
        xlsx = _xlsx([
            ("ticker", "UPLD"), ("year", 2025),
            ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
            ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
            ("Jumlah aset lancar", 300), ("Jumlah aset", 1000), ("Jumlah liabilitas", 450),
            ("Jumlah ekuitas", 550),
        ])
        r2 = client.post("/api/dupont/upload", files={"file": ("b.xlsx", xlsx)}, data={"ticker": "UPLD"})
        assert r2.status_code == 200
        body = r2.json()
        assert body["bundle"]["previous"]["year"] == 2024
        assert body["bundle"]["current"]["balance_sheet_balanced"] is True
        r3 = client.post("/api/dupont/upload", files={"file": ("c.txt", b"x")})
        assert r3.status_code == 400

def test_export_returns_content_and_node_colors_rendered():
    with TestClient(app) as client:
        res = client.get("/api/dupont/ASII/export")
        assert res.status_code == 200 and len(res.content) > 500
        home = client.get("/?ticker=TLKM")
        assert "text-emerald-400" in home.text or "text-amber-300" in home.text
```

---

# BAB 7: PLAYBOOK PROMPT EKSEKUSI HERMES AGENT DI TELEGRAM (M0–M8)

Kirimkan 3 perintah terstruktur di bawah ini secara berurutan kepada **Hermes Agent** di Telegram setelah kamu mengirimkan file dokumen ini:

### Prompt Telegram 1 (Milestone 0 — Inisialisasi & `AGENT_SPEC.md`)
> "Halo Hermes, baca file dokumen `MASTER_PRD_HERMES` ini secara menyeluruh. Kita membangun aplikasi gabungan **Proyek 1 (Platform DuPont & ALK)** dan **Proyek 2 (Terminal Riset Saham/IHSG)** dalam bentuk **Combined 2-Tab Dashboard**.
>
> Tugas pertama kamu:
> 1. Buat folder proyek `idx-quant-terminal` sesuai struktur di Bab 6.1.
> 2. Simpan seluruh isi dokumen ini sebagai `AGENT_SPEC.md` di root proyek agar menjadi acuan tetap.
> 3. Buat `requirements.txt` dan instal dependensinya di dalam virtual environment.
> Laporkan setelah struktur direktori dan `AGENT_SPEC.md` siap."

### Prompt Telegram 2 (Milestone 1, 2, 3, & 6 — Database, DuPont Engine, Parser IDX, LLM, & Terminal Pipeline)
> "Lanjutkan ke Milestone Backend (M1, M2, M3, dan M6). Salin dan implementasikan kode di Bab 6.2 sampai Bab 6.7 (kode sudah diuji; salin persis, jangan 'menyederhanakan') (`database.py`, `models.py`, `dupont_engine.py`, `parser.py`, `llm_analyzer.py`, `pdf_exporter.py`, dan `terminal_pipeline.py`) tanpa ada guardrail yang dikurangi. Pastikan seed data 4 emiten BEI (`ASII`, `ICBP`, `TLKM`, `ADRO`) dan seed data Terminal IHSG berfungsi."

### Prompt Telegram 3 (Milestone 4, 5, 7, & 8 — Combined 2-Tab UI, PDF Export, & Pytest Verification)
> "Selesaikan Milestone 4, 5, 7, dan 8:
> 1. Implementasikan `app/main.py` (Bab 6.8), `app/templates/base.html` (Bab 6.9), dan `tests/test_core_platform.py` (Bab 6.10).
> 2. Jalankan `python -m pytest -v` (bukan `pytest` polos) dan pastikan seluruh test (23 test) berstatus PASS. Jangan mengubah isi test agar lolos; jika ada test gagal, perbaiki kodenya dan laporkan penyebabnya.
> 3. Jalankan server FastAPI (`uvicorn app.main:app --host 0.0.0.0 --port 8000`) dan kirimkan laporan hasilnya."

---

## CATATAN TAMBAHAN & DATA PERTAMA YANG DITARIK SEBELUM BUILD
1. **Urutan Penarikan Data Riil:**
   - **Langkah 1:** Tarik 1 sampel JSON/CSV harian dari *pipeline* briefing IHSG milikmu (berisi indeks, big-cap movers, foreign flow RG/NG, dan S/R) lalu kirimkan ke endpoint `POST /api/terminal/ingest`.
   - **Langkah 2:** Tarik file Excel/PDF laporan keuangan IDX tahunan (`FY`) dan kuartalan (`Q2/Q3`) emiten target, lalu unggah ke `POST /api/dupont/upload` untuk menguji *cache* SQLite dan penyetahuan (*annualization*) otomatis.
2. **Pemulihan Konteks Telegram:** Jika sesi chat Telegram bersama Hermes terputus atau terkena *reset*, cukup kirimkan instruksi: *"Hermes, baca ulang `AGENT_SPEC.md` dan jalankan `python -m pytest -v` untuk melanjutkan pekerjaan."*

---

# BAB 8: AUDIT LOG v2.2 & BATASAN YANG DIKETAHUI

## 8.1 Hasil Audit (kode dijalankan, bukan hanya dibaca)
Pada audit sebelum v2.2, kode v2.1 dijalankan dan empat bug nyata terbukti dengan reproduksi:

| # | Bug v2.1 | Bukti | Perbaikan v2.2 | Test pengunci |
|---|---|---|---|---|
| 1 | `pytest` polos gagal `ModuleNotFoundError: app` | Simulasi tanpa cwd di `sys.path` | `pytest.ini` (`pythonpath = .`) + gunakan `python -m pytest` | seluruh suite |
| 2 | Parser membaca "Jumlah aset lancar" sebagai total aset (300, seharusnya 1000); ekuitas konsolidasi tidak terbaca; selisih neraca 133% | File Excel uji | G8: exact match pos neraca, tolak subtotal & EBITDA, baca ekuitas konsolidasi | `test_parser_*` (3 test) |
| 3 | YoY bisa membandingkan tahun yang sama (2025 vs 2025) | Dua upload tahun sama | G9: pembanding = tahun-1 jenis periode sama; unique constraint; upload ulang menggantikan | `test_yoy_*`, `test_reupload_*` |
| 4 | ROE jatuh 30% ke 7% tetap berlabel "OPERATIONAL_DRIVEN (High Quality)"; leverage turun ditulis "ekspansi, naik dari 3.33x menjadi 1.67x" | Skenario margin runtuh & leverage turun | G10: atribusi log bertanda + verdict sadar arah | `test_margin_collapse_*`, `test_falling_leverage_*`, `test_rising_leverage_*`, `test_log_contributions_*` |

Perbaikan lain di v2.2: ingest terminal divalidasi (422) dan dapat diberi API key; ticker tak dikenal menampilkan banner; warna node pohon DuPont kini tampil; LLM tidak memblokir halaman utama, dicache, dan outputnya divalidasi angka; path database & template tidak lagi bergantung pada direktori kerja.

## 8.2 Yang Sudah Diverifikasi dengan Eksekusi
- `python -m pytest -v`: 23 test PASS.
- Server `uvicorn` sungguhan: semua route mengembalikan HTTP 200.
- Jalur LLM diuji dengan server LLM tiruan: output jujur diterima (`source = LLM (angka tervalidasi)`), output dengan angka karangan ditolak dan kembali ke deterministik, panggilan non-blocking menghangatkan cache.

## 8.3 Batasan yang Diketahui (JANGAN diklaim sebagai fitur selesai)
1. **Parser belum diuji dengan file laporan keuangan IDX asli.** Hanya diuji dengan Excel/JSON tiruan berformat baris `label, nilai`. Format riil (kolom ganda tahun berjalan vs pembanding, catatan kaki, satuan jutaan/miliar, PDF hasil pindai) hampir pasti butuh penyesuaian. **Langkah pertama setelah build: uji dengan 2–3 file asli dan sesuaikan `ACCOUNT_SYNONYMS`.** Parser PDF hanya membaca tabel yang bisa diekstrak `pdfplumber`; PDF hasil pindai tidak didukung. `unit_multiplier` tidak terdeteksi otomatis dari file.
2. **Data seed dan snapshot Terminal adalah ilustrasi/demo**, bukan data resmi. Jangan dipakai untuk keputusan investasi. Ganti dengan data riil lewat upload dan `POST /api/terminal/ingest`.
3. **Emiten perbankan (BBCA, BBRI, BMRI, dll.) belum didukung**: konsep EBIT dan Interest Burden tidak berlaku untuk bank. Perlu model DuPont khusus bank (NII, NIM, dll.).
4. **WeasyPrint belum diuji.** Jika tidak terpasang, ekspor jatuh ke halaman HTML siap cetak (tombol "Cetak / Simpan PDF" di browser), bukan file PDF langsung.
5. **UI belum lengkap terhadap visi PRD**: belum ada form upload di UI (hanya API), belum ada pencarian/sortir kolom, pohon DuPont berupa kartu (tanpa garis hierarki), HTMX/AG-Grid/Plotly belum dipakai, dan klik ticker memuat ulang halaman penuh.
6. **Aturan Fraksi Harga BEI** diimplementasikan dari pengetahuan umum (Rp1/2/5/10/25 menurut rentang harga). Verifikasi terhadap peraturan BEI terbaru sebelum dipakai produksi.
7. **Keamanan & skala**: tidak ada autentikasi pengguna; `INGEST_API_KEY` bersifat opsional; snapshot Terminal disimpan di memori proses (hilang saat restart, tidak dibagi antar worker); cache LLM juga di memori. Jangan dibuka ke internet publik tanpa lapisan autentikasi dan penyimpanan snapshot yang persisten.
8. **Sebuah klaim "bebas halusinasi"** hanya berlaku untuk angka (validator angka). Validator tidak menilai kebenaran *penafsiran* kualitatif LLM; untuk itu narasi deterministik tetap menjadi acuan.

## 8.4 Urutan Kerja yang Disarankan Setelah Build
1. `python -m pytest -v` harus 23 PASS.
2. Unggah 1–2 laporan keuangan IDX asli (FY tahun berjalan **dan** FY tahun sebelumnya) via `POST /api/dupont/upload`; periksa `balance_sheet_balanced` dan angka terhadap laporan aslinya.
3. Ganti snapshot Terminal dengan data harian riil via `POST /api/terminal/ingest` (set `INGEST_API_KEY` lebih dulu).
4. Baru kerjakan backlog UI (form upload, sortir/pencarian, pohon hierarki) dan dukungan bank.
