from typing import List, Optional
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
    # Optional: DB tidak selalu punya turnover / arus asing. None berarti
    # "tidak ada data" dan template menampilkan N/A, bukan angka karangan.
    total_value_idr_bn: Optional[float] = None
    net_foreign_rg_idr_bn: Optional[float] = None
    net_foreign_all_idr_bn: Optional[float] = None
    market_status: str = Field(default="CLOSED EOD", pattern="^(OPEN|PRE-CLOSING|CLOSED EOD)$")
    briefing_headline: str

class BigCapMoverItem(BaseModel):
    ticker: str
    company_name: str
    last_price: int
    change_pct: float
    ihsg_point_impact: Optional[float] = None
    volume_lot: int
    market_cap_idr_trn: float

class ForeignFlowItem(BaseModel):
    ticker: str
    # None = data arus asing tidak tersedia untuk emiten ini. Sebelumnya
    # angkanya dikarang dengan rumus change_pct x 42.5 / x128 / x38.
    net_foreign_rg_1d_bn: Optional[float] = None
    net_foreign_rg_5d_bn: Optional[float] = None
    net_foreign_ng_1d_bn: Optional[float] = None

    @computed_field
    @property
    def flow_signal(self) -> str:
        if self.net_foreign_rg_1d_bn is None:
            return "N/A"
        if self.net_foreign_rg_1d_bn > 25.0 and (self.net_foreign_rg_5d_bn or 0) > 50.0:
            return "STRONG_ACCUMULATION"
        elif self.net_foreign_rg_1d_bn > 0:
            return "MILD_INFLOW"
        elif self.net_foreign_rg_1d_bn < -25.0 and (self.net_foreign_rg_5d_bn or 0) < -50.0:
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
        # Snapshot kosong: IHSG diisi pemanggil dari DB. Nilai lama (7685.42,
        # +0.84%) tidak pernah cocok dengan data tersimpan (5098.06).
        trading_date="",
        ihsg_last=0.0,
        change_pts=0.0,
        change_pct=0.0,
        total_value_idr_bn=None,
        net_foreign_rg_idr_bn=None,
        net_foreign_all_idr_bn=None,
        market_status="CLOSED EOD",
        briefing_headline="Snapshot belum dimuat dari sumber data.",
    ),
    movers=[],
    foreign_flows=[],
    sr_matrix=[],
)

