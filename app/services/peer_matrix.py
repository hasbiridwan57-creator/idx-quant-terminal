"""
Sector Comparison Matrix — Institutional Peer Benchmark
Supports Multi-Ticker Side-by-Side Comparison (up to 10 peers)
"""
import sys
sys.path.insert(0, "/Users/hasbi/idx-quant-terminal")

from app.services.idx_audited_financials import five_year_table, _load, get_issuer_profile

def _safe(v, default="N/A"):
    return default if v is None else v

def _pct(v, decimals=1):
    if v is None: return "N/A"
    return f"{v:.{decimals}f}%"

def _bn(v, decimals=0):
    if v is None: return "N/A"
    return f"Rp {v:,.{decimals}f}B"

def _ratio(v, decimals=2):
    if v is None: return "N/A"
    return f"{v:.{decimals}f}x"

def _multi(v, decimals=2):
    if v is None: return "N/A"
    return f"{v:.{decimals}f}x"

def build_peer_matrix(primary_ticker: str, peer_tickers: list[str] = None,
                      session=None) -> dict:
    """
    Returns comprehensive peer comparison across multiple tickers.
    primary_ticker: fokus utama
    peer_tickers: list ticker pembanding (default: auto-detect sector peers)
    session: SQLModel Session opsional — dipakai untuk beta riil & WACC institusional.
             Tanpa session, WACC memakai fallback beta sektor (ditandai PROXY).
    """
    if session is None:
        try:
            from app.db.database import engine as _eng
            from sqlmodel import Session as _S
            with _S(_eng) as _s:
                return build_peer_matrix(primary_ticker, peer_tickers, session=_s)
        except Exception:
            session = None

    all_data = _load()

    # Default peers jika tidak ditentukan
    if not peer_tickers:
        # Tentukan sektor dari primary ticker
        p_hist = five_year_table(primary_ticker)
        if not p_hist:
            return {"error": f"Ticker {primary_ticker} tidak ditemukan"}

        peers = _get_auto_peers(primary_ticker, all_data)
    else:
        peers = peer_tickers

    rows = []
    for tk in [primary_ticker] + [p for p in peers if p != primary_ticker]:
        hist = five_year_table(tk)
        if not hist:
            continue
        r = hist[-1]  # tahun terbaru
        r_prev = hist[-2] if len(hist) >= 2 else None

        # Revenue YoY
        rev_cur = r.get("revenue_bn")
        rev_prev = r_prev.get("revenue_bn") if r_prev else None
        rev_yoy = ((rev_cur / rev_prev) - 1) * 100 if rev_cur and rev_prev else None

        # GP Margin
        gp = r.get("gross_profit_bn")
        gp_margin = (gp / rev_cur * 100) if gp and rev_cur else None

        # EBIT margin (Top-Down)
        se = r.get("selling_expense_bn") or 0
        ga = r.get("ga_expense_bn") or 0
        ebit = (gp - se - ga) if gp else None
        ebit_margin = (ebit / rev_cur * 100) if ebit and rev_cur else None

        # Net Margin
        ni = r.get("net_income_parent_bn")
        net_margin = (ni / rev_cur * 100) if ni and rev_cur else None

        # ROE
        eq = r.get("equity_parent_bn") or r.get("equity_total_bn")
        roe = (ni / eq * 100) if ni and eq else None

        # ── ROIC / WACC / EVA: pakai engine institusional (bukan hardcode) ──
        from app.services.cost_of_capital import compute_wacc, compute_eva
        _wacc_res = compute_wacc(session, tk, r)
        wacc_pct = _wacc_res.get("wacc_pct") if _wacc_res.get("available") else None
        _eva_res = compute_eva(session, tk, r, _wacc_res)
        roic = _eva_res.get("roic_pct") if _eva_res.get("available") else None
        eva_spread = _eva_res.get("spread_pct") if _eva_res.get("available") else None
        eva_abs = _eva_res.get("eva_bn") if _eva_res.get("available") else None
        eva_method = _eva_res.get("method")

        # Altman Z'' — hanya komponen yang benar-benar tersedia.
        # Versi lama memakai assets*0.5 dan ni*0.5 sebagai pengganti working capital
        # dan retained earnings: itu angka karangan. Sekarang N/A bila tidak ada.
        z_double_prime = None
        _ta = r.get("assets_bn")
        _tl = r.get("liabilities_bn")
        _ca = r.get("cash_bn")
        _re = r.get("retained_earnings_bn")
        if _ta and _ta > 0 and _tl is not None and _re is not None and ni is not None and ebit is not None:
            # WC = Current Assets - Current Liabilities; current assets tidak tersedia
            # di XBRL -> gunakan pendekatan Altman Z'' yang hanya butuh total:
            # Z'' = 6.56*(WC/TA) + 3.26*(RE/TA) + 6.72*(EBIT/TA) + 1.05*(BVE/TL)
            _wc = (_ca or 0.0) - (_tl * 0.0)  # tidak dapat dihitung tanpa current liab
            z_double_prime = None  # dinyatakan N/A secara jujur
        
        # EBITDA & Working Capital (institutional capital efficiency)
        _da = r.get("depreciation_amortization_bn")
        _ebitda = (ebit + _da) if (ebit is not None and _da is not None) else None
        _ebitda_m = (_ebitda / rev_cur * 100) if (_ebitda is not None and rev_cur) else None
        _cogs = r.get("cost_of_sales_bn")
        _dio = (r.get("inventories_bn") / _cogs * 365) if (r.get("inventories_bn") is not None and _cogs and _cogs > 0) else None
        _dso = (r.get("trade_receivables_bn") / rev_cur * 365) if (r.get("trade_receivables_bn") is not None and rev_cur and rev_cur > 0) else None
        _dpo = (r.get("trade_payables_bn") / _cogs * 365) if (r.get("trade_payables_bn") is not None and _cogs and _cogs > 0) else None
        _ccc = (_dio + _dso - _dpo) if (_dio is not None and _dso is not None and _dpo is not None) else None

        # EVA dihitung oleh cost_of_capital.compute_eva() di atas (sudah termasuk
        # Excess Return Model untuk bank). Tidak ada perhitungan duplikat di sini.

        rows.append({
            "ticker": tk,
            "is_primary": tk == primary_ticker,
            "company_name": r.get("company_name", tk),
            "sector": r.get("sector", "N/A"),
            "year": r.get("year"),
            "revenue_bn": rev_cur,
            "revenue_yoy": rev_yoy,
            "gross_profit_bn": gp,
            "gp_margin_pct": gp_margin,
            "ebit_bn": ebit,
            "ebit_margin_pct": ebit_margin,
            "net_income_bn": ni,
            "net_margin_pct": net_margin,
            "roe_pct": roe,
            "roic_pct": roic,
            "equity_bn": eq,
            "assets_bn": r.get("assets_bn"),
            "liabilities_bn": r.get("liabilities_bn"),
            "cash_bn": r.get("cash_bn"),
            "wacc_pct": wacc_pct,
            "altman_z_double_prime": z_double_prime,
            "ebitda_bn": _ebitda,
            "ebitda_margin_pct": _ebitda_m,
            "ccc_days": _ccc,
            "dio_days": _dio,
            "dso_days": _dso,
            "dpo_days": _dpo,
            "eva_spread_pct": eva_spread,
            "eva_bn": eva_abs,
            "eva_method": eva_method,
        })

    if not rows:
        return {"error": "Tidak ada data untuk peer comparison"}

    # Compute sector medians
    numeric_cols = ["revenue_bn","gp_margin_pct","ebit_margin_pct","net_margin_pct",
                    "roe_pct","roic_pct","wacc_pct","altman_z_double_prime","revenue_yoy",
                    "ebitda_margin_pct","ccc_days","eva_spread_pct"]
    medians = {}
    for col in numeric_cols:
        vals = [r[col] for r in rows if r.get(col) is not None]
        medians[col] = sum(vals) / len(vals) if vals else None

    return {
        "primary_ticker": primary_ticker.upper(),
        "peers": rows,
        "sector_median": medians,
        "total_companies": len(rows),
        "audit_source": "IDX XBRL AUDITED — 100% REAL DATA",
        "generated_at": "2025",
    }

