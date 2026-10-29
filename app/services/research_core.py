from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# ---------- Provenance ----------
@dataclass(frozen=True)
class M:
    """Metric dengan asal-usul. src: REPORTED | COMPUTED | ESTIMATED | MANUAL | MISSING"""
    v: Optional[float] = None
    src: str = "MISSING"
    note: str = ""
    @property
    def ok(self) -> bool: return self.v is not None
    def fmt(self, f: str = "{:,.1f}", na: str = "n/a") -> str: return f.format(self.v) if self.v is not None else na

def reported(v: Optional[float], note="") -> M: return M(v, "REPORTED", note) if v is not None else M()

# ---------- StatementView : satu-satunya jalan konversi satuan ----------
@dataclass
class StatementView:
    bn: Dict[str, M]
    missing: List[str] = field(default_factory=list)
    annualization: float = 1.0
    def get(self, k: str) -> M: return self.bn.get(k, M())
    def need(self, *keys: str) -> bool: return all(self.get(k).ok for k in keys)

_FIELDS = ["revenue","ebit","ebt","net_income_parent","total_assets","total_liabilities","total_equity_parent",
           "interest_bearing_debt","cash_and_equivalents","current_assets","current_liabilities",
           "interest_expense","operating_cash_flow","capex","depreciation","minority_interest"]
_FLOW = {"revenue","ebit","ebt","net_income_parent","interest_expense","operating_cash_flow","capex","depreciation"}

def build_view(stmt) -> StatementView:
    mult = float(getattr(stmt, "unit_multiplier", None) or 1.0)
    af = float(getattr(stmt, "annualization_factor", 1.0))
    out, miss = {}, []
    for f in _FIELDS:
        raw = getattr(stmt, f, None)
        if raw is None:                                    # BUKAN `if not raw` -> nol itu data valid
            out[f] = M(); miss.append(f); continue
        v = float(raw) * mult / 1e9                        # -> Rp miliar
        if f == "capex": v = abs(v)                        # capex sering negatif di laporan arus kas
        if f in _FLOW: v *= af                             # annualize hanya arus (flow), bukan saldo
        out[f] = M(v, "REPORTED" if af == 1.0 or f not in _FLOW else "ESTIMATED",
                   "" if af == 1.0 or f not in _FLOW else f"disetahunkan x{af:g}")
    return StatementView(out, miss, af)

# ---------- Rating policy ----------
@dataclass
class RatingPolicy:
    buy_premium_over_ke: float = 0.05
    sell_below_total_return: float = 0.0
    max_dispersion: float = 0.40
    min_data_quality: float = 60.0

def rate(price: float, pt: float, div_yield: float, ke: float, mids: List[float], dq: float,
         pol: RatingPolicy = RatingPolicy()) -> Dict[str, Any]:
    if dq < pol.min_data_quality or not mids:
        return dict(rating="NOT RATED", reason=f"Data quality {dq:.0f}/100 < {pol.min_data_quality:.0f}", confidence="N/A")
    tr = pt / price - 1 + (div_yield or 0.0)
    mean = sum(mids) / len(mids)
    disp = (max(mids) - min(mids)) / mean if mean else 1.0
    r = "BUY" if tr >= ke + pol.buy_premium_over_ke else "SELL" if tr <= pol.sell_below_total_return else "HOLD"
    return dict(rating=r, total_return=tr, hurdle=ke + pol.buy_premium_over_ke, dispersion=disp,
                confidence="LOW" if disp > pol.max_dispersion else "MEDIUM" if disp > 0.2 else "HIGH")

# ---------- Risk heatmap dari angka nyata ----------
def level(x: Optional[float], cuts: List[float], higher_is_worse: bool = True) -> Optional[int]:
    if x is None: return None
    n = sum(1 for c in cuts if (x >= c if higher_is_worse else x <= c))
    return 1 + n   # 1 (rendah) .. 5 (kritis)

def risk_matrix(m: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    spec = [
        ("R1","Leverage (Net debt/EBITDA, x)", m.get("nd_ebitda"), [0.5,1.5,2.5,3.5], True),
        ("R2","Cakupan bunga (EBIT/Bunga, x)", m.get("icr"),        [8,4,2.5,1.5], False),
        ("R3","Likuiditas (Current ratio, x)", m.get("current_ratio"), [2,1.5,1.1,0.9], False),
        ("R4","Kualitas laba (CFO/NI, x)",      m.get("cfo_ni"),    [1.0,0.85,0.7,0.5], False),
        ("R5","Valuasi (z-score P/E vs 3Y)",    m.get("pe_z"),      [0.5,1.0,1.5,2.0], True),
        ("R6","Volatilitas harga (ann. vol)",   m.get("vol"),       [0.20,0.30,0.40,0.55], True),
        ("R7","Likuiditas perdagangan (hari keluar)", m.get("days_to_exit"), [1,3,7,15], True),
    ]
    out = []
    for code, name, val, cuts, hw in spec:
        lv = level(val, cuts, hw)
        out.append(dict(code=code, name=name, value=val, level=lv,
                        label={None:"Data tidak tersedia",1:"Rendah",2:"Terkendali",3:"Moderat",4:"Tinggi",5:"Kritis"}[lv]))
    return out

# ---------- Football field ----------
def football(rows: List[Dict[str, Any]], price: float) -> Dict[str, Any]:
    """rows: [{method, low, mid, high}] hanya metode yang datanya lengkap."""
    ok = [r for r in rows if r.get("low") and r.get("high") and r["low"] <= r["high"]]
    mids = [r["mid"] for r in ok]
    return dict(rows=ok, price=price, blended_mid=sum(mids)/len(mids) if mids else None,
                lo=min((r["low"] for r in ok), default=None), hi=max((r["high"] for r in ok), default=None))

# ---------- EPS shock ----------
def eps_shock(ebit: float, interest: float, floating_debt: float, tax: float, ni: float, rate_bp=100, rev_drop=0.10, dol=2.0):
    d_rate = -(floating_debt * rate_bp / 1e4) * (1 - tax) / ni
    d_rev = -(rev_drop * dol * ebit) * (1 - tax) / ni
    return dict(ni_chg_rate=d_rate, ni_chg_rev=d_rev)
