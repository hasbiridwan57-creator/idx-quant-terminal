from __future__ import annotations
import math, re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

# ---------- 1. ROE bridge (LMDI) : jumlah kontribusi == delta ROE persis ----------
def lmdi_roe_bridge(prev: Dict[str, float], curr: Dict[str, float]) -> Dict[str, float]:
    """prev/curr: tax_burden, interest_burden, ebit_margin, asset_turnover, equity_multiplier (semua > 0).
    Return kontribusi dalam poin persentase ROE (pp). sum(values) == (ROE1-ROE0)*100."""
    keys = ["ebit_margin", "asset_turnover", "equity_multiplier", "tax_burden", "interest_burden"]
    roe0 = math.prod(prev[k] for k in keys); roe1 = math.prod(curr[k] for k in keys)
    d = roe1 - roe0
    if abs(d) < 1e-12:
        return {k: 0.0 for k in keys}
    L = d / math.log(roe1 / roe0)               # logarithmic mean
    return {k: L * math.log(curr[k] / prev[k]) * 100.0 for k in keys}

# ---------- 2. DCF murni: satu fungsi untuk base, sensitivitas, skenario ----------
@dataclass
class DCFInputs:
    revenue0: float; ebit_margin: float; tax_rate: float
    da_pct: float; capex_pct: float; nwc_pct: float          # % of revenue
    g_start: float; g_terminal: float; years: int = 5
    wacc: float = 0.11
    net_debt: float = 0.0; minority: float = 0.0; shares: float = 1.0   # shares sama satuan dgn nilai
    mid_year: bool = True

def dcf_value(x: DCFInputs) -> Dict[str, float]:
    if x.wacc <= x.g_terminal:
        raise ValueError(f"WACC ({x.wacc:.2%}) harus > terminal growth ({x.g_terminal:.2%})")
    rev, pv, fcffs = x.revenue0, 0.0, []
    for t in range(1, x.years + 1):
        g = x.g_start + (x.g_terminal - x.g_start) * (t - 1) / max(1, x.years - 1)  # fade linear
        new_rev = rev * (1 + g)
        ebit = new_rev * x.ebit_margin
        fcff = ebit * (1 - x.tax_rate) + new_rev * (x.da_pct - x.capex_pct) - (new_rev - rev) * x.nwc_pct
        fcffs.append(fcff)
        pv += fcff / (1 + x.wacc) ** (t - 0.5 if x.mid_year else t)
        rev = new_rev
    # terminal: reinvestment dinormalisasi (capex = D&A * 1.05 agar tidak overstate)
    tv_fcff = rev * (1 + x.g_terminal) * x.ebit_margin * (1 - x.tax_rate) \
              - rev * x.g_terminal * x.nwc_pct - rev * (1 + x.g_terminal) * x.da_pct * 0.05
    tv = tv_fcff / (x.wacc - x.g_terminal)
    pv_tv = tv / (1 + x.wacc) ** (x.years - 0.5 if x.mid_year else x.years)
    ev = pv + pv_tv
    eq = ev - x.net_debt - x.minority
    return dict(ev=ev, equity=eq, price=eq / x.shares, tv_share=pv_tv / ev if ev else float("nan"), fcff=fcffs)

def dcf_sensitivity(x: DCFInputs, dw=(-0.02, -0.01, 0, 0.01, 0.02), dg=(-0.01, -0.005, 0, 0.005, 0.01)):
    from dataclasses import replace
    grid = [[dcf_value(replace(x, wacc=x.wacc + a, g_terminal=x.g_terminal + b))["price"] for a in dw] for b in dg]
    return grid  # baris = g, kolom = WACC ; sel [2][2] == base

def reverse_dcf_growth(x: DCFInputs, market_price: float) -> Optional[float]:
    """Cari g_start (growth tahun-1 yg memudar) yang membuat nilai DCF == harga pasar."""
    from dataclasses import replace
    lo, hi = -0.30, 0.60
    f = lambda g: dcf_value(replace(x, g_start=g))["price"] - market_price
    if f(lo) * f(hi) > 0: return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return (lo + hi) / 2

# ---------- 3. Beta selaras tanggal + Blume ----------
def beta_aligned(stock: List[float], bench: List[float]) -> Tuple[float, float]:
    """stock & bench HARUS sudah selaras per tanggal (aligned_closes). Return (raw, blume)."""
    n = min(len(stock), len(bench))
    rs = [stock[i] / stock[i-1] - 1 for i in range(1, n)]
    rb = [bench[i] / bench[i-1] - 1 for i in range(1, n)]
    ms, mb = sum(rs)/len(rs), sum(rb)/len(rb)
    cov = sum((a-ms)*(b-mb) for a, b in zip(rs, rb)) / (len(rs)-1)
    var = sum((b-mb)**2 for b in rb) / (len(rb)-1)
    raw = cov/var if var > 0 else 1.0
    return raw, 0.67*raw + 0.33

# ---------- 4. Earnings quality ----------
def sloan_accrual_ratio(ni: float, cfo: float, ta_begin: float, ta_end: float) -> float:
    return (ni - cfo) / ((ta_begin + ta_end) / 2)