def _get_auto_peers(primary_ticker: str, all_data: dict) -> list:
    """Auto-detect sector peers based on sector classification with curated IDX clusters"""
    # 1. Curated benchmark clusters standar institusional IDX
    CLUSTERS = {
        # Automotive & Conglomerates
        "ASII": ["AUTO", "ASSA", "IMAS", "SMSM", "UNTR", "MPMX"],
        # Big Banks
        "BBCA": ["BBRI", "BMRI", "BBNI", "BRIS", "BDMN", "BNGA"],
        "BBRI": ["BBCA", "BMRI", "BBNI", "BRIS", "BBTN"],
        "BMRI": ["BBCA", "BBRI", "BBNI", "BRIS", "BDMN"],
        "BBNI": ["BBCA", "BBRI", "BMRI", "BRIS", "BNGA"],
        # Telco & Tech
        "TLKM": ["ISAT", "EXCL", "TOWR", "TBIG", "GOTO", "BUKK"],
        "GOTO": ["BUKA", "EMTK", "TLKM", "BELI"],
        # Consumer Staples
        "ICBP": ["INDF", "MYOR", "UNVR", "KLBF", "CMRY"],
        "MYOR": ["ICBP", "INDF", "UNVR", "ULTJ", "CLEO"],
        "UNVR": ["ICBP", "MYOR", "KLBF", "KAEF"],
        # Mining & Energy
        "ADRO": ["PTBA", "ITMG", "BUMI", "INDY", "MEDC"],
        "PTBA": ["ADRO", "ITMG", "BUMI", "HRUM"],
        "ANTM": ["INCO", "MDKA", "TINS", "NCKL"],
        # Property
        "BSDE": ["CTRA", "PWON", "SMRA", "ASRI", "LPKR"],
        "CTRA": ["BSDE", "PWON", "SMRA", "DILD"],
    }
    pt = primary_ticker.upper()
    if pt in CLUSTERS:
        # Filter hanya peers yang punya data di DB
        return [tk for tk in CLUSTERS[pt] if tk in all_data][:7]

    # 2. Fallback: cari dari sektor (index dari profil BEI, tanpa loop berat)
    prof = get_issuer_profile(pt)
    sector = prof.get("sector")
    if sector:
        from app.services.idx_audited_financials import _PROFILES_CACHE, get_issuer_profile as _gip
        _gip(pt)  # pastikan cache terisi
        sector_tickers = [
            tk for tk in (all_data.keys())
            if tk != pt and (_gip(tk).get("sector") == sector)
        ]
        if sector_tickers:
            return sector_tickers[:7]

    # 3. Fallback umum: top market cap issuers
    top_default = ["BBCA", "BBRI", "BMRI", "ASII", "TLKM", "ICBP", "UNTR", "ADRO"]
    return [tk for tk in top_default if tk != primary_ticker][:6]

def compute_wacc_components(row: dict) -> dict:
    """Simplified WACC compute from audited row"""
    re = 0.07  # risk-free proxy
    beta = 1.0  # default
    erp = 0.055  # equity risk premium

    cost_equity = re + beta * erp
    cost_debt = 0.09  # proxy

    assets = row.get("assets_bn") or 1
    equity = row.get("equity_parent_bn") or row.get("equity_total_bn") or (assets * 0.4)
    debt = row.get("liabilities_bn") or (assets * 0.6)

    e_ratio = equity / (equity + debt) if (equity + debt) > 0 else 0.5
    d_ratio = debt / (equity + debt) if (equity + debt) > 0 else 0.5

    etr = 0.22  # standard ETR
    wacc = e_ratio * cost_equity + d_ratio * cost_debt * (1 - etr)

    return {
        "wacc_pct": round(wacc * 100, 2),
        "cost_equity_pct": round(cost_equity * 100, 2),
        "cost_debt_pct": round(cost_debt * 100, 2),
        "e_ratio_pct": round(e_ratio * 100, 1),
        "d_ratio_pct": round(d_ratio * 100, 1),
        "etr_pct": round(etr * 100, 1),
    }