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

    # ── Extended Fields (v4.0) ──────────────────────────────────────────
    sector: Optional[str] = None
    shares_outstanding: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    interest_bearing_debt: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    interest_income: Optional[float] = None
    interest_expense: Optional[float] = None
    tax_provision: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    depreciation: Optional[float] = None
    minority_interest: Optional[float] = None
    eps: Optional[float] = None

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

    def is_banking_entity(self) -> bool:
        """Deteksi emiten bank dari nama ticker atau sector label."""
        bank_tickers = {
            "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BDMN", "BNGA", "NISP",
            "MEGA", "BBTN", "BJBR", "BJTM", "BTPS", "ARTO", "BBHI", "PNBN",
            "BNLI", "BNII", "AGRO", "BBKP", "BMAS", "BSIM", "MAYA", "MCOR",
            "SDRA", "BGTG", "AMAR", "BANK", "BABP", "BACA", "BINA", "BKSW",
            "BMND", "BVIC", "DNAR", "INPC", "MASB", "NOBU", "PKPK",
        }
        return self.ticker.upper() in bank_tickers or (
            self.sector is not None and "bank" in self.sector.lower()
        ) or self.ticker.upper().startswith("B") and self.sector == "Financials"

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

    # ── Earnings Quality (v4.0) ─────────────────────────────────────
    ocf_to_net_income: Optional[float] = None   # Arus kas operasional / Laba bersih
    accrual_anomaly_detected: bool = False       # Accrual Alert: OCF/NI < 0.75 → kualitas laba suspect

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
    primary_driver_effect: str = "NA"
    roe_direction: str = "NA"
    driver_contributions_pct: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    tree_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    roe_bridge_steps: List[Dict[str, Any]] = Field(default_factory=list)

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

    # ── Earnings Quality (v4.0) ─────────────────────────────────────
    if stmt.operating_cash_flow is not None and stmt.net_income_parent > 0:
        ocf_to_net_income = round(stmt.operating_cash_flow / stmt.net_income_parent, 4)
    else:
        ocf_to_net_income = None
    accrual_anomaly_detected = ocf_to_net_income is not None and ocf_to_net_income < 0.75

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
        ocf_to_net_income=ocf_to_net_income,
        accrual_anomaly_detected=accrual_anomaly_detected,
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
            f"Neraca tidak seimbang: selisih {current_stmt.balance_sheet_discrepancy_pct:.2f}% antara Aset dan (Liabilitas + Ekuitas).\n"
        )
    if curr.is_negative_equity:
        warnings.append(
            "Defisiensi Modal (Ekuitas <= 0): ROE dan Equity Multiplier dinonaktifkan (NM) untuk mencegah distorsi matematis akibat ekuitas negatif.\n"
        )
    if curr.sign_inversion_detected:
        warnings.append(
            "Inversi tanda terdeteksi (EBIT <= 0 atau EBT <= 0): Rasio Tax Burden dan Interest Burden perlu diinterpretasikan bersama nilai absolutnya.\n"
        )
    if curr.annualized_applied:
        warnings.append(
            f"Laporan interim ({curr.period_type.value}) telah disetahunkan (faktor {current_stmt.annualization_factor:.2f}x) agar sebanding dengan Neraca.\n"
        )

    # ── Accrual Alert (v5.0) ─────────────────────────────────────
    if curr.accrual_anomaly_detected:
        warnings.append(
            f"Peringatan Kualitas Laba (Accrual Alert): Rasio OCF terhadap Laba Bersih rendah ({curr.ocf_to_net_income:.2f}x < 0.75x). Pertumbuhan laba didominasi akrual."
        )

    deltas: Dict[str, YoYDeltaItem] = {}
    primary_driver = PrimaryDriver.INSUFFICIENT_PRIOR_DATA
    driver_effect = "NA"
    roe_direction = "NA"
    contributions: Dict[str, float] = {
        "OPERATIONAL_MARGIN": 0.0,
        "ASSET_EFFICIENCY": 0.0,
        "FINANCIAL_LEVERAGE": 0.0,
        "TAX_OR_INTEREST_BURDEN": 0.0,
    }

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
                "Periode pembanding memiliki ekuitas negatif: atribusi YoY ROE tidak bermakna (NM).\n"
            )
        else:
            primary_driver, driver_effect, roe_direction, contributions = _attribute_roe_change(
                curr, prev, deltas
            )

    # ── ROE Bridge Waterfall 6-Langkah (v5.0) ────────────────────
    roe_bridge_steps: List[Dict[str, Any]] = []
    if curr.roe is not None and prev is not None and prev.roe is not None:
        def _alloc(key: str) -> float:
            if not contributions:
                return 0.0
            return round(contributions.get(key, 0.0), 2)

        roe_bridge_steps = [
            {
                "label": f"ROE {prev.year}",
                "val_pct": round(prev.roe * 100.0, 2),
                "type": "BASE",
            },
            {
                "label": "Margin Operasi (EBIT)",
                "val_pct": _alloc("OPERATIONAL_MARGIN"),
                "type": "DELTA",
            },
            {
                "label": "Efisiensi Aset (AT)",
                "val_pct": _alloc("ASSET_EFFICIENCY"),
                "type": "DELTA",
            },
            {
                "label": "Efek Pajak & Bunga",
                "val_pct": _alloc("TAX_OR_INTEREST_BURDEN"),
                "type": "DELTA",
            },
            {
                "label": "Pengungkit Utang (EM)",
                "val_pct": _alloc("FINANCIAL_LEVERAGE"),
                "type": "DELTA",
            },
            {
                "label": f"ROE {curr.year}",
                "val_pct": round(curr.roe * 100.0, 2),
                "type": "TOTAL",
            },
        ]

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
        roe_bridge_steps=roe_bridge_steps,
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
    """Atribusi perubahan ROE dengan dekomposisi logaritmik."""
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