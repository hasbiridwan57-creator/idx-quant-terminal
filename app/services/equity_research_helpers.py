"""
CFA Figure 28 & 29: WACC/CAPM Build-Up & Figure 31 & 32: Peer Comps Extended & DuPont 5-Way
Institutional calculation, no synthetic data.
"""

def build_wacc_components(financials, beta_raw, current_price, shares_bn, is_bank, ticker):
    """
    Build Cost of Equity (CAPM) + Cost of Debt + WACC.
    Rf = SBN 10Y Indonesia (~6.8%)
    ERP = Damodaran Indonesia (~6.5%)
    Beta = covariance vs IHSG dari XBRL 24-bulan price series
    """
    rf = 0.068  # SBN 10Y Indonesia
    erp = 0.065  # Damodaran ERP + country risk
    latest = financials[-1] if financials else {}

    # Beta: regresi return harian vs IHSG (5 tahun) bila tersedia, lalu beta
    # sektor Damodaran, baru terakhir 1,0. Versi lama SELALU 1,0 -> Ke identik
    # untuk semua emiten (13,3%), mengabaikan risiko masing-masing.
    beta = beta_raw
    beta_src = None
    if beta is None:
        try:
            from sqlmodel import Session as _S
            from app.db.database import engine as _eng
            from app.services.cost_of_capital import _get_beta as _gb
            _sector = (latest.get("sector") or None)
            with _S(_eng) as _sess:
                beta, beta_src = _gb(_sess, ticker, _sector)
        except Exception:
            beta, beta_src = None, None
    if beta is None:
        beta, beta_src = 1.0, "PROXY (beta pasar default 1.0 — data tidak tersedia)"
    elif beta_src is None:
        beta_src = "COMPUTED (beta dari pemanggil)"
    ke = rf + beta * erp  # Cost of Equity

    # Market cap & debt (dalam miliar Rp)
    # UNIT: shares_bn = JUTA lembar, curr_p = Rp/saham.
    #   juta lembar × Rp/saham = Rp JUTA  -> bagi 1.000 = Rp MILIAR
    # (versi lama lupa membagi 1.000 sehingga market cap 1.000x terlalu besar
    #  dan bobot ekuitas WACC jadi 99,89% — mustahil.)
    # NULL-SAFE: emiten tersuspensi/delisting (WSKT, SRIL) tidak punya harga,
    # jadi market_cap = None. Bobot WACC lalu N/A — TIDAK dikarang.
    market_cap = ((current_price * shares_bn) / 1000.0) if (current_price and shares_bn) else None
    liabilities = latest.get("liabilities_bn") or 0.0
    equity_bn = latest.get("equity_parent_bn") or 0.0

    cod_source = "N/A (bank)"
    if is_bank:
        # Bank: tidak ada "total debt" korporat. Seluruh liabilities adalah
        # dana pihak ketiga (costed). WACC bank tidak dihitung dari bobot
        # debt/equity; bank dinilai dengan Justified PBV memakai Cost of Equity.
        total_debt = 0.0
        total_cap = market_cap
        we = 1.0
        wd = 0.0
        if market_cap is None:      # bank tanpa harga -> WACC = Ke saja (tetap valid)
            total_cap = None
        cod_pre_tax = None
        kd_post_tax = None
    else:
        # Non-bank: interest-bearing debt TIDAK punya tag tunggal di XBRL.
        # Gunakan Total Liabilities sebagai PROXY konservatif (upper bound WACC),
        # dan tandai secara eksplisit agar tidak dibaca sebagai angka pasti.
        total_debt = liabilities
        if market_cap is None:
            total_cap = None
            we = wd = None
        else:
            total_cap = market_cap + total_debt
            we = market_cap / total_cap if total_cap > 0 else None
            wd = total_debt / total_cap if total_cap > 0 else None
        # Kd (cost of debt) = beban keuangan / rata-rata pinjaman berbunga.
        # MASALAH: XBRL BEI tidak punya tag pinjaman berbunga untuk non-bank
        # (st_debt coverage 0), sehingga pembagi yang tersedia hanyalah TOTAL
        # LIABILITAS yang didominasi utang usaha -> Kd 1,72% (mustahil untuk
        # emiten Indonesia, SBN saja 6,8%).
        # Solusi: Kd = Rf + spread kredit korporasi (2,5%) sebagai ESTIMASI
        # STRUKTURAL yang diberi label eksplisit. Rumus lama menghasilkan WACC
        # 7,0% dan klaim "UNDERVALUED +241%" yang tidak dapat dipertanggungjawabkan.
        fc = latest.get("finance_costs_bn") or 0.0
        cod_pre_tax = fc / total_debt if total_debt > 0 else None
        if cod_pre_tax is None or not (0.06 <= cod_pre_tax <= 0.20):
            cod_pre_tax = rf + 0.025          # Rf + spread korporasi AA
            cod_source = "ESTIMASI (Rf + spread kredit 2,5%)"
        else:
            cod_source = "COMPUTED (beban keuangan / liabilitas)"

    # Effective Tax Rate — pakai pretax_bn sesuai key di historical_financials
    # ETR: KUNCI TOLERAN. Pipeline mengirim `profit_before_tax_bn`, bukan
    # `pretax_bn` — versi lama hanya membaca nama yang salah sehingga ETR
    # selalu 0,0% dan Kd after-tax = Kd pre-tax (WACC terlalu rendah).
    # XBRL BEI mencatat beban pajak NEGATIF -> pakai nilai absolut.
    pbt = latest.get("pretax_bn", latest.get("profit_before_tax_bn")) or 0.0
    tax = abs(latest.get("tax_provision_bn") or 0.0)
    etr = min(max(tax / pbt, 0.0), 0.50) if pbt > 0 else 0.0
    kd_post_tax = (cod_pre_tax * (1.0 - etr)) if cod_pre_tax is not None else None

    if is_bank:
        wacc = ke
    elif we is not None and wd is not None:
        wacc = we * ke + wd * (kd_post_tax or 0.0)
    else:
        # Tanpa harga pasar, bobot struktur modal tidak dapat dihitung.
        wacc = None

    # Justified PBV (bank valuation standar CFA / FIG):
    # PBV = (ROE - g) / (Ke - g). Hanya valid bila Ke > g dan ROE > 0.
    justified_pbv = None
    justified_pbv_note = None
    if is_bank:
        ni = latest.get("net_income_parent_bn")
        g = 0.04  # asumsi pertumbuhan abadi bank = 4% (di bawah nominal PDB)
        if ni is not None and equity_bn and equity_bn > 0:
            roe_dec = ni / equity_bn
            if ke > g:
                justified_pbv = round((roe_dec - g) / (ke - g), 2)
                justified_pbv_note = "ROE & Ke dari XBRL audited + CAPM"
            else:
                justified_pbv_note = "Ke <= g, formula tidak valid"
        else:
            justified_pbv_note = "ROE/equity tidak tersedia"

    return {
        "rf_pct": round(rf * 100, 2),
        "erp_pct": round(erp * 100, 2),
        "beta": round(beta, 3),
        "ke_pct": round(ke * 100, 2),
        "cod_pre_tax_pct": round(cod_pre_tax * 100, 2) if cod_pre_tax else None,
        "kd_post_tax_pct": round(kd_post_tax * 100, 2) if kd_post_tax else None,
        "etr_pct": round(etr * 100, 2),
        # NULL-SAFE: None tetap None (N/A di UI/PDF), bukan crash.
        "we_pct": round(we * 100, 2) if we is not None else None,
        "wd_pct": round(wd * 100, 2) if wd is not None else None,
        "wacc_pct": round(wacc * 100, 2) if wacc is not None else None,
        "market_cap_bn": round(market_cap, 1) if market_cap is not None else None,
        "total_debt_bn": round(total_debt, 1) if total_debt is not None else None,
        "total_cap_bn": round(total_cap, 1) if total_cap is not None else None,
        "justified_pbv": justified_pbv,
        "justified_pbv_note": justified_pbv_note,
        "method": "BANK_JUSTIFIED_PBV" if is_bank else "STANDARD_CAPM",
        "debt_provenance": "N/A (bank)" if is_bank else "PROXY: total liabilities",
        "cod_source": cod_source if not is_bank else "N/A (bank)",
        "provenance": {
            "rf": "ASSUMPTION (SBN 10Y Indonesia)",
            "erp": "ASSUMPTION (Damodaran Indonesia)",
            "beta": beta_src,
            "ke": "COMPUTED (CAPM)",
            "wacc": "COMPUTED",
            "justified_pbv": "COMPUTED" if justified_pbv is not None else "N/A",
        },
    }


