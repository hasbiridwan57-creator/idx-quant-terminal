#!/usr/bin/env python3
"""Generator laporan end-to-end IDX-QuantTerminal v4.0.

Menghasilkan satu file markdown berisi:
  1. Ringkasan arsitektur & flow data
  2. Kode sumber LENGKAP setiap file (tanpa potongan)
  3. Daftar endpoint REST
  4. Hasil verifikasi
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/hasbi/idx-quant-terminal")
OUT_DIR = ROOT / "laporan"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "IDX_QuantTerminal_v4.0_END_TO_END_LENGKAP.md"

# File sumber yang di-dump lengkap (urutan mengikuti alur request)
SOURCE_FILES = [
    ("app/main.py", "FastAPI entry point — lifecycle, seluruh route handler, integrasi engine"),
    ("app/db/database.py", "Engine SQLite, event PRAGMA, auto-migrasi kolom v3.0 → v4.0"),
    ("app/db/models.py", "SQLModel schema — 8 tabel, FinancialStatementCache + field extended v4.0"),
    ("app/services/dupont_engine.py", "DuPont 3-Stage & 5-Stage, rekonsiliasi < 1e-6, accrual check, tree nodes"),
    ("app/services/banking_engine.py", "Bank Model OJK/BI — NIM, CIR, ROA, ROE, Justified PBV, is_banking_entity"),
    ("app/services/fincept_valuation.py", "DCF — WACC, un/relever beta, FCFF, Gordon Growth TV, sensitivitas 2D, skenario"),
    ("app/services/fincept_risk.py", "Risk — Sharpe, Sortino, Calmar, Max DD, VaR/CVaR 95%, Beta, Alpha, IR"),
    ("app/services/fincept_fixed_income.py", "Fixed income — bond pricing, YTM Newton-Raphson, duration, convexity, credit score"),
    ("app/services/fincept_financial_ratios.py", "Rasio keuangan tambahan (port FinceptTerminal)"),
    ("app/services/parser.py", "Parser Excel/PDF/JSON, ACCOUNT_SYNONYMS, seed, load_ticker_pair/history, generator template Excel"),
    ("app/services/terminal_pipeline.py", "Pipeline IHSG — tick size BEI, S/R matrix, movers, foreign flow, validator"),
    ("app/services/llm_analyzer.py", "Audit kualitas laba berbasis metrik (fallback non-LLM)"),
    ("app/services/pdf_exporter.py", "Ekspor tear-sheet HTML/PDF"),
    ("app/providers/__init__.py", "Re-export provider"),
    ("app/providers/yahoo.py", "Provider idx CLI + yfinance, freshness, budget, cache finansial & quote"),
    ("app/providers/classify.py", "Klasifikasi kesegaran data & health sumber"),
    ("app/templates/base.html", "UI dark institusional (Tailwind + Alpine.js) — 2 tab: DuPont & Terminal"),
    ("app/templates/pdf_report.html", "Template laporan cetak A4"),
    ("scripts/populate_db.py", "Seed database & sinkronisasi ticker massal"),
    ("tests/test_providers.py", "Test suite provider"),
    ("tests/test_core_platform.py", "Test suite platform inti"),
]

FLOW = """\
## ALUR DATA END-TO-END

