# DATA_SOURCE_DISCOVERY (Fase 0 — Sumber Data Gratis untuk idx-quant-terminal)

Dokumen ini mendokumentasikan hasil audit kandidat sumber data gratis untuk platform riset pasar modal Indonesia (IDX/BEI), mencakup harga, indeks, laporan keuangan, dan arus asing.

---

## 1. Ringkasan Eksekutif & Temuan Repo GitHub

Dari pencarian dan evaluasi repo GitHub teraktif per Oktober 2026:

| Repositori | Bahasa | Bintang | Lisensi | Status Adopsi |
|------------|--------|---------|---------|---------------|
| **`ranaroussi/yfinance`** | Python | ★25.608 | Apache-2.0 | **DIADOPSI (Primary Source)**: Wrapper resmi Python ke API publik Yahoo Finance. Menggantikan parsing mentah; menangani format `.JK`, rate-limit, 160 fields quote, serta 4-5 tahun laporan keuangan (financials, balance sheet, cash flow) yang langsung di-feed ke DuPont Engine. |
| **`Fincept-Corporation/FinceptTerminal`** | C++ / Qt | ★33.123 | Non-standard | **DIADOPSI SEBAGAI DESAIN/INSPIRASI**: Repo desktop C++ Qt berbobot 790MB dengan tata letak grid dark Bloomberg. Bukan library Python langsung, tapi sistem modular tab, palette warna, dan hierarki widget-nya diadopsi sebagai blueprint visual untuk Tab Terminal di platform web ini. |
| **`fzn0x/idx`** | Rust | ★194 | MIT | **DIADOPSI (Secondary/Fallback)**: Binary ARM64 lokal (`~/.local/bin/idx`) untuk snapshot keluasan pasar (955 emiten, turnover agregat) jika yfinance mengalami timeout/rate-limit. |
| **`INo-xious/stockbit-mcp`** | Node.js | ★55 | MIT | Ditolak untuk core feed (memerlukan akun/token login pribadi pengguna, bukan data feed publik nol-konfigurasi). |

---

## 2. Pemetaan Kemampuan (Capability Matrix)

| Capability | Sumber Terpilih | Status | Keterlambatan Jujur | Catatan Teknis |
|------------|-----------------|--------|---------------------|----------------|
| **`QUOTE_BULK`** | Yahoo Finance (via `idx`) | ✅ Berhasil | 5–15 menit saat bursa buka | 1 request muat 50–100 ticker, tanpa API key. |
| **`INDEX_QUOTE`** | Yahoo Finance `^JKSE` | ✅ Berhasil | 5–15 menit | Menghasilkan harga IHSG, poin change, % change. |
| **`MARKET_OVERVIEW`** | Yahoo Finance | ✅ Berhasil | 15 menit / EOD | Advancing/Declining/Unchanged + Turnover harian + Top Movers. |
| **`HISTORY_DAILY`** | Yahoo Finance (via `idx`) | ✅ Berhasil | EOD harian | OHLCV harian interval 1d/1wk untuk kalkulasi moving averages & chart. |
| **`FINANCIAL_STATEMENT`** | Yahoo Finance `fundamentals-timeseries` | ✅ Berhasil | Kuartal / Tahunan | Revenue, Net Income, Total Assets, Equity, Debt, Tax, Interest tersedia untuk DuPont 3 & 5-stage. |
| **`FOREIGN_FLOW`** | idx.co.id (via IPOT/MSN fallback) | ⚠️ Terbatas | Cloudflare Blocked pada DC/VPN | Cloudflare bot protection memblokir IP server. Fallback: **Import CSV/JSON pengguna** atau dijalankan dari koneksi residensial/browser lokal. |

---

## 3. Detail Uji Coba Lapangan (Real Probe Output)

### A. Quote Emiten (BBCA, BBRI, TLKM, ASII)
- `BBCA`: Rp5.025 (-2,89%), Market Cap Rp617 T, PER 10.6x, PBV 2.28x, Dividend Yield 7.58%
- `BBRI`: Rp2.910 (+0,34%), Market Cap Rp438 T, PER 7.1x, PBV 1.36x, Dividend Yield 14.36%

### B. Indeks Komposit (IHSG / `^JKSE`)
- Nilai: 5.439,258 (+51,36 poin / +0,95%)
- Market Breadth: 501 naik, 190 turun, 222 stagnan (dari 913 ticker aktif)
- Turnover Harian: Rp13,77 Triliun

### C. Laporan Keuangan BBCA (untuk DuPont Engine)
Data terbaca presisi dari Yahoo Timeseries:
- Total Revenue: Rp89,52 Triliun
- Pretax Income (EBT): Rp50,46 Triliun
- Interest Expense: Rp6,01 Triliun → EBIT dihitung Rp56,48 Triliun
- Net Income: Rp40,73 Triliun
- Total Assets: Rp1.314,73 Triliun
- Stockholders Equity: Rp221,01 Triliun
- **Hasil DuPont 3-Stage**: ROE = 18,43%, NPM = 45,50%, Asset Turnover = 0.068x, Equity Multiplier = 5.95x. Selisih rekonsiliasi $2.77 \times 10^{-17}$ (jauh di bawah batas toleransi $10^{-6}$).

---

## 4. Mekanisme Keandalan & Kesegaran Data

1. **Aturan Label Kesegaran (`app/providers/classify.py`)**:
   - `REALTIME`: delay < 2 menit (hanya jika ada data feed live berlisensi).
   - `DELAYED`: delay 2–15 menit (label standar saat jam perdagangan IDX 09:00–16:00 WIB).
   - `EOD` (End of Day): setelah jam 16:15 WIB atau saat pasar tutup di akhir pekan/hari libur.
   - `STALE`: data tidak ter-update > 60 menit saat jam aktif pasar.

2. **Budget & Rate-Limiting (`app/providers/yahoo.py`)**:
   - Batas harian: 200 request quote, 50 request fundamental.
   - Delay minimum antar-panggilan batch: 300 ms.
   - Cooldown 10–30 menit jika mendekati ambang batas.

3. **Breakage Guardrail**:
   - Skema divalidasi via Pydantic model. Bila Yahoo mengubah format JSON, sistem tidak crash melainkan menandai status `RUSAK` dan memicu alert di header antarmuka.

---

## 5. Rekomendasi Lanjutan untuk Pengguna

- **Untuk fitur Foreign Flow harian**: Mengingat idx.co.id memperketat proteksi bot Cloudflare pada IP non-residensial, disarankan menyediakan fitur **Drag-and-Drop file Ringkasan Saham BEI (Excel/CSV)** di dashboard agar data foreign net buy/sell tetap 100% akurat tanpa bergantung pada scraping yang rentan blokir.
- **Untuk data real-time detik**: Jika di kemudian hari memerlukan tick data tanpa delay 15 menit, dapat dihubungkan ke sesi privat Stockbit via `stockbit-mcp` dengan token lokal pengguna.