def build_dupont_5way(financial_row, ticker):
    """
    DuPont 5-Way Analysis:
    ROE = Tax Burden × Interest Burden × Operating Margin × Asset Turnover × Equity Multiplier
    ROE = (NI/PBT) × (PBT/EBIT) × (EBIT/Sales) × (Sales/Assets) × (Assets/Equity)
    """
    ni = financial_row.get("net_income_parent_bn")
    pbt = financial_row.get("profit_before_tax_bn")
    ebit = financial_row.get("ebit_bn")
    rev = financial_row.get("revenue_bn")
    assets = financial_row.get("assets_bn")
    equity = financial_row.get("equity_parent_bn")

    if not all([ni, pbt, ebit, rev, assets, equity]):
        return None

    tax_burden = ni / pbt if pbt != 0 else 0.0
    interest_burden = pbt / ebit if ebit != 0 else 0.0
    operating_margin = ebit / rev if rev != 0 else 0.0
    asset_turnover = rev / assets if assets != 0 else 0.0
    equity_multiplier = assets / equity if equity != 0 else 0.0

    roe_decomposed = tax_burden * interest_burden * operating_margin * asset_turnover * equity_multiplier
    roe_direct = ni / equity if equity != 0 else 0.0

    return {
        "tax_burden_pct": round(tax_burden * 100, 2),
        "interest_burden_pct": round(interest_burden * 100, 2),
        "operating_margin_pct": round(operating_margin * 100, 2),
        "asset_turnover_x": round(asset_turnover, 2),
        "equity_multiplier_x": round(equity_multiplier, 2),
        "roe_decomposed_pct": round(roe_decomposed * 100, 2),
        "roe_direct_pct": round(roe_direct * 100, 2),
        "year": financial_row.get("year"),
    }


