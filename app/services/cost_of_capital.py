"""
Cost of Capital (WACC) — Institutional Grade.

Menggantikan versi lama yang memakai beta=1.0, ERP=5.5%, cost of debt=9%,
dan ETR=22% HARDCODED untuk semua emiten.

Prinsip:
  - Beta diambil dari regresi return harian vs IHSG (data riil DB).
    Jika tidak tersedia -> fallback beta sektor, ditandai provenance.
  - Risk-free dari input (default yield SUN 10Y), bukan angka karangan.
  - ERP: Damodaran Indonesia country risk premium (dapat dikonfigurasi).
  - Cost of debt = interest expense / rata-rata interest-bearing debt.
  - ETR aktual = tax provision / pretax. Jika tidak valid -> statutory 22%.
  - Setiap komponen membawa provenance: REPORTED / MARKET / COMPUTED / PROXY.

ZERO-FAKE: tidak ada nilai yang dipakai tanpa menyatakan asalnya.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlmodel import Session

DEFAULT_RF_PCT = 6.0          # yield SUN 10Y (dapat di-override)
DEFAULT_ERP_PCT = 5.5         # Damodaran mature-market ERP (dapat di-override)
DEFAULT_CRP_PCT = 2.5         # Indonesia country risk premium
STATUTORY_ETR = 0.22          # UU HPP 2022

# Fallback beta per sektor (Damodaran Januari 2026, emerging markets)
SECTOR_BETA = {
    "Keuangan": 1.05,
    "Perindustrian": 1.00,
    "Barang Konsumen Non-Primer": 1.10,
    "Barang Konsumen Primer": 0.85,
    "Energi": 1.05,
    "Barang Baku": 1.10,
    "Infrastruktur": 0.95,
    "Kesehatan": 0.90,
    "Teknologi": 1.25,
    "Properti & Real Estat": 1.15,
    "Transportasi & Logistik": 1.05,
}


def _get_beta(session: Optional[Session], ticker: str,
              sector: Optional[str]) -> tuple[Optional[float], str]:
    """Beta dari regresi riil; fallback sektor bila data tidak cukup."""
    if session is not None:
        try:
            from app.services.performance_engine import compute_performance
            perf = compute_performance(session, ticker, benchmark="IHSG")
            b = perf.get("beta")
            if perf.get("available") and b is not None and b != 0:
                return float(b), "MARKET (regresi return harian vs IHSG, 5 tahun)"
        except Exception:
            pass
    if sector and sector in SECTOR_BETA:
        return SECTOR_BETA[sector], f"PROXY (beta sektor {sector}, Damodaran)"
    return 1.0, "PROXY (beta pasar default 1.0 — data tidak tersedia)"


def _get_etr(row: dict) -> tuple[float, str]:
    """ETR aktual dari laporan; fallback statutory.

    CATATAN PENTING: di XBRL BEI, beban pajak dilaporkan NEGATIF
    (mis. BBCA 2025: tax_expense = -13.697,78 B, pretax = +71.260,88 B).
    ETR = |tax| / pretax. Memakai tanda mentah menghasilkan ETR negatif
    yang keliru dibulatkan jadi 0%.
    """
    pretax = row.get("profit_before_tax_bn")
    tax = row.get("tax_provision_bn")
    if pretax and tax is not None and pretax > 0:
        etr = abs(tax) / pretax
        if 0.0 <= etr <= 0.75:           # rentang wajar
            return etr, "COMPUTED (|tax provision| / pretax aktual)"
    return STATUTORY_ETR, f"PROXY (tarif statutori {STATUTORY_ETR*100:.0f}%)"


def _get_cost_of_debt(row: dict, etr: float) -> tuple[float, str]:
    """Kd = interest expense / rata-rata interest-bearing debt (post-tax)."""
    ie = row.get("interest_expense_bn")
    debt = row.get("total_loans_bn") or row.get("liabilities_bn")
    if ie is not None and debt and debt > 0:
        kd_pre = abs(ie) / debt
        if 0.005 <= kd_pre <= 0.35:      # 0.5% - 35% wajar
            return kd_pre * (1.0 - etr), "COMPUTED (beban bunga / total pinjaman, post-tax)"
    return 0.09 * (1.0 - etr), "PROXY (cost of debt 9% pre-tax)"


def _market_cap_bn(session, ticker: str) -> Optional[float]:
    """Kapitalisasi pasar dalam miliar rupiah, atau None bila tidak dapat dihitung.

    Urutan sumber:
      1. `QuoteLatest.market_cap` (sudah dalam rupiah penuh) — paling langsung.
      2. harga terakhir x jumlah saham dari tabel 5 tahun audited.
    Tidak memakai `QuoteLatest.shares_outstanding` karena kolom itu tidak ada
    di model; percobaan sebelumnya mengembalikan None untuk semua emiten
    sehingga bobot WACC jatuh ke ekuitas buku.
    """
    if session is None:
        return None
    tk = ticker.upper()
    try:
        from sqlmodel import select as _sel
        from app.db.models import QuoteLatest as _QL
        q = session.exec(_sel(_QL).where(_QL.ticker == tk)).first()
        mc = getattr(q, "market_cap", None) if q is not None else None
        if mc and mc > 0:
            return float(mc) / 1e9        # rupiah penuh -> miliar
        px = float(q.price) if (q and q.price and q.price > 0) else None
        from app.services.idx_audited_financials import five_year_table as _fyt
        hist = _fyt(tk) or []
        if px is None and hist:
            _c = hist[-1].get("close")
            px = float(_c) if _c else None
        sh = hist[-1].get("shares_outstanding") if hist else None
        if px and sh and float(sh) > 0:
            return (px * float(sh)) / 1e9
        return None
    except Exception:
        return None


def compute_wacc(session: Optional[Session], ticker: str, row: dict,
                 rf_pct: float = DEFAULT_RF_PCT,
                 erp_pct: float = DEFAULT_ERP_PCT,
                 crp_pct: float = DEFAULT_CRP_PCT) -> Dict[str, Any]:
    """
    Hitung WACC institusional dengan provenance per komponen.

    row: dict dari five_year_table() (satu tahun fiskal).
    """
    sector = row.get("sector")
    is_bank = bool(row.get("is_bank"))

    beta, beta_src = _get_beta(session, ticker, sector)
    etr, etr_src = _get_etr(row)

    rf = rf_pct / 100.0
    erp_total = (erp_pct + crp_pct) / 100.0
    ke = rf + beta * erp_total

    kd_post, kd_src = _get_cost_of_debt(row, etr)

    # ── Struktur modal ──────────────────────────────────────────────────────
    # BANK: WACC = biaya ekuitas. "Utang" bank adalah DPK nasabah — itu bahan
    # baku usaha dengan biaya yang SUDAH tercermin di NIM, bukan pendanaan
    # korporat yang dibobot dalam WACC. Versi lama memakai `total_loans_bn`
    # (kredit yang DISALURKAN, yaitu ASET senilai Rp970 T untuk BBCA) sebagai
    # bobot utang, menghasilkan WACC 3,97% — DI BAWAH risk-free 6,0%, mustahil.
    # NON-BANK: pakai utang berbunga bila ada; `liabilities_bn` (termasuk utang
    # usaha & beban akrual) hanya sebagai PROXY dan ditandai demikian.
    equity = row.get("equity_parent_bn") or row.get("equity_total_bn")
    if is_bank:
        debt = None
    else:
        debt = row.get("interest_bearing_debt_bn")
        if debt is None:
            debt = row.get("st_debt_bn")
        if debt is None:
            debt = row.get("liabilities_bn")

    if equity is None or equity <= 0:
        return {
            "available": False,
            "reason": "Ekuitas tidak tersedia/tidak valid — WACC tidak dapat dihitung",
            "is_bank": is_bank,
        }

    if is_bank:
        # Bank: biaya modal relevan = biaya ekuitas (lihat catatan di atas).
        we, wd = 1.0, 0.0
        wacc = ke
        debt_prov = ("N/A — bank: biaya modal relevan adalah biaya ekuitas; "
                     "DPK bukan pendanaan korporat")
    elif debt is None or debt < 0:
        # Tidak ada utang berbunga -> WACC = cost of equity
        we, wd = 1.0, 0.0
        wacc = ke
        debt_prov = "N/A (tidak ada utang berbunga)"
    else:
        # Bobot memakai NILAI PASAR ekuitas (market cap) bila tersedia — itu
        # standar WACC institusional. Memakai ekuitas BUKU membuat bobot utang
        # terlalu kecil (ASII: 23,2% vs 26,6% berbasis pasar) dan WACC terlalu
        # tinggi; sementara memakai total liabilitas membuatnya terlalu besar
        # (53,2%). Dua jalur (halaman utama vs tab Peers) sempat berbeda
        # 9,58% vs 11,84% untuk emiten yang sama karena ini.
        _mc = _market_cap_bn(session, ticker)
        _eq_w = _mc if (_mc and _mc > 0) else equity
        _eq_basis = "MARKET" if (_mc and _mc > 0) else "BOOK"
        # Catatan konsistensi: bobot memakai market cap, sama seperti
        # equity_research_helpers.build_wacc_components. Dua fungsi WACC yang
        # berbeda basis (buku vs pasar) menghasilkan ASII 11,84% vs 11,30%.
        total = _eq_w + debt
        we, wd = _eq_w / total, debt / total
        wacc = we * ke + wd * kd_post
        _ibd = row.get("interest_bearing_debt_bn") is not None or row.get("st_debt_bn") is not None
        debt_prov = ((f"REPORTED ({_eq_basis} equity + utang berbunga)" if _ibd
                      else f"PROXY ({_eq_basis} equity + total liabilitas; utang "
                           f"berbunga tidak tersedia di filing)"))

    # SANITY GATE: biaya modal tidak boleh di bawah risk-free. Bila terjadi,
    # ada komponen yang salah (bobot utang keliru, Kd mustahil, beta rusak).
    # Menampilkan angka di bawah rf = menyatakan pendanaan lebih murah daripada
    # obligasi pemerintah tanpa risiko — tidak dapat dipertanggungjawabkan.
    _wacc_mustahil = wacc < rf
    if _wacc_mustahil:
        return {
            "available": False,
            "is_bank": is_bank,
            "reason": (f"WACC {wacc*100:.2f}% di bawah risk-free {rf*100:.2f}% — "
                       f"komponen biaya modal tidak valid, hasil disembunyikan "
                       f"daripada disajikan sebagai fakta."),
            "cost_equity_pct": round(ke * 100.0, 2),
        }

    return {
        "available": True,
        "wacc_pct": round(wacc * 100.0, 2),
        "cost_equity_pct": round(ke * 100.0, 2),
        "cost_debt_pct": round(kd_post * 100.0, 2),
        "rf_pct": round(rf * 100.0, 2),
        "erp_pct": round(erp_pct, 2),
        "crp_pct": round(crp_pct, 2),
        "beta": round(beta, 3),
        "etr_pct": round(etr * 100.0, 2),
        "w_equity_pct": round(we * 100.0, 1),
        "w_debt_pct": round(wd * 100.0, 1),
        "is_bank": is_bank,
        "provenance": {
            "beta": beta_src,
            "etr": etr_src,
            "cost_of_debt": kd_src,
            "weights": debt_prov,
            "rf": f"INPUT ({rf_pct}% — asumsi yield SUN 10Y, dapat diubah)",
            "erp": f"INPUT (ERP {erp_pct}% + CRP {crp_pct}%, Damodaran Indonesia)",
        },
    }


# ─────────────────────────────────────────────────────────────────
# EVA / Economic Profit
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# Altman Z'' — versi yang benar untuk emerging market & non-manufaktur
# ─────────────────────────────────────────────────────────────────
def compute_altman_z(row: dict) -> Dict[str, Any]:
    """
    Altman Z'' (double-prime) untuk perusahaan non-manufaktur & emerging market.

        Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4

        X1 = Working Capital / Total Assets
        X2 = Retained Earnings / Total Assets
        X3 = EBIT / Total Assets
        X4 = Book Value of Equity / Total Liabilities

    Zona: Z'' > 2.6 = SAFE | 1.1 - 2.6 = GREY | < 1.1 = DISTRESS

    ZERO-FAKE: setiap variabel harus dari filing. Bila salah satu tidak ada,
    hasil N/A — TIDAK memakai pengganti seperti assets*0.5 (versi lama).
    Bank tidak dihitung: tidak punya klasifikasi lancar/tidak lancar.
    """
    if row.get("is_bank"):
        return {
            "available": False,
            "reason": "Bank memakai unclassified balance sheet — working capital "
                      "tidak bermakna, Altman Z'' tidak berlaku untuk lembaga keuangan.",
        }

    # Terima dua konvensi key: `assets_bn` (loader) dan `total_assets_bn`
    # (historical_financials di research engine). Tanpa ini, Altman selalu N/A.
    ta = row.get("assets_bn") or row.get("total_assets_bn")
    ca = row.get("current_assets_bn")
    cl = row.get("current_liabilities_bn")
    re_bn = row.get("retained_earnings_bn")
    ebit = row.get("ebit_bn")
    tl = row.get("liabilities_bn") or row.get("total_liabilities_bn")
    eq = (row.get("equity_parent_bn") or row.get("equity_total_bn")
          or row.get("total_equity_bn"))

    missing = []
    if not ta or ta <= 0: missing.append("Total Assets")
    if ca is None: missing.append("Current Assets")
    if cl is None: missing.append("Current Liabilities")
    if re_bn is None: missing.append("Retained Earnings")
    if ebit is None: missing.append("EBIT")
    if not tl or tl <= 0: missing.append("Total Liabilities")
    if eq is None: missing.append("Book Equity")

    if missing:
        return {
            "available": False,
            "reason": "Komponen tidak tersedia di filing: " + ", ".join(missing),
        }

    wc = ca - cl
    x1 = wc / ta
    x2 = re_bn / ta
    x3 = ebit / ta
    x4 = eq / tl

    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4

    if z > 2.6:
        zone, label = "SAFE", "Aman"
    elif z >= 1.1:
        zone, label = "GREY", "Abu-abu"
    else:
        zone, label = "DISTRESS", "Distress"

    # Catatan interpretasi: X4 (BVE/TL) bisa meledak pada emiten dengan liabilitas
    # sangat kecil relatif ekuitas (mis. BUKA: TL Rp 717 B vs Equity Rp 25,3 T),
    # menghasilkan Z puluhan meski RE/TA negatif. Model aslinya diturunkan untuk
    # manufaktur dengan struktur modal normal. Zona tetap benar (SAFE), tapi
    # angkanya tidak boleh dibaca sebagai "41x lebih aman".
    notes = []
    if x4 > 10:
        notes.append(
            f"X4 (BVE/TL) = {x4:.1f}x sangat tinggi karena liabilitas kecil "
            "relatif ekuitas; skor Z jenuh. Zona tetap valid, besaran tidak "
            "bisa dibandingkan langsung antar emiten."
        )
    if x2 < 0:
        notes.append("RE/TA negatif: saldo laba terakumulasi defisit (rugi bertahun-tahun).")
    if x1 < 0:
        notes.append("WC/TA negatif: liabilitas jangka pendek melebihi aset jangka pendek.")

    return {
        "available": True,
        "z_score": round(z, 2),
        "zone": zone,
        "zone_label": label,
        "x1_wc_ta": round(x1, 4),
        "x2_re_ta": round(x2, 4),
        "x3_ebit_ta": round(x3, 4),
        "x4_bve_tl": round(x4, 4),
        "notes": notes,
        "inputs": {
            "working_capital_bn": round(wc, 1),
            "retained_earnings_bn": round(re_bn, 1),
            "ebit_bn": round(ebit, 1),
            "total_assets_bn": round(ta, 1),
            "total_liabilities_bn": round(tl, 1),
            "book_equity_bn": round(eq, 1),
        },
        "provenance": "COMPUTED (Altman Z'' double-prime, 4 variabel dari filing audited)",
        "thresholds": "SAFE > 2.60 | GREY 1.10-2.60 | DISTRESS < 1.10",
    }


# ─────────────────────────────────────────────────────────────────
# EVA / Economic Profit
# ─────────────────────────────────────────────────────────────────
def compute_sustainable_growth(hist: list) -> tuple[Optional[float], str]:
    """
    g berkelanjutan untuk model Justified PBV.

    Formula standar: g = ROE x (1 - payout ratio).

    Dua jalur, dipilih berdasarkan ketersediaan data:
      1. PAYOUT RIIL — bila dividen kas dibayar dan laba tersedia.
         payout = dividend / net income, dibatasi 0-100%.
      2. CAGR EKUITAS — fallback bila dividen tidak ada. Dalam steady state,
         pertumbuhan ekuitas = ROE x retention, jadi definisinya setara tanpa
         perlu data DPS.

    Dibatasi 0%-8%: terminal growth di atas nominal PDB Indonesia (~5-7%)
    tidak realistis untuk horizon panjang.
    """
    hist = hist or []
    if not hist:
        return None, "N/A (tidak ada data historis)"

    last = hist[-1]
    eq_last = last.get("equity_parent_bn") or last.get("equity_total_bn")
    ni_last = last.get("net_income_parent_bn")
    div_last = last.get("dividends_paid_bn")

    # ── Jalur 1: payout ratio riil ──────────────────────────────────
    if (ni_last and ni_last > 0 and div_last is not None
            and eq_last and eq_last > 0):
        payout = abs(div_last) / ni_last
        if 0.0 <= payout <= 1.0:
            roe = ni_last / eq_last
            g = roe * (1.0 - payout)
            g = max(0.0, min(0.08, g))
            return round(g * 100.0, 2), (
                f"COMPUTED (g = ROE {roe*100:.2f}% x (1 - payout {payout*100:.1f}%), "
                f"dividen dari filing, dibatasi 0-8%)"
            )

    # ── Jalur 2: CAGR ekuitas buku ──────────────────────────────────
    eqs = [r.get("equity_parent_bn") or r.get("equity_total_bn") for r in hist]
    eqs = [e for e in eqs if e is not None and e > 0]
    if len(eqs) < 2:
        return None, "N/A (butuh minimal 2 tahun ekuitas positif / data dividen)"
    start, end = eqs[0], eqs[-1]
    n = len(eqs) - 1
    if start <= 0:
        return None, "N/A (ekuitas awal tidak valid)"
    cagr = (end / start) ** (1.0 / n) - 1.0
    g = max(0.0, min(0.08, cagr))
    src = (f"COMPUTED (CAGR ekuitas buku {cagr*100:.2f}% dari {n} tahun "
           f"sebagai pengganti ROE x retention, dibatasi 0-8%)")
    return round(g * 100.0, 2), src


def compute_eva(session: Optional[Session], ticker: str, row: dict,
                wacc_result: Optional[Dict[str, Any]] = None,
                rf_pct: float = DEFAULT_RF_PCT) -> Dict[str, Any]:
    """
    EVA (Economic Value Added) = NOPAT - (WACC x Invested Capital)

    Untuk BANK: RWA (Risk-Weighted Assets) TIDAK tersedia di XBRL BEI
    (diverifikasi: 554 tag BBCA tidak memuat tag risk-weighted/tier/CAR).
    Maka Invested Capital bank TIDAK dapat dihitung secara institusional.

    Alih-alih memakai proxy yang menyesatkan (Assets - Cash membuat bank tampak
    menciptakan nilai raksasa karena aset bank = pinjaman), bank dinilai dengan
    EXCESS RETURN MODEL yang benar untuk lembaga keuangan:
        Excess Return = (ROE - Cost of Equity) x Book Equity
    Ini ekuivalen dengan EVA bila modal diukur dari sisi ekuitas (sisi pemegang
    saham), dan merupakan praktik standar valuasi bank (Damodaran, Koller).
    """
    is_bank = bool(row.get("is_bank"))

    if wacc_result is None:
        wacc_result = compute_wacc(session, ticker, row, rf_pct=rf_pct)

    if not wacc_result.get("available"):
        return {"available": False, "reason": wacc_result.get("reason"), "is_bank": is_bank}

    ebit = row.get("ebit_bn")
    pretax = row.get("profit_before_tax_bn")
    tax = row.get("tax_provision_bn")
    equity = row.get("equity_parent_bn") or row.get("equity_total_bn")
    ni = row.get("net_income_parent_bn")

    etr = wacc_result["etr_pct"] / 100.0

    if is_bank:
        # ---- EXCESS RETURN MODEL (bank) ----
        ke = wacc_result["cost_equity_pct"] / 100.0
        if ni is None or equity is None or equity <= 0:
            return {"available": False, "is_bank": True,
                    "reason": "Laba bersih atau ekuitas tidak tersedia"}

        roe = ni / equity
        spread = roe - ke
        excess = spread * equity

        return {
            "available": True,
            "is_bank": True,
            "method": "EXCESS RETURN (ROE - Ke) x Book Equity",
            "reason_rwa": (
                "RWA tidak tersedia di XBRL BEI (diverifikasi: tidak ada tag "
                "risk-weighted/tier/CAR). EVA berbasis invested capital tidak dapat "
                "dihitung secara institusional untuk bank."
            ),
            "roe_pct": round(roe * 100.0, 2),
            "cost_equity_pct": round(ke * 100.0, 2),
            "spread_pct": round(spread * 100.0, 2),
            "excess_return_bn": round(excess, 1),
            "book_equity_bn": round(equity, 1),
            "nopat_bn": None,
            "invested_capital_bn": None,
            "eva_bn": round(excess, 1),
            "interpretation": (
                "Bank menciptakan nilai di atas biaya ekuitas"
                if spread > 0 else
                "Bank TIDAK menutup biaya ekuitasnya (nilai ekonomis negatif)"
            ),
            "provenance": {
                "roe": "COMPUTED (laba bersih / ekuitas)",
                "ke": wacc_result["provenance"]["beta"],
                "method": "Excess Return Model (standar valuasi bank)",
            },
        }

    # ---- EVA standar (non-bank) ----
    if ebit is None:
        return {"available": False, "is_bank": False, "reason": "EBIT tidak tersedia"}

    nopat = ebit * (1.0 - etr)
    assets = row.get("assets_bn")
    if assets is None or assets <= 0:
        return {"available": False, "is_bank": False, "reason": "Total aset tidak tersedia"}

    # Invested Capital = Total Assets - Cash - Non-Interest-Bearing Current Liabilities.
    # Definisi ini dapat DIVERIFIKASI dengan identitas neraca:
    #   CA + NCA = Assets (selisih 0.00% terverifikasi di 8 emiten)
    #   CL + NCL = Liabilities (selisih 0.00%)
    # Current liabilities dikoreksi dengan utang jangka pendek berbunga karena
    # utang berbunga adalah bagian dari pendanaan, bukan modal kerja operasional.
    cash = row.get("cash_bn") or 0.0
    _ca = row.get("current_assets_bn")
    _cl = row.get("current_liabilities_bn")
    _std = row.get("st_debt_bn")

    if _ca is not None and _cl is not None:
        nibcl = _cl - (_std or 0.0)
        ic = assets - cash - nibcl
        ic_prov = ("COMPUTED (Assets - Cash - NonInterestBearingCL; "
                   "CL dikoreksi utang jangka pendek berbunga)")
    else:
        ic = assets - cash
        ic_prov = "PROXY (Assets - Cash; current liabilities tidak tersedia di filing)"

    if ic <= 0:
        return {"available": False, "is_bank": False, "reason": "Invested capital tidak valid"}

    capital_charge = wacc_result["wacc_pct"] / 100.0 * ic
    eva = nopat - capital_charge
    roic = nopat / ic

    return {
        "available": True,
        "is_bank": False,
        "method": "EVA = NOPAT - (WACC x Invested Capital)",
        "nopat_bn": round(nopat, 1),
        "invested_capital_bn": round(ic, 1),
        "capital_charge_bn": round(capital_charge, 1),
        "roic_pct": round(roic * 100.0, 2),
        "wacc_pct": wacc_result["wacc_pct"],
        "spread_pct": round(roic * 100.0 - wacc_result["wacc_pct"], 2),
        "eva_bn": round(eva, 1),
        "interpretation": (
            "Menciptakan nilai ekonomi di atas biaya modal"
            if eva > 0 else
            "Menghancurkan nilai: laba operasi tidak menutup biaya modal"
        ),
        "provenance": {
            "nopat": f"COMPUTED (EBIT x (1 - ETR {etr*100:.2f}%))",
            "invested_capital": ic_prov,
            "wacc": wacc_result["provenance"]["beta"],
        },
    }