def _index_market_cap_trn() -> float:
    """Total kapitalisasi pasar emiten tersimpan, dalam triliun rupiah.

    Dipakai sebagai penyebut kontribusi poin IHSG. Dihitung dari harga terakhir
    x jumlah saham (keduanya ada untuk 891 dari 914 emiten). Bila tidak dapat
    dihitung, kembalikan 0.0 agar pemanggil menulis N/A alih-alih mengarang.
    """
    try:
        from app.db.database import get_session as _gs
        sess = next(_gs())
        try:
            from sqlalchemy import text as _sqltext
            rows = sess.execute(_sqltext(
                """
                SELECT q.price, f.shares_outstanding
                FROM quotelatest q
                JOIN financialstatementcache f ON f.ticker = q.ticker
                 AND f.year = (SELECT MAX(year) FROM financialstatementcache f2
                               WHERE f2.ticker = q.ticker)
                WHERE q.price > 0 AND f.shares_outstanding > 0
                """
            )).fetchall()
        finally:
            sess.close()
        total = sum(float(px) * float(sh) for px, sh in rows if px and sh)
        return total / 1e12
    except Exception:
        return 0.0


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

            # Ambil arus asing riil dari DB (tabel foreignflowdaily).
            _ff_1d, _ff_5d, _ff_ng = {}, {}, {}
            try:
                from sqlalchemy import text as _sqlt
                from app.db.database import get_session as _gs_ff
                _sff = next(_gs_ff())
                try:
                    _row = _sff.execute(_sqlt(
                        "SELECT MAX(date) FROM foreignflowdaily")).fetchone()
                    _dmax = _row[0] if _row else None
                    if _dmax:
                        for _r in _sff.execute(_sqlt(
                            "SELECT ticker, net_foreign_rg_bn, net_foreign_ng_bn "
                            "FROM foreignflowdaily WHERE date = :d"), {"d": _dmax}).fetchall():
                            _ff_1d[_r[0]] = round(float(_r[1] or 0), 1)
                            _ff_ng[_r[0]] = round(float(_r[2] or 0), 1)
                        for _r in _sff.execute(_sqlt(
                            "SELECT ticker, SUM(net_foreign_rg_bn) FROM foreignflowdaily "
                            "WHERE date <= :d GROUP BY ticker"), {"d": _dmax}).fetchall():
                            _ff_5d[_r[0]] = round(float(_r[1] or 0), 1)
                finally:
                    _sff.close()
            except Exception:
                pass

            # Peta jumlah saham per emiten (untuk market cap & point impact).
            _shares_map = {}
            try:
                from sqlalchemy import text as _sqlt2
                from app.db.database import get_session as _gs_sh
                _ssh = next(_gs_sh())
                try:
                    for _r in _ssh.execute(_sqlt2(
                        "SELECT ticker, shares_outstanding FROM financialstatementcache f "
                        "WHERE year = (SELECT MAX(year) FROM financialstatementcache f2 "
                        "WHERE f2.ticker = f.ticker) AND shares_outstanding > 0"
                    )).fetchall():
                        _shares_map[_r[0]] = float(_r[1])
                finally:
                    _ssh.close()
            except Exception:
                pass

            # Build live movers from heavyweights / gainers
            live_movers: List[BigCapMoverItem] = []
            for item in ov.get("heavyweights", [])[:4]:
                sym = item.get("symbol", "")
                px = int(round(float(item.get("price", 0))))
                cp = float(item.get("change_pct", 0.0))
                mcap_t = float(item.get("market_cap", 0.0) or 0.0) / 1e12
                vol_lot = int(item.get("volume", 0)) // 100
                # Provider jarang mengirim market_cap (56 dari 914 terisi).
                # Hitung dari harga x saham tersimpan agar kontribusi indeks
                # punya penyebut dan pembilang dari basis data yang sama.
                if mcap_t <= 0 and px > 0:
                    _sh = _shares_map.get(sym.upper())
                    if _sh:
                        mcap_t = (px * _sh) / 1e12
                # Dampak poin IHSG: sumbangan relatif emiten = perubahan harga
                # dikali bobot market cap-nya terhadap kapitalisasi IHSG.
                # Versi lama memakai change_pct x 0.15 (konstanta tanpa dasar).
                impact = None
                try:
                    _idx_mcap_t = float((idx_data.get("market_cap") or 0)) / 1e12
                    if _idx_mcap_t <= 0:
                        # Provider tidak mengirim kapitalisasi indeks. Hitung
                        # dari harga x jumlah saham yang tersimpan (891 dari
                        # 914 emiten punya keduanya), jangan biarkan N/A
                        # padahal datanya ada.
                        _idx_mcap_t = _index_market_cap_trn()
                    if _idx_mcap_t > 0 and mcap_t > 0:
                        impact = round(ihsg_last * (mcap_t / _idx_mcap_t) * (cp / 100.0), 2)
                except Exception:
                    impact = None
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
                    
                    # Arus asing HANYA dari tabel foreignflowdaily. Versi lama
                    # mengarang dengan rumus change_pct x 42.5 / x128 / x38 yang
                    # tidak punya dasar data apa pun. Bila tidak ada baris untuk
                    # emiten ini, nilainya None sehingga UI menampilkan N/A.
                    live_ff.append(
                        ForeignFlowItem(
                            ticker=m.ticker,
                            net_foreign_rg_1d_bn=_ff_1d.get(m.ticker),
                            net_foreign_rg_5d_bn=_ff_5d.get(m.ticker),
                            net_foreign_ng_1d_bn=_ff_ng.get(m.ticker),
                        )
                    )

                return TerminalPayload(
                    header=IHSGBriefingHeader(
                        trading_date=trading_date,
                        ihsg_last=ihsg_last,
                        change_pts=change_pts,
                        change_pct=change_pct,
                        total_value_idr_bn=turnover_trn if turnover_trn > 0 else None,
                        # Diisi dari foreignflowdaily bila ada; None = N/A.
                        net_foreign_rg_idr_bn=(round(sum(_ff_1d.values()), 1) if _ff_1d else None),
                        net_foreign_all_idr_bn=(round(sum(_ff_ng.values()), 1) if _ff_ng else None),
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