def extend_peer_comps(peer_list, ticker_ref):
    """
    Tambahkan kolom institusional ke peer comps.
    peer_list bisa berupa:
      - list of str (['AUTO', 'UNTR', ...])
      - list of dict ([{'ticker': 'AUTO', ...}])
    Ambil metrik audited riil dari loader idx_audited_financials.
    """
    from app.services.idx_audited_financials import five_year_table
    extended = []
    for item in peer_list:
        if isinstance(item, str):
            p_ticker = item.upper()
            ext = {"ticker": p_ticker}
        elif isinstance(item, dict):
            ext = dict(item)
            p_ticker = (ext.get("ticker") or "").upper()
        else:
            continue

        try:
            p_hist = five_year_table(p_ticker)
            if p_hist:
                last_p = p_hist[-1]
                ext["revenue_bn"] = last_p.get("revenue_bn")
                ext["net_income_bn"] = last_p.get("net_income_parent_bn")
                ext["equity_bn"] = last_p.get("equity_parent_bn")
                ext["assets_bn"] = last_p.get("assets_bn")
                gp = last_p.get("gross_profit_bn")
                se = last_p.get("selling_expense_bn") or 0.0
                ga = last_p.get("ga_expense_bn") or 0.0
                pbt = last_p.get("profit_before_tax_bn")
                fc = last_p.get("finance_costs_bn")
                fi = last_p.get("finance_income_bn") or 0.0
                if gp is not None:
                    ext["ebit_bn"] = round(gp - se - ga, 1)
                elif pbt is not None and fc is not None:
                    ext["ebit_bn"] = round(pbt + fc - fi, 1)
                else:
                    ext["ebit_bn"] = None

                if ext.get("ebit_bn") is not None and ext.get("revenue_bn"):
                    ext["ebit_margin_pct"] = round(ext["ebit_bn"] / ext["revenue_bn"] * 100.0, 1)

                ni = ext.get("net_income_bn")
                eq = ext.get("equity_bn")
                if ni and eq and eq > 0:
                    ext["roe"] = round(ni / eq * 100.0, 1)
        except Exception:
            pass

        extended.append(ext)
    return extended