```
                    SUMBER DATA EKSTERNAL
                 idx CLI (955 emiten)   yfinance
                          \\              /
                           v            v
              ┌──────────────────────────────────────┐
   LAYER 1    │  DATA INGESTION                      │
              │  app/providers/yahoo.py              │
              │  app/providers/classify.py           │
              │  → fetch_market_overview()           │
              │  → fetch_financials_multi(years=4)   │
              │  → fetch_quotes() / fetch_history()  │
              │  → classify_freshness()              │
              └──────────────────┬───────────────────┘
                                 v
              ┌──────────────────────────────────────┐
   LAYER 2    │  STORAGE & PERSISTENCE               │
              │  app/db/database.py + models.py      │
              │  SQLite + SQLModel ORM, 8 tabel      │
              │  cache_financials_multi_to_db()      │
              │  _migrate_schema_add_columns()       │
              └──────────────────┬───────────────────┘
                                 v
        ┌────────────────────────┴────────────────────────┐
        v                                                 v
┌───────────────────────────┐              ┌───────────────────────────┐
│  LAYER 3a                 │              │  LAYER 3b                 │
│  DUPONT & BANKING         │              │  VALUASI & RISIKO         │
│  dupont_engine.py         │              │  fincept_valuation.py     │
│  banking_engine.py        │              │  fincept_risk.py          │
│  → 3/5-stage, diff<1e-6   │              │  fincept_fixed_income.py  │
│  → accrual check OCF/NI   │              │  → WACC, FCFF, TV, 2D     │
│  → NIM/CIR/Justified PBV  │              │  → Sharpe/VaR/Credit      │
└───────────┬───────────────┘              └───────────┬───────────────┘
            │                                          │
            └────────────────┬─────────────────────────┘
                             v
              ┌──────────────────────────────────────┐
   LAYER 4    │  REST API & CONTROLLER               │
              │  app/main.py (FastAPI)               │
              │  GET /  GET /api/health              │
              │  /api/market/overview /api/quotes    │
              │  /api/dupont/{t} /export /template   │
              │  /api/terminal/snapshot /api/risk/{t}│
              └──────────────────┬───────────────────┘
                                 v
              ┌──────────────────────────────────────┐
   LAYER 5    │  PRESENTASI                          │
              │  app/templates/base.html             │
              │  Tailwind dark #0A0E17 + Alpine.js   │
              │  Tab 1 DuPont · Tab 2 Terminal IHSG  │
              └──────────────────────────────────────┘
```

## ALUR REQUEST `GET /?ticker=<SYMBOL>`

1. `load_ticker_pair(session, ticker)` → ambil periode terbaru + pembanding YoY dari
   `FinancialStatementCache`. Bila kosong → `fetch_financials_multi()` → cache → ulangi.
2. `analyze_dupont_yoy(curr, prev)` → `dupont_engine.py`:
   dekomposisi 3-stage & 5-stage, `reconciliation_diff_*`, atribusi logaritmik,
   `tree_nodes`, warning neraca/ekuitas negatif.
3. `summarize_dupont_anomalies(bundle)` → audit kualitas laba.
4. `get_terminal_snapshot()` → IHSG, movers, foreign flow, S/R matrix
   dengan fraksi harga BEI tervalidasi.
5. Deteksi bank: `is_banking_entity(ticker, sector)`.
   - Bank  → `calculate_banking_ratios()` (NIM, ROA, ROE, CIR, Justified PBV),
     DCF **tidak** dijalankan.
   - Non-bank → `quick_dcf_valuation()` (WACC, FCFF 5Y, TV, sensitivitas, skenario)
     + `calculate_credit_metrics()`.
6. `load_ticker_history()` → tren multi-tahun → `compute_single_period_dupont()` per periode.
7. `calculate_risk_metrics()` → Sharpe, Sortino, VaR/CVaR, Max DD.
8. `templates.TemplateResponse("base.html", ctx)` → render.

## ALUR UPLOAD `POST /api/dupont/upload`

1. Baca bytes (batas 25 MB).
2. `parse_idx_file_bytes()` → deteksi `.xlsx` / `.pdf` / `.json`,
   cocokkan label via `ACCOUNT_SYNONYMS`, validasi `required_keys`.
3. `save_or_get_cached_statement()` → hash SHA-256, upsert per
   `(ticker, year, period_type)`.

## ALUR EKSPOR

- `GET /api/dupont/{ticker}/export` → `render_dupont_report_export()` → HTML A4 siap cetak.
- `GET /api/dupont/template/excel` → `generate_idx_excel_template_bytes()` → `.xlsx`
  (2 sheet: `Laporan_Keuangan`, `Panduan_Upload`).
"""


def dump_file(rel: str, desc: str) -> str:
    p = ROOT / rel
    if not p.exists():
        return f"### `{rel}`\n\n**Deskripsi:** {desc}\n\n> ⚠️ File tidak ditemukan.\n\n---\n\n"
    body = p.read_text(encoding="utf-8", errors="replace")
    lang = "html" if p.suffix == ".html" else "python"
    return (
        f"### `{rel}`\n\n"
        f"**Deskripsi:** {desc}  \n"
        f"**Ukuran:** {p.stat().st_size:,} bytes · {len(body.splitlines()):,} baris\n\n"
        f"```{lang}\n{body}\n```\n\n---\n\n"
    )


def endpoint_table() -> str:
    rows = [
        ("GET", "/", "Dashboard utama — Tab DuPont + Tab Terminal"),
        ("GET", "/api/health", "Status sumber data + budget polling"),
        ("GET", "/api/market/overview", "Breadth, gainers, losers, heavyweights"),
        ("GET", "/api/quotes", "Quote batch (maks 200 simbol)"),
        ("GET", "/api/dupont/{ticker}", "Bundle DuPont + audit kualitas laba (JSON)"),
        ("GET", "/api/dupont/{ticker}/export", "Tear-sheet HTML/PDF"),
        ("GET", "/api/dupont/template/excel", "Template Excel laporan keuangan"),
        ("POST", "/api/dupont/upload", "Unggah laporan (.xlsx/.pdf/.json)"),
        ("GET", "/api/terminal/snapshot", "Snapshot IHSG + S/R matrix"),
        ("POST", "/api/terminal/ingest", "Ingest snapshot terminal (butuh API key)"),
        ("GET", "/api/risk/{ticker}", "Risk metrics dari data harga 1Y"),
    ]
    out = "| Method | Path | Deskripsi |\n|---|---|---|\n"
    for m, p, d in rows:
        out += f"| `{m}` | `{p}` | {d} |\n"
    return out


def verification() -> str:
    try:
        from fastapi.testclient import TestClient

        import sys

        sys.path.insert(0, str(ROOT))
        from app.main import app

        c = TestClient(app)
        checks = [
            ("GET /?ticker=ASII", "/?ticker=ASII"),
            ("GET /?ticker=BBCA", "/?ticker=BBCA"),
            ("GET /api/health", "/api/health"),
            ("GET /api/market/overview", "/api/market/overview"),
            ("GET /api/quotes?symbols=BBCA,BBRI", "/api/quotes?symbols=BBCA,BBRI"),
            ("GET /api/dupont/ASII", "/api/dupont/ASII"),
            ("GET /api/dupont/ASII/export", "/api/dupont/ASII/export"),
            ("GET /api/dupont/template/excel", "/api/dupont/template/excel"),
            ("GET /api/terminal/snapshot", "/api/terminal/snapshot"),
        ]
        lines = ["| Endpoint | Status | Bytes |\n|---|---|---|\n"]
        for name, path in checks:
            r = c.get(path)
            ok = "200 OK" if r.status_code == 200 else f"{r.status_code}"
            lines.append(f"| `{name}` | {ok} | {len(r.content):,} |\n")
        return "".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"> Verifikasi tidak dijalankan: `{exc}`\n"


def git_info() -> str:
    try:
        sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return f"- Git HEAD: `{sha}`" if sha else "- Repo bukan git / tanpa commit"
    except Exception:  # noqa: BLE001
        return "- Repo bukan git / tanpa commit"


def main() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")
    parts: list[str] = []

    parts.append(
        "# IDX-QuantTerminal v4.0 — Laporan End-to-End Lengkap\n\n"
        f"**Digenerate:** {now}  \n"
        f"**Root proyek:** `{ROOT}`  \n"
        f"**Versi aplikasi:** 4.0.0  \n"
        f"{git_info()}\n\n"
        "Dokumen ini memuat alur data end-to-end, daftar endpoint REST, "
        "hasil verifikasi, dan **kode sumber lengkap setiap file** tanpa potongan.\n\n"
        "---\n\n"
    )

    parts.append(FLOW)
    parts.append("\n---\n\n## DAFTAR ENDPOINT REST\n\n")
    parts.append(endpoint_table())
    parts.append("\n---\n\n## HASIL VERIFIKASI ENDPOINT\n\n")
    parts.append(verification())
    parts.append("\n---\n\n## STRUKTUR DIREKTORI\n\n```\n")

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [
            d for d in dirnames
            if d not in {".venv", "__pycache__", ".git", "node_modules", "tmp"}
        ]
        rel = Path(dirpath).relative_to(ROOT)
        depth = 0 if str(rel) == "." else len(rel.parts)
        indent = "  " * depth
        if str(rel) != ".":
            parts.append(f"{indent}{rel.name}/\n")
        for f in sorted(filenames):
            parts.append(f"{indent}  {f}\n")

    parts.append("```\n\n---\n\n## KODE SUMBER LENGKAP\n\n")
    for rel, desc in SOURCE_FILES:
        parts.append(dump_file(rel, desc))

    OUT.write_text("".join(parts), encoding="utf-8")
    size = OUT.stat().st_size
    print(f"OK  {OUT}")
    print(f"    {size:,} bytes ({size / 1024:.1f} KB)")
    print(f"    {len(SOURCE_FILES)} file sumber di-dump lengkap")


if __name__ == "__main__":
    main()
