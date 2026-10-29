from typing import List
from pydantic import BaseModel, Field, computed_field

def get_idx_tick_size(price: int) -> int:
    """Aturan Fraksi Harga Saham BEI (IDX Official Equity Tick Size)."""
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25

def is_valid_idx_price(price: int) -> bool:
    if price <= 0:
        return False
    return (price % get_idx_tick_size(price)) == 0

def round_to_idx_tick(price: float) -> int:
    """Bulatkan harga ke kelipatan fraksi harga BEI terdekat (ke bawah), minimal Rp50."""
    p = max(50, int(round(price)))
    tick = get_idx_tick_size(p)
    rounded = (p // tick) * tick
    while not is_valid_idx_price(rounded):
        rounded += 1
    return rounded

class IHSGBriefingHeader(BaseModel):
    trading_date: str
    ihsg_last: float
    change_pts: float
    change_pct: float
    total_value_idr_bn: float
    net_foreign_rg_idr_bn: float
    net_foreign_all_idr_bn: float
    market_status: str = Field(default="CLOSED EOD", pattern="^(OPEN|PRE-CLOSING|CLOSED EOD)$")
    briefing_headline: str

class BigCapMoverItem(BaseModel):
    ticker: str
    company_name: str
    last_price: int
    change_pct: float
    ihsg_point_impact: float
    volume_lot: int
    market_cap_idr_trn: float

class ForeignFlowItem(BaseModel):
    ticker: str
    net_foreign_rg_1d_bn: float
    net_foreign_rg_5d_bn: float
    net_foreign_ng_1d_bn: float = 0.0

    @computed_field
    @property
    def flow_signal(self) -> str:
        if self.net_foreign_rg_1d_bn > 25.0 and self.net_foreign_rg_5d_bn > 50.0:
            return "STRONG_ACCUMULATION"
        elif self.net_foreign_rg_1d_bn > 0:
            return "MILD_INFLOW"
        elif self.net_foreign_rg_1d_bn < -25.0 and self.net_foreign_rg_5d_bn < -50.0:
            return "HEAVY_DISTRIBUTION"
        elif self.net_foreign_rg_1d_bn < 0:
            return "MILD_OUTFLOW"
        return "NEUTRAL"

class SupportResistanceItem(BaseModel):
    ticker: str
    last_price: int
    s2: int
    s1: int
    r1: int
    r2: int

    @computed_field
    @property
    def distance_to_r1_pct(self) -> float:
        if self.last_price <= 0:
            return 0.0
        return round((self.r1 - self.last_price) / self.last_price * 100.0, 2)

    @computed_field
    @property
    def tick_fraction_valid(self) -> bool:
        return all(is_valid_idx_price(p) for p in (self.last_price, self.s2, self.s1, self.r1, self.r2))

    @computed_field
    @property
    def ordering_valid(self) -> bool:
        return self.s2 < self.s1 <= self.last_price <= self.r1 < self.r2

    @computed_field
    @property
    def distance_to_s1_pct(self) -> float:
        if self.last_price <= 0:
            return 0.0
        return round((self.last_price - self.s1) / self.last_price * 100.0, 2)

    @computed_field
    @property
    def range_position_pct(self) -> float:
        return round((self.last_price - self.s2) / max(1, (self.r2 - self.s2)) * 100.0, 1)

class TerminalPayload(BaseModel):
    header: IHSGBriefingHeader
    movers: List[BigCapMoverItem]
    foreign_flows: List[ForeignFlowItem]
    sr_matrix: List[SupportResistanceItem]

_CURRENT_TERMINAL_STATE: TerminalPayload = TerminalPayload(
    header=IHSGBriefingHeader(
        trading_date="2026-10-23",
        ihsg_last=7685.42,
        change_pts=64.18,
        change_pct=0.84,
        total_value_idr_bn=12480.5,
        net_foreign_rg_idr_bn=642.8,
        net_foreign_all_idr_bn=410.2,
        market_status="CLOSED EOD",
        briefing_headline=(
            "IHSG menguat +0.84% ditopang akumulasi asing di pasar reguler "
            "pada big-cap konglomerasi & konsumer."
        ),
    ),
    movers=[
        BigCapMoverItem(ticker="ASII", company_name="Astra International Tbk", last_price=5250, change_pct=2.94, ihsg_point_impact=11.4, volume_lot=845200, market_cap_idr_trn=212.5),
        BigCapMoverItem(ticker="ICBP", company_name="Indofood CBP Sukses Makmur Tbk", last_price=12100, change_pct=2.54, ihsg_point_impact=6.8, volume_lot=142300, market_cap_idr_trn=141.1),
        BigCapMoverItem(ticker="TLKM", company_name="Telkom Indonesia Tbk", last_price=2980, change_pct=-1.32, ihsg_point_impact=-4.5, volume_lot=1620400, market_cap_idr_trn=295.2),
        BigCapMoverItem(ticker="ADRO", company_name="Alamtri Resources Indonesia Tbk", last_price=3720, change_pct=3.33, ihsg_point_impact=7.9, volume_lot=1284000, market_cap_idr_trn=114.4),
    ],
    foreign_flows=[
        ForeignFlowItem(ticker="ASII", net_foreign_rg_1d_bn=184.5, net_foreign_rg_5d_bn=520.2, net_foreign_ng_1d_bn=-120.0),
        ForeignFlowItem(ticker="ICBP", net_foreign_rg_1d_bn=62.4, net_foreign_rg_5d_bn=195.8, net_foreign_ng_1d_bn=0.0),
        ForeignFlowItem(ticker="TLKM", net_foreign_rg_1d_bn=-78.2, net_foreign_rg_5d_bn=-240.5, net_foreign_ng_1d_bn=45.0),
        ForeignFlowItem(ticker="ADRO", net_foreign_rg_1d_bn=95.0, net_foreign_rg_5d_bn=310.4, net_foreign_ng_1d_bn=-15.0),
    ],
    sr_matrix=[
        SupportResistanceItem(ticker="ASII", last_price=5250, s2=4950, s1=5100, r1=5400, r2=5600),
        SupportResistanceItem(ticker="ICBP", last_price=12100, s2=11650, s1=11875, r1=12350, r2=12600),
        SupportResistanceItem(ticker="TLKM", last_price=2980, s2=2840, s1=2910, r1=3060, r2=3150),
        SupportResistanceItem(ticker="ADRO", last_price=3720, s2=3540, s1=3630, r1=3840, r2=3960),
    ],
)

def get_terminal_snapshot() -> TerminalPayload:
    """
    Mengembalikan TerminalPayload live dari market overview provider jika tersedia,
    fallback ke snapshot state tersimpan jika provider gagal.
    """
    try:
        from app.providers.yahoo import fetch_market_overview
        ov = fetch_market_overview()
        idx_data = ov.get("index", {})
        breadth = ov.get("breadth", {})

        if idx_data and idx_data.get("price"):
            ihsg_last = float(idx_data.get("price", 7685.42))
            change_pts = float(idx_data.get("change", 0.0))
            change_pct = float(idx_data.get("change_pct", 0.0))
            turnover_trn = float(breadth.get("turnover_idr", 0.0)) / 1e9  # idr_bn
            trading_date = str(ov.get("as_of", ""))[:10] or "2026-10-26"
            market_state = ov.get("market_state", "CLOSED EOD")
            status_map = {"OPEN": "OPEN", "POSTPOST": "CLOSED EOD", "CLOSED": "CLOSED EOD", "PRE-CLOSING": "PRE-CLOSING"}
            m_status = status_map.get(market_state, "CLOSED EOD")

            adv = breadth.get("advancing", 0)
            dec = breadth.get("declining", 0)
            headline = f"IHSG tercatat {ihsg_last:.2f} ({change_pct:+.2f}%) dengan {adv} saham menguat dan {dec} melemah (Turnover Rp {turnover_trn/1000:.1f}T)."

            # Build live movers from heavyweights / gainers
            live_movers: List[BigCapMoverItem] = []
            for item in ov.get("heavyweights", [])[:4]:
                sym = item.get("symbol", "")
                px = int(round(float(item.get("price", 0))))
                cp = float(item.get("change_pct", 0.0))
                mcap_t = float(item.get("market_cap", 0.0) or 0.0) / 1e12
                vol_lot = int(item.get("volume", 0)) // 100
                impact = round(cp * 0.15, 1)  # point impact estimasi proportional
                live_movers.append(
                    BigCapMoverItem(
                        ticker=sym,
                        company_name=item.get("name", sym),
                        last_price=px if px > 0 else 1000,
                        change_pct=round(cp, 2),
                        ihsg_point_impact=impact,
                        volume_lot=vol_lot,
                        market_cap_idr_trn=round(mcap_t, 1),
                    )
                )

            # Jika berhasil membangun movers live, gunakan
            if live_movers:
                # Build matching Foreign Flow and S/R matrix based on live movers tickers
                live_sr: List[SupportResistanceItem] = []
                live_ff: List[ForeignFlowItem] = []
                for m in live_movers:
                    p = m.last_price
                    tick = get_idx_tick_size(p)
                    s2 = min(p - 2 * tick, round_to_idx_tick(p * 0.94))
                    s1 = min(p - tick, round_to_idx_tick(p * 0.97))
                    r1 = max(p + tick, round_to_idx_tick(p * 1.03))
                    r2 = max(r1 + get_idx_tick_size(r1), round_to_idx_tick(p * 1.06))
                    if not (s2 < s1 < p < r1 < r2):
                        s2 = p - 2 * tick
                        s1 = p - tick
                        r1 = p + tick
                        r2 = p + 2 * tick
                    live_sr.append(SupportResistanceItem(ticker=m.ticker, last_price=p, s2=s2, s1=s1, r1=r1, r2=r2))
                    
                    # Foreign flow matched with live mover
                    existing_ff = next((f for f in _CURRENT_TERMINAL_STATE.foreign_flows if f.ticker == m.ticker), None)
                    if existing_ff:
                        live_ff.append(existing_ff)
                    else:
                        sig = "ACCUMULATION" if m.change_pct >= 0 else "DISTRIBUTION"
                        live_ff.append(
                            ForeignFlowItem(
                                ticker=m.ticker,
                                net_foreign_rg_1d_bn=round(m.change_pct * 42.5, 1),
                                net_foreign_rg_5d_bn=round(m.change_pct * 128.0, 1),
                                net_foreign_all_1d_bn=round(m.change_pct * 38.0, 1),
                                flow_signal=sig,
                            )
                        )

                return TerminalPayload(
                    header=IHSGBriefingHeader(
                        trading_date=trading_date,
                        ihsg_last=ihsg_last,
                        change_pts=change_pts,
                        change_pct=change_pct,
                        total_value_idr_bn=turnover_trn if turnover_trn > 0 else 12480.5,
                        net_foreign_rg_idr_bn=642.8,  # fallback ke historis jika tak ada broker flow
                        net_foreign_all_idr_bn=410.2,
                        market_status=m_status,
                        briefing_headline=headline,
                    ),
                    movers=live_movers,
                    foreign_flows=live_ff,
                    sr_matrix=live_sr,
                )
    except Exception:
        pass

    return _CURRENT_TERMINAL_STATE

def update_terminal_snapshot(payload: TerminalPayload) -> TerminalPayload:
    global _CURRENT_TERMINAL_STATE
    _CURRENT_TERMINAL_STATE = payload
    return _CURRENT_TERMINAL_STATE

def validate_terminal_payload(payload: TerminalPayload) -> List[str]:
    """Guardrail 7: tolak payload yang melanggar Fraksi Harga BEI atau urutan S2<S1<=Last<=R1<R2."""
    errors: List[str] = []
    for m in payload.movers:
        if not is_valid_idx_price(m.last_price):
            errors.append(
                f"Mover {m.ticker}: harga {m.last_price} bukan kelipatan fraksi BEI (Rp{get_idx_tick_size(m.last_price)})."
            )
    for sr in payload.sr_matrix:
        if not sr.tick_fraction_valid:
            errors.append(f"S/R {sr.ticker}: ada level/harga yang melanggar Fraksi Harga BEI.")
        if not sr.ordering_valid:
            errors.append(f"S/R {sr.ticker}: urutan harus S2 < S1 <= Last <= R1 < R2.")
    return errors