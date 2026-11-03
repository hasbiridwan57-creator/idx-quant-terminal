# IDX-Quant Terminal — image produksi.
#
# Kenapa slim + wheels: pandas/numpy butuh build tool kalau tanpa wheel.
# Memasang build-essential di image akhir menambah ~300 MB; trik di bawah
# hanya memasang wheel biner (--only-binary) supaya tidak butuh compiler.
#
# Ukuran target < 900 MB. Mount /app/static ditulis saat runtime kalau
# filesystem writable; kalau read-only app tetap hidup (lihat app/main.py).

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

# libpq untuk psycopg (driver Postgres/Neon), curl untuk healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kode + data XBRL (18 MB) ikut dalam image.
COPY app ./app
COPY data ./data
COPY static ./static

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1

# Satu worker: app memuat 1,15 juta baris + 4.175 laporan ke memori.
# Worker kedua akan menggandakan RSS menjadi ~420 MB dan melewati limit 512 MB.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