def altman_z_em(wc, re, ebit, book_equity, ta, tl) -> float:
    """Altman Z'' (emerging markets / non-manufaktur): >2.6 aman, 1.1-2.6 abu-abu, <1.1 distress."""
    return 3.25 + 6.56*(wc/ta) + 3.26*(re/ta) + 6.72*(ebit/ta) + 1.05*(book_equity/tl)

# ---------- 5. P/E band dari harga & EPS riil ----------
def pe_band(prices: List[Tuple[str, float]], eps_steps: List[Tuple[str, float]]):
    """prices: [(YYYY-MM-DD, close_RAW)] ; eps_steps: [(tanggal_berlaku, EPS_TTM)] urut naik.
    EPS dipakai mulai tanggal rilis laporan (bukan akhir periode) -> hindari look-ahead."""
    series, j, eps = [], -1, None
    for d, p in prices:
        while j + 1 < len(eps_steps) and eps_steps[j+1][0] <= d:
            j += 1
        eps = eps_steps[j][1] if j >= 0 else None
        if eps and eps > 0: series.append((d, p / eps))
    vals = [v for _, v in series]
    if len(vals) < 60: return None
    m = sum(vals)/len(vals); sd = (sum((v-m)**2 for v in vals)/(len(vals)-1))**0.5
    cur = vals[-1]
    pct = sum(1 for v in vals if v <= cur)/len(vals)*100
    return dict(mean=m, sd=sd, plus1=m+sd, minus1=m-sd, plus2=m+2*sd, minus2=m-2*sd, current=cur,
                z=(cur-m)/sd if sd else 0, percentile=pct, n=len(vals), series=series)

# ---------- 6. Forecast 3-statement-lite yang pasti balance ----------
@dataclass
class Base:
    revenue: float; cash: float; debt: float; equity_total: float   # equity_total = induk + NCI
    nwc_pct: float; da_pct: float; capex_pct: float

def forecast(base: Base, years: int, growth: List[float], ebit_margin: List[float],
             tax: float, int_rate: float, payout: float, debt_target: Optional[List[float]] = None):
    rows, rev, cash, debt, eq = [], base.revenue, base.cash, base.debt, base.equity_total
    noa = eq + debt - cash                      # net operating assets
    nwc = base.revenue * base.nwc_pct
    for t in range(years):
        new_rev = rev * (1 + growth[t]); ebit = new_rev * ebit_margin[t]
        interest = debt * int_rate               # pakai debt awal tahun -> tanpa sirkularitas
        ni = (ebit - interest) * (1 - tax)
        dep, capex = new_rev * base.da_pct, new_rev * base.capex_pct
        new_nwc = new_rev * base.nwc_pct; d_nwc = new_nwc - nwc
        cfo = ni + dep - d_nwc
        div = max(0.0, ni * payout)
        new_debt = debt_target[t] if debt_target else debt
        cash = cash + cfo - capex - div + (new_debt - debt)
        eq = eq + ni - div
        noa = noa + capex - dep + d_nwc
        debt, rev, nwc = new_debt, new_rev, new_nwc
        assert abs((cash + noa) - (debt + eq)) < 1e-6, "neraca tidak balance"
        rows.append(dict(t=t+1, revenue=rev, ebit=ebit, ni=ni, cfo=cfo, capex=capex, div=div, cash=cash,
                         debt=debt, equity=eq, roe=ni/eq, fcf=cfo-capex))
    return rows

# ---------- 7. Parser: satuan & angka locale-aware ----------
_UNIT_PATTERNS = [
    (r"(dalam|in)\s+(jutaan|millions?)", 1e6), (r"(dalam|in)\s+(miliar|milyar|billions?)", 1e9),
    (r"(dalam|in)\s+(ribuan|thousands?)", 1e3), (r"(dalam|in)\s+(triliun|trillions?)", 1e12),
    (r"(dalam\s+)?rupiah\s+penuh|full\s+rupiah", 1.0),
]
def detect_unit_multiplier(text: str) -> Optional[float]:
    t = text.lower()
    for pat, mult in _UNIT_PATTERNS:
        if re.search(pat, t): return mult
    return None

def parse_idr_number(s: str, locale: str = "id") -> Optional[float]:
    """locale='id': '.' ribuan, ',' desimal (default laporan IDX). locale='en': kebalikannya.
    Jika dua pemisah muncul bersamaan, yang paling kanan = desimal (override locale)."""
    s = str(s).strip().replace(" ", "")
    if not s or s in {"-", "\u2014"}: return None
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = s.strip("()-")
    thou, dec = (".", ",") if locale == "id" else (",", ".")
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
    s = s.replace(thou, "").replace(dec, ".")
    try: v = float(s)
    except ValueError: return None
    return -v if neg else v

# ---------- 8. Indikator teknikal yang benar ----------
def rsi_wilder(close, period=14):
    import pandas as pd
    d = close.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    ad = dn.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = au / ad
    rsi = 100 - 100/(1+rs)
    rsi[(ad == 0) & (au > 0)] = 100.0        # semua naik -> 100 (bukan 50)
    rsi[(ad == 0) & (au == 0)] = 50.0
    return rsi

def tick(price: float) -> int:
    return 1 if price < 200 else 2 if price < 500 else 5 if price < 2000 else 10 if price < 5000 else 25
def round_down_tick(p: float) -> int:
    t = tick(p); return int(p // t * t)
def round_up_tick(p: float) -> int:
    t = tick(p); return int(-(-p // t) * t)
