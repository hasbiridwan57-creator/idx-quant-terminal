"""
Regresi: nilai wajar emiten di SCREENER harus sama dengan jalur HALAMAN.

Bug yang dijaga oleh test ini
-----------------------------
Screener dan halaman utama menghitung nilai wajar bank lewat fungsi yang sama
(`calculate_banking_ratios`), tetapi sempat menghasilkan angka berbeda untuk
emiten yang sama — BBCA 4.559 (screener) vs 4.532 (halaman). Penyebabnya dua:

  1. Beta di jalur halaman dibulatkan 2 desimal (0,98) sementara jalur batch
     memakai presisi penuh (0,9753), sehingga Ke 13,84% vs 13,80%.
  2. `beta_prefetch` memotong data 5 tahun, sedangkan `load_prices` memakai
     seluruh riwayat — dua himpunan observasi, dua nilai beta.

Keduanya sudah dihapus: beta presisi penuh dan prefetch memakai seluruh
riwayat. Test ini memastikan kedua jalur tetap identik.
"""
import pytest
from sqlmodel import Session

from app.db.database import engine
from app.services.beta_prefetch import prefetch_betas
from app.services.cost_of_capital import _BETA_CACHE, _get_beta, compute_wacc
from app.services.idx_audited_financials import five_year_table


BANKS = ["BBCA", "BMRI", "BBRI"]


@pytest.fixture(scope="module")
def session():
    with Session(engine) as s:
        yield s


def test_beta_identik_antara_prefetch_dan_jalur_halaman(session):
    """
    Beta dari prefetch batch harus sama persis dengan beta jalur per-emiten.

    Kalau berbeda, Ke berbeda, lalu nilai wajar berbeda antara screener dan
    halaman untuk emiten yang sama — persis bug yang pernah terjadi.
    """
    for tk in BANKS:
        hist = five_year_table(tk)
        if not hist:
            pytest.skip(f"{tk}: data XBRL tidak tersedia")

        # Jalur halaman: cache kosong, hitung sendiri
        _BETA_CACHE.clear()
        beta_page, src_page = _get_beta(session, tk, hist[-1].get("sector"))
        if beta_page is None:
            continue

        # Jalur batch: prefetch mengisi cache
        _BETA_CACHE.clear()
        filled = prefetch_betas(session, [tk])
        if not filled:
            continue
        beta_batch, _ = _get_beta(session, tk, hist[-1].get("sector"))

        assert beta_batch == pytest.approx(beta_page, rel=1e-9), (
            f"{tk}: beta batch {beta_batch} != beta halaman {beta_page}. "
            "Prefetch dan jalur per-emiten harus memakai data yang sama."
        )


def test_ke_dan_wacc_konsisten(session):
    """Ke yang dipakai Justified PBV bank harus sama dengan Ke di jalur batch."""
    for tk in BANKS:
        hist = five_year_table(tk)
        if not hist:
            continue
        _BETA_CACHE.clear()
        w = compute_wacc(session, tk, hist[-1])
        if not w.get("available"):
            continue
        ke = w.get("cost_equity_pct")
        assert ke is not None, f"{tk}: Ke None padahal WACC available"
        # WACC bank = biaya ekuitas (DPK bukan pendanaan korporat)
        assert w.get("wacc_pct") == pytest.approx(ke, rel=1e-9), (
            f"{tk}: untuk bank, WACC harus sama dengan Ke"
        )


def test_screener_memuat_wacc(session):
    """Kolom wacc_pct tidak boleh kosong untuk emiten yang datanya lengkap."""
    from app.services.quant_engine import build_peer_screener_rows

    rows = build_peer_screener_rows(session)
    assert rows, "screener tidak menghasilkan baris"

    by_ticker = {r["ticker"]: r for r in rows}
    checked = 0
    for tk in BANKS:
        r = by_ticker.get(tk)
        if not r:
            continue
        # Bank selalu punya Ke; kalau kosong, kolom WACC tidak pernah terisi
        assert r.get("wacc_pct") is not None, (
            f"{tk}: wacc_pct kosong di screener. Sebelumnya nilai ini "
            "dihitung lalu dibuang saat menyusun baris output."
        )
        checked += 1
    assert checked > 0, "tidak ada bank yang bisa diverifikasi"
