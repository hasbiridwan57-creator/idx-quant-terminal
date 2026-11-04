# IDX-Quant Terminal

Platform riset ekuitas untuk pasar saham Indonesia (BEI/IDX) — dibangun di atas **laporan keuangan audited XBRL asli** dari BEI, bukan data dummy.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-88%20passed-brightgreen.svg)](#pengujian)
[![Data](https://img.shields.io/badge/emiten-937-orange.svg)](#cakupan-data)

---

## Tampilan

> **Tidak ada demo yang di-hosting.** Aplikasi ini dijalankan lokal — tiga perintah di bagian [Menjalankan](#menjalankan). Screenshot di bawah diambil dari aplikasi yang benar-benar berjalan dengan data asli, bukan mockup.

### DuPont & Analisis Fundamental
Penguraian ROE tiga tingkat dengan waterfall jembatan YoY dan audit kualitas laba.

![DuPont](docs/screenshots/02-dupont.png)

### Valuasi Perbankan (Justified PBV)
BVPS × Justified PBV dengan Ke dan g yang dihitung per emiten — bukan konstanta.

![Valuasi](docs/screenshots/03-valuation.png)

### Screener 937 Emiten
Satu tabel, dihitung dari engine yang sama dengan halaman per emiten.

![Screener](docs/screenshots/04-screener.png)

### Peer Matrix
Perbandingan head-to-head antar emiten sejenis.

![Peer Matrix](docs/screenshots/05-peer-matrix.png)

### Quant Risk
Monte Carlo GBM, VaR, Sharpe, dan ukuran risiko lain dari seri harga harian.

![Quant Risk](docs/screenshots/06-quant-risk.png)

### Fixed Income
Durasi, convexity, dan YTM untuk obligasi dan SBN.

![Fixed Income](docs/screenshots/07-fixed-income.png)

### Research Paper
Laporan 5 tahun siap ekspor PDF dan Excel.

![Research Paper](docs/screenshots/08-research-paper.png)

---

## Kenapa proyek ini ada

Sebagian besar screener saham Indonesia mengisi sel yang kosong dengan angka karangan supaya tabelnya terlihat lengkap. Proyek ini melakukan kebalikannya:

> **Kalau datanya tidak ada, tulis `N/A`. Jangan pernah mengarang.**

Setiap angka di aplikasi ini bisa dilacak ke sumbernya. Setiap angka yang **dihitung** diberi label bahwa itu hasil hitungan, bukan laporan emiten.

---

## Cakupan data

| Komponen | Jumlah | Sumber |
|---|---|---|
| Emiten tercakup | **937** | BEI |
| Filing laporan keuangan | **4.185** (2021–2025) | XBRL audited BEI |
| Baris harga harian | **±1,15 juta** | yfinance (EOD) |
| Endpoint API | **31** | — |
| Test otomatis | **88** | — |

Data fundamental berasal dari **XBRL audited** yang dipublikasikan BEI — angka yang sudah diaudit akuntan publik, bukan estimasi. Untuk harga penutupan harian dipakai yfinance (EOD), dipisahkan jelas dari data fundamental.

---

## Fitur

### Tab 1 — Charting
Grafik harga dengan indikator teknikal: EMA, Bollinger Bands, RSI, ATR, ADX (tren), Hurst exponent (mean reversion vs trending), dan deteksi volatilitas. Semua dihitung dari seri harga historis, bukan sinyal paket jadi.

### Tab 2 — DuPont & Analisis Fundamental
Penguraian ROE menjadi tiga komponen standar:
```
ROE = Margin Laba × Perputaran Aset × Pengganda Ekuitas
```
Lengkap dengan perbandingan tahun-ke-tahun (YoY), deteksi anomali akrual, dan identifikasi ekuitas tipis (ROE > 100% hampir selalu berarti ekuitas terkikis buyback/dividen, bukan bisnis luar biasa — UI memberi keterangan itu, bukan memuji angkanya).

### Tab 3 — Valuasi
- **DCF (Discounted Cash Flow)** dengan WACC yang dihitung per emiten: beta dari regresi return harian vs IHSG (5 tahun), risk-free dari yield SUN, equity risk premium + country risk premium Indonesia
- **Justified PBV** untuk bank — memakai `(ROE − g) / (Ke − g)`, bukan PBV median sektor
- **EVA** (Economic Value Added)
- **Sanity gate**: nilai wajar di luar rentang 0,25×–4× harga pasar ditolak dan ditampilkan `N/A`, karena itu tanda asumsi yang rusak — bukan peluang

### Tab 4 — Screener
937 emiten dalam satu tabel, dihitung dari engine yang sama dengan halaman per emiten (bukan template terpisah). Kolom: DuPont, ROE, WACC, credit grade, nilai wajar, upside, dan verdict kualitas.

### Tab 5 — Fixed Income
Kalkulator obligasi: durasi Macaulay & modifikasi, convexity, YTM, harga bersih/kotor.

### Tab 6 — Terminal & Pasar
Snapshot pasar, ringkasan IHSG, turnover, aliran dana asing, status perdagangan per emiten.

### Tab 7 — Research Paper
Laporan riset siap unduh dalam **PDF** dan **Excel**, dengan tabel 5 tahun, rasio, valuasi, dan catatan metodologi.

### Tab 8 — Peer Comparison
Perbandingan antar emiten sejenis: DuPont, valuasi, profitabilitas, dan struktur modal — semuanya lewat jalur WACC yang sama dengan halaman utama supaya angkanya konsisten.

### Tab 9 — Performance & Risiko
Return, volatilitas, Sharpe, Sortino, maximum drawdown, beta, alpha, dan korelasi terhadap IHSG — dihitung dari seri harga harian.

Berita dan katalis per emiten tersedia lewat endpoint `/api/research/{ticker}/news`, ditampilkan di panel riset tab 7 dan dipisahkan dari analisis supaya tidak tercampur opini.

---

## Prinsip yang dipegang

**1. Tidak ada data dummy.**
Tidak ada satu pun angka fundamental yang di-hardcode. Semua berasal dari XBRL audited BEI atau dihitung dari data mentah.

**2. Setiap angka punya provenance.**
Nilai di aplikasi ditandai salah satu dari:

| Label | Arti |
|---|---|
| `REPORTED` | Angka yang dilaporkan emiten di laporan keuangan |
| `MARKET` | Dari data pasar (harga, volume) |
| `COMPUTED` | Hasil hitungan engine dari data di atas |
| `PROXY` | Perkiraan karena data primer tidak tersedia — **selalu ditandai** |
| `N/A` | Data tidak ada. Tidak diisi, tidak ditebak |

**3. Bank diperlakukan berbeda.**
Untuk bank, WACC = biaya ekuitas. "Utang" bank adalah dana pihak ketiga — bahan baku usaha dengan biaya yang sudah tercermin di NIM, bukan pendanaan korporat yang dibobot dalam WACC. Memperlakukannya sebagai utang menghasilkan WACC di bawah risk-free, yang mustahil.

**4. Bobot WACC memakai nilai pasar.**
Bukan nilai buku ekuitas. Memakai ekuitas buku membuat bobot utang terlalu kecil dan WACC terlalu tinggi.

**5. Satu sumber kebenaran untuk setiap parameter.**
Risk-free rate, kurs USD/IDR, dan WACC dipakai dari satu tempat di seluruh jalur (halaman utama, screener, PDF, peer comparison). Sebelumnya beberapa jalur memakai nilai berbeda untuk emiten yang sama — itu sudah dihapus.

---

## Menjalankan

### Kebutuhan
- Python 3.11+

### Pasang

```bash
git clone https://github.com/hasbiridwan57-creator/idx-quant-terminal.git
cd idx-quant-terminal
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Jalankan

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Buka **http://127.0.0.1:8000**

Dokumentasi API interaktif otomatis tersedia di **http://127.0.0.1:8000/docs**

### Pengujian

```bash
pytest -q
```
```
88 passed
```

---

## Konfigurasi database

Secara bawaan aplikasi memakai **SQLite lokal** (`idx_quant_cache.db`) yang dibuat otomatis saat pertama kali dijalankan. Tidak ada yang perlu diatur.

### Data fundamental — otomatis

Saat startup, aplikasi membaca `data/xbrl_audited_metrics.jsonl` (18 MB, **4.185 filing audited untuk 937 emiten, 2021–2025**) dan mengisi tabel `financialstatementcache`. Jadi setelah `git clone`, DuPont, valuasi, screener, dan PDF langsung berfungsi tanpa langkah tambahan.

Data harga harian **tidak** disertakan di repo (1,15 juta baris, ~157 MB — terlalu besar untuk git). Isi sendiri dengan:

```bash
python scripts/backfill_ohlcv_yfinance.py            # semua 937 emiten
python scripts/backfill_ohlcv_yfinance.py BBCA ASII  # emiten tertentu saja
```

Skrip ini menarik OHLCV 5 tahun dari yfinance (`.JK`), idempoten, dan **tidak mengisi angka karangan** — emiten tanpa data dicatat `nodata`, bukan diisi nol. Butuh waktu lama untuk semua emiten karena rate limit; mulai dari beberapa ticker untuk mencoba.

Tanpa data harga, bagian fundamental dan screener tetap jalan (937 emiten); yang kosong hanya charting dan metrik performa/risiko — dan itu tampil sebagai `N/A`, bukan angka palsu.

### Memakai PostgreSQL

```bash
export IDX_DB_URL="postgresql://user:password@host:5432/nama_db"
```

Skrip migrasi SQLite → Postgres disertakan:

```bash
export IDX_SRC_DB="sqlite:///$(pwd)/idx_quant_cache.db"
export IDX_DST_DB="$IDX_DB_URL"
python scripts/migrate_to_postgres.py
```

Migrasi ini idempoten dan melaporkan jumlah baris per tabel di akhir, sehingga bisa diverifikasi.

---

## Deploy

`Dockerfile` dan `render.yaml`/`railway.json`/`Procfile` sudah tersedia.

```bash
docker build -t idx-quant .
docker run -p 8000:8000 -e IDX_DB_URL="postgresql://..." idx-quant
```

Catatan untuk container:
- **Satu worker.** Aplikasi memuat ±1,15 juta baris harga + 4.185 filing ke memori (~211 MB RSS). Dua worker akan menggandakannya dan bisa menghabiskan 512 MB.
- Healthcheck tersedia di `/health`.
- Image ±993 MB.

---

## Arsitektur

```
app/
├── main.py                  # FastAPI: 31 endpoint + render Jinja
├── paths.py                 # Resolusi path (env var → repo → home)
├── db/                      # Model SQLModel + koneksi SQLite/Postgres
├── services/
│   ├── idx_audited_financials.py   # Pembaca XBRL audited
│   ├── dupont_engine.py            # Penguraian DuPont
│   ├── cost_of_capital.py          # WACC, beta, cost of equity/debt
│   ├── beta_prefetch.py            # Beta batch (lihat catatan performa)
│   ├── banking_engine.py           # Rasio & valuasi khusus bank
│   ├── dcf_grid.py                 # DCF + sensitivitas
│   ├── quant_engine.py             # Screener 937 emiten
│   ├── performance_engine.py       # Sharpe, Sortino, drawdown, beta
│   ├── forensic_accounting.py      # Deteksi anomali akrual
│   ├── fincept_fixed_income.py     # Durasi, convexity, YTM
│   └── pdf_exporter.py             # Laporan PDF & Excel
├── templates/               # Template Jinja (satu per tab)
└── data/                    # XBRL JSONL + profil emiten
```

**Catatan performa.** Screener awalnya menembak 3.263 query ke database satu per satu. Di SQLite lokal itu tidak terasa; di Postgres remote (latensi ~60 ms) satu render halaman butuh **465 detik**. Perbaikannya: `beta_prefetch.py` menarik semua harga yang dibutuhkan dalam satu query besar dan menghitung beta di memori, ditambah prefetch market cap dan cache kurs USD/IDR. Hasilnya **query turun ke 98 dan render turun ke 28 detik**, dengan angka yang identik dan deterministik.

---

## Batasan yang jujur

- **Cakupan 937 emiten**, bukan seluruh 900+ yang tercatat hari ini — emiten baru atau yang belum menyampaikan laporan audited tidak muncul dengan angka.
- **Harga EOD**, bukan real-time. Untuk data intraday, aplikasi ini bukan pilihan.
- **`PROXY` dipakai saat data primer tidak ada** — misalnya biaya utang ketika emiten tidak merinci beban bunga. Selalu ditandai, tidak pernah disamarkan sebagai angka riil.
- **Estimasi valuasi bukan rekomendasi.** DCF dan Justified PBV bergantung pada asumsi (growth, WACC, terminal value). Sensitivitas asumsi ditampilkan agar pembaca melihat rentangnya, bukan satu angka seolah pasti.
- **Bank dan non-bank memakai rumus berbeda** karena memang bisnisnya berbeda. Perbandingan langsung metrik keduanya tidak selalu bermakna.

---

## Lisensi & penggunaan

Proyek ini untuk keperluan pembelajaran dan riset. Data fundamental milik BEI dan emiten masing-masing; harga pasar dari yfinance. Bukan nasihat investasi.

---

## Kontribusi

Issue dan pull request terbuka. Kalau menemukan angka yang salah, sertakan:
1. Ticker dan periode
2. Angka yang tampil vs angka yang seharusnya
3. Sumber (halaman laporan keuangan atau filing XBRL)

Karena setiap angka seharusnya bisa dilacak, laporan seperti ini bisa langsung ditindaklanjuti.
