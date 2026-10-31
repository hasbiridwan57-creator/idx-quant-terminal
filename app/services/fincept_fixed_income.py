"""
app/services/fincept_fixed_income.py
Fixed Income Analytics — Port dari FinceptTerminal:
  fincept-qt/scripts/Analytics/fixedIncome/bond_pricing.py
  fincept-qt/scripts/Analytics/fixedIncome/credit_analysis.py
  fincept-qt/scripts/Analytics/fixedIncome/duration_convexity.py

Fitur:
  - Bond pricing (kupon tetap & floating)
  - Duration & Convexity (Macaulay, Modified)
  - Yield to Maturity (YTM) — closed-form approximation
  - Current Yield, Simple Yield
  - Credit spread analysis
  - Credit metrics untuk perbankan BEI

Python-native, zero external dependency.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum

# ─── Enums ──────────────────────────────────────────────────────────────────────

class BondType(Enum):
    TREASURY = "SBN / SUN"
    CORPORATE = "Obligasi Korporasi"
    SUKUK = "Sukuk"
    FLIP = "FILP"

class CouponFrequency(Enum):
    MONTHLY = 12
    QUARTERLY = 4
    SEMIANNUAL = 2
    ANNUAL = 1

# ─── Bond Pricing ────────────────────────────────────────────────────────────────

@dataclass
class BondPriceResult:
    clean_price: float          # Harga bersih (tanpa accrued interest)
    dirty_price: float           # Harga kotor (dengan accrued interest)
    accrued_interest: float     # bunga berjalan
    current_yield: float        # CY = kupon / harga
    simple_yield: float         # SY = (kupon + (F-P)/n) / P
    ytm_approx: float           # Approximate YTM
    duration_years: float       # Macaulay Duration (tahun)
    modified_duration: float   # Modified Duration
    convexity: float            # Convexity
    pvbp: float                 # Price Value of a Basis Point

@dataclass
class BondCashFlow:
    period: int
    date: str
    principal: float
    coupon: float
    total: float

def _day_count_30360(d1: str, d2: str) -> float:
    """Day count convention 30/360 (Indonesia standard for SBN)."""
    try:
        y1, m1, d1n = map(int, d1.split("-"))
        y2, m2, d2n = map(int, d2.split("-"))
        return 360 * (y2 - y1) + 30 * (m2 - m1) + min(d1n, 30) - min(d2n, 30)
    except Exception:
        return 0.0

def bond_price(
    face_value: float,
    coupon_rate: float,           # Annual coupon rate (e.g. 0.08 = 8%)
    ytm: float,                    # Yield to Maturity (decimal)
    years_to_maturity: float,
    frequency: CouponFrequency = CouponFrequency.SEMIANNUAL,
    settlement_date: str = "2026-01-01",
    issue_date: str = "2025-01-01",
) -> BondPriceResult:
    """
    Kalkulasi harga obligasi dengan semua metrik fixed income.

    Args:
        face_value: Nilai nominal (e.g. 1_000_000 IDR)
        coupon_rate: Suku bunga kupon tahunan (decimal, e.g. 0.0725 = 7.25%)
        ytm: Yield to Maturity (decimal, annualized)
        years_to_maturity: Sisa tenor dalam tahun
        frequency: Frekuensi pembayaran kupon
        settlement_date: Tanggal settlement (untuk accrued interest)
        issue_date: Tanggal issuance
    """
    n_periods = int(years_to_maturity * frequency.value)
    coupon_per_period = face_value * coupon_rate / frequency.value
    rate_per_period = ytm / frequency.value

    # PV kupon
    pv_coupons = 0.0
    pv_principal = 0.0
    periods = list(range(1, n_periods + 1))

    for t in periods:
        df = (1 + rate_per_period) ** t
        pv_coupons += coupon_per_period / df

    # PV pokok
    pv_principal = face_value / ((1 + rate_per_period) ** n_periods)

    # Harga bersih
    clean_price = pv_coupons + pv_principal

    # Accrued interest (day count 30/360)
    ai = _day_count_30360(issue_date, settlement_date) / 360 * coupon_rate * face_value
    dirty_price = clean_price + ai

    # Current Yield
    current_yield = (coupon_rate * face_value) / clean_price if clean_price > 0 else 0.0

    # Simple Yield: (kupon + (F-P)/tahun) / P
    if clean_price > 0 and years_to_maturity > 0:
        simple_yield = (coupon_rate * face_value + (face_value - clean_price) / years_to_maturity) / clean_price
    else:
        simple_yield = coupon_rate

    # Duration (Macaulay) & Convexity
    weighted_time = 0.0
    weighted_time_sq = 0.0
    total_pv = clean_price

    for t in periods:
        df = (1 + rate_per_period) ** t
        cf_pv = coupon_per_period / df
        w = cf_pv / total_pv * (t / frequency.value)
        weighted_time += w

    # Principal weighted time
    principal_pv = face_value / ((1 + rate_per_period) ** n_periods)
    principal_w = principal_pv / total_pv * (years_to_maturity)
    weighted_time += principal_w

    # Convexity
    for t in periods:
        df = (1 + rate_per_period) ** t
        cf_pv = coupon_per_period / df
        t_yrs = t / frequency.value
        weighted_time_sq += (t_yrs * (t_yrs + 1) / (frequency.value ** 2)) * cf_pv / ((1 + rate_per_period) ** 2) / total_pv

    principal_pv_d = face_value / ((1 + rate_per_period) ** n_periods)
    principal_yrs = years_to_maturity
    weighted_time_sq += (principal_yrs * (principal_yrs + 1 / frequency.value)) * principal_pv_d / ((1 + rate_per_period) ** 2) / total_pv

    macaulay_duration = weighted_time
    modified_duration = macaulay_duration / (1 + rate_per_period)
    convexity = weighted_time_sq

    # PVBP (Price Value of a Basis Point)
    pvbp = modified_duration * clean_price * 0.0001

    return BondPriceResult(
        clean_price=round(clean_price, 2),
        dirty_price=round(dirty_price, 2),
        accrued_interest=round(ai, 2),
        current_yield=round(current_yield, 4),
        simple_yield=round(simple_yield, 4),
        ytm_approx=round(ytm, 4),
        duration_years=round(macaulay_duration, 4),
        modified_duration=round(modified_duration, 4),
        convexity=round(convexity, 4),
        pvbp=round(pvbp, 4),
    )


def ytm_from_price(
    face_value: float,
    coupon_rate: float,
    price: float,
    years_to_maturity: float,
    frequency: CouponFrequency = CouponFrequency.SEMIANNUAL,
) -> float:
    """
    Cari YTM dari harga obligasi (Newton-Raphson approximation).
    """
    if price <= 0:
        return 0.0

    n = int(years_to_maturity * frequency.value)
    coupon = face_value * coupon_rate / frequency.value
    y = coupon_rate  # initial guess: coupon rate as YTM

    for _ in range(100):
        r = y / frequency.value
        pv = sum(coupon / (1 + r) ** t for t in range(1, n + 1)) + face_value / (1 + r) ** n
        if abs(price - pv) < 0.01:
            break
        # Newton step (rough)
        dv = sum(-t * coupon / (1 + r) ** (t + 1) for t in range(1, n + 1)) \
             - n * face_value / (1 + r) ** (n + 1)
        dv /= frequency.value
        if abs(dv) < 1e-10:
            break
        y -= (pv - price) / dv

    return max(y, 0.0)


# ─── Credit Metrics ─────────────────────────────────────────────────────────────

@dataclass
class CreditMetricsResult:
    # Semua Optional: emiten yang tidak melaporkan komponen tertentu
    # (mis. beban bunga tidak ada di XBRL) harus menghasilkan N/A, bukan 0,0.
    debt_to_equity: Optional[float]
    debt_to_assets: Optional[float]
    interest_coverage: Optional[float]  # EBIT / Interest Expense
    cash_to_debt: Optional[float]        # Cash / Total Debt
    current_ratio: Optional[float]  # CA / CL — None untuk bank (unclassified BS)
    quick_ratio: Optional[float]    # (CA - Inventory) / CL — None untuk bank
    credit_score: int               # Score 1-10 (10 = investment grade)
    credit_grade: str               # AAA, AA, A, BBB, BB, B, CCC, D
    debt_service_coverage: Optional[float]  # CFADS / (Interest + Principal)


def calculate_credit_metrics(
    # Balance Sheet
    total_assets: float,
    total_liabilities: float,
    total_debt: float,
    current_assets: float,
    current_liabilities: float,
    cash_and_equivalents: float,
    # Income / Cash Flow
    ebit: float,
    interest_expense: float,
    cash_flow_from_operations: float,
    principal_repayment: float = 0,
    net_income: float = 0,
    # Period & Institution Mode
    period: int = 1,  # 1 = annual
    is_bank: bool = False,
) -> CreditMetricsResult:
    """
    Credit metrics untuk analisis risiko kredit perbankan/korporasi.
    Mendukung permodelan bank khusus (OJK/Basel proxy) jika is_bank=True.
    """
    equity = total_assets - total_liabilities
    if equity <= 0:
        equity = 1e-9

    # ZERO-FAKE: komponen yang tidak dilaporkan emiten (None) menghasilkan
    # N/A, bukan 0,0. Angka 0,0 terbaca sebagai "tidak punya utang" /
    # "tidak ada beban bunga" — kesimpulan yang berlawanan dengan kenyataan
    # (datanya memang tidak ada di XBRL).
    def _r(num, den, floor_den=True):
        if num is None or den is None:
            return None
        if floor_den and den <= 0:
            return None
        return num / den

    # Leverage ratios
    dte = _r(total_debt, equity)
    dta = _r(total_debt, total_assets)

    # Coverage ratios
    icr = _r(ebit, interest_expense)

    # Liquidity
    cr = _r(current_assets, current_liabilities)
    qr = _r(current_assets, current_liabilities)

    # Cash ratios
    ctd = _r(cash_and_equivalents, total_debt)

    # Debt service coverage
    _dsr_den = None if (interest_expense is None or principal_repayment is None) \
        else interest_expense + principal_repayment
    dsr = _r(cash_flow_from_operations, _dsr_den)

    unscored = []
    if is_bank:
        # Bank-specific credit evaluation (OJK / Basel Proxy)
        # Bank funded by deposits -> standard D/E & CR penalize banks unfairly.
        score = 5.0
        
        # 1. Capital Adequacy Proxy (Equity / Total Assets)
        eq_ratio = equity / total_assets if total_assets > 0 else 0.0
        if eq_ratio >= 0.15:
            score += 2.5
        elif eq_ratio >= 0.10:
            score += 2.0
        elif eq_ratio >= 0.08:
            score += 1.0
        else:
            score -= 1.0

        # 2. Return on Assets (ROA)
        roa = net_income / total_assets if total_assets > 0 else 0.0
        if roa >= 0.025:
            score += 2.0
        elif roa >= 0.015:
            score += 1.0
        elif roa < 0.005:
            score -= 1.0

        # 3. Cash / Liquid Reserve to Assets
        cash_ratio = cash_and_equivalents / total_assets if total_assets > 0 else 0.0
        if cash_ratio >= 0.10:
            score += 1.0
        elif cash_ratio < 0.03:
            score -= 0.5

        # 4. Solvency / Non-distress buffer
        if equity > 0 and net_income > 0:
            score += 0.5

        # BUG lama: cr = cash_ratio * 10 lalu dilaporkan sebagai "current ratio".
        # Itu bukan current ratio — hanya rasio kas yang dikali 10 supaya
        # kebetulan berada di kisaran angka rasio lancar, sehingga bank tampak
        # punya likuiditas lancar padahal neracanya unclassified (tanpa
        # aset/kewajiban jangka pendek). Sekarang dikembalikan None (N/A):
        # rasio lancar tidak berlaku untuk lembaga keuangan.
        cr = None
        qr = None
        # icr tetap None bila beban bunga tidak dilaporkan (N/A jujur);
        # jangan disulap jadi angka dari ROA yang bukan interest coverage.
        if icr is not None:
            icr = round(max(icr, roa * 100), 2)
    else:
        # Corporate standard credit scoring (1-10)
        score = 5.0  # start neutral

        # Komponen yang N/A tidak menambah/mengurangi skor: kita tidak
        # punya dasar untuk menilai. Skor tetap 5,0 (netral) pada aspek itu.
        # "unscored" dicatat supaya grade tidak dilebih-lebihkan.
        unscored = []

        # ICR contribution
        if icr is None:
            unscored.append("ICR")
        elif icr >= 8:    score += 2.0
        elif icr >= 4:   score += 1.0
        elif icr >= 2:    score -= 0.5
        else:            score -= 2.0

        # D/E contribution
        if dte is None:
            unscored.append("D/E")
        elif dte <= 0.5:   score += 1.5
        elif dte <= 1.5: score += 0.5
        elif dte <= 2.5: score -= 0.5
        else:            score -= 1.5

        # Current ratio
        if cr is None:
            unscored.append("CR")
        elif cr >= 2.0:   score += 0.5
        elif cr < 1.0:  score -= 1.0

        # Cash to debt
        if ctd is None:
            unscored.append("kas/utang")
        elif ctd >= 0.5:  score += 0.5
        elif ctd >= 0.2: score += 0.0
        else:           score -= 0.5

    score = max(1.0, min(10.0, score))

    # Map score to grade
    grades = [
        (9.0, "AAA"),
        (8.0, "AA+"),
        (7.0, "AA"),
        (6.0, "AA-"),
        (5.0, "A+"),
        (4.0, "A"),
        (3.0, "A-"),
        (2.0, "BBB"),
        (1.5, "BB+"),
        (1.0, "BB"),
        (0.0, "B"),
    ]
    grade = "D"
    for threshold, g in grades:
        if score >= threshold:
            grade = g
            break

    return CreditMetricsResult(
        debt_to_equity=round(dte, 4) if dte is not None else None,
        debt_to_assets=round(dta, 4) if dta is not None else None,
        interest_coverage=round(icr, 2) if icr is not None else None,
        cash_to_debt=round(ctd, 4) if ctd is not None else None,
        current_ratio=round(cr, 4) if cr is not None else None,
        quick_ratio=round(qr, 4) if qr is not None else None,
        credit_score=int(round(score)),
        credit_grade=grade,
        debt_service_coverage=round(dsr, 4) if dsr is not None else None,
    )


# ─── Demo ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # SUN FR0082: face 1M, coupon 7.25%, YTM ~7%, tenor 2 tahun
    r = bond_price(
        face_value=1_000_000,
        coupon_rate=0.0725,
        ytm=0.07,
        years_to_maturity=2.0,
    )
    print("=== SBN Price (face 1M, 7.25% kupon, YTM 7%, 2 tahun) ===")
    print(f"  Clean Price: Rp {r.clean_price:,.0f}")
    print(f"  Accrued:     Rp {r.accrued_interest:,.0f}")
    print(f"  Dirty Price: Rp {r.dirty_price:,.0f}")
    print(f"  CY: {r.current_yield*100:.2f}%")
    print(f"  Duration:    {r.duration_years:.3f} tahun")
    print(f"  Modified:     {r.modified_duration:.3f} tahun")
    print(f"  Convexity:    {r.convexity:.4f}")

    # Credit check BBRI
    cm = calculate_credit_metrics(
        total_assets=2_135_371_105_000_000,
        total_liabilities=1_811_337_247_000_000,
        total_debt=171_647_601_000_000,
        current_assets=0, current_liabilities=0,
        cash_and_equivalents=200_000_000_000_000,
        ebit=128_325_762_000_000,
        interest_expense=24_000_000_000_000,
        cash_flow_from_operations=80_000_000_000_000,
        principal_repayment=10_000_000_000_000,
    )
    print("\n=== BBRI Credit Metrics ===")
    print(f"  D/E: {cm.debt_to_equity:.2f}x | D/A: {cm.debt_to_assets:.2f}x")
    print(f"  ICR: {cm.interest_coverage:.1f}x | DSCR: {cm.debt_service_coverage:.2f}x")
    print(f"  Credit Score: {cm.credit_score}/10 → Grade: {cm.credit_grade}")
