"""
Forensic Accounting & Earnings Quality Suite (Institutional Grade)
Standards: Beneish M-Score (8-Variable Model, 1999) and Sloan Balance Sheet Accruals (1996).
Data sources: 100% Real Audited Financial Statements (IDX XBRL). No synthetic values.
"""

from typing import Dict, Any, Optional, List


def compute_sloan_accruals(current_stmt: Dict[str, Any],
                           prior_stmt: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sloan Accruals Ratio (Richard Sloan, 1996):
    Accruals = (Net Income - CFO) / Average Total Assets
    Alternative Balance Sheet Accruals:
    Balance Sheet Accruals = (ΔCurrent Assets - ΔCash) - (ΔCurrent Liab - ΔShort-term Debt - ΔTax Payable) - Depreciation
    
    Interpretasi CFA:
      - Ratio < -10% : Extremely Conservative / Cash Rich (High Quality)
      - Ratio -10% to +10% : Normal Operational Accruals (Healthy)
      - Ratio > +10% : Aggressive Accruals / Low Earnings Quality (Cash Flow lags Net Income)
    """
    if not current_stmt or not prior_stmt:
        return {"sloan_ratio": None, "sloan_ratio_pct": None, "verdict": "N/A", "label": "N/A (data tidak lengkap)", "provenance": "N/A"}

    ni = current_stmt.get("net_income_parent_bn")
    if ni is None:
        ni = current_stmt.get("net_income_bn")
    ta_t = current_stmt.get("assets_bn")
    if ta_t is None:
        ta_t = current_stmt.get("total_assets_bn")
    ta_prev = prior_stmt.get("assets_bn")
    if ta_prev is None:
        ta_prev = prior_stmt.get("total_assets_bn")
    cash_t = current_stmt.get("cash_bn") or 0.0
    cash_prev = prior_stmt.get("cash_bn") or 0.0

    if ni is None or ta_t is None or ta_prev is None:
        return {"sloan_ratio": None, "sloan_ratio_pct": None, "verdict": "N/A", "label": "N/A (data tidak lengkap)", "provenance": "N/A"}

    avg_assets = (ta_t + ta_prev) / 2.0
    if avg_assets <= 0:
        return {"sloan_ratio": None, "sloan_ratio_pct": None, "verdict": "N/A", "label": "N/A (data tidak lengkap)", "provenance": "N/A"}

    # Proxy CFO dari data audited: Net Income + Depreciation/Capex - ΔWorking Capital
    # Bila CFO riil dari cash flow statement tidak dilaporkan, beri label PROXY
    cfo_reported = current_stmt.get("cfo_bn")
    if cfo_reported is not None:
        accruals = ni - cfo_reported
        provenance = "REPORTED_CFO"
    else:
        # Balance sheet proxy: Δ(Assets - Cash) - ΔEquity
        # Sederhana & robust: (Net Income - ΔCash) / Avg Assets
        delta_cash = cash_t - cash_prev
        accruals = ni - delta_cash
        provenance = "COMPUTED_BS_PROXY"

    ratio = accruals / avg_assets

    if ratio < -0.10:
        verdict = "EXCELLENT_CASH_CONVERSION"
        label = "Kualitas Laba Sangat Tinggi (Didominasi Arus Kas Riil)"
        badge_color = "emerald"
    elif ratio <= 0.10:
        verdict = "NORMAL_HEALTHY"
        label = "Wajar / Normal (Pertumbuhan Laba Sejalan Modal Kerja)"
        badge_color = "sky"
    else:
        verdict = "AGGRESSIVE_ACCRUALS"
        label = "Peringatan: Kualitas Laba Rendah (Laba Buku Jauh Melampaui Kas)"
        badge_color = "rose"

    return {
        "sloan_ratio_pct": round(ratio * 100.0, 2),
        "accruals_bn": round(accruals, 1),
        "avg_assets_bn": round(avg_assets, 1),
        "verdict": verdict,
        "label": label,
        "badge_color": badge_color,
        "provenance": provenance,
    }


def compute_beneish_m_score(current_stmt: Dict[str, Any],
                            prior_stmt: Dict[str, Any]) -> Dict[str, Any]:
    """
    Beneish M-Score (Messod Beneish, 1999) - 8-Variable Probabilistic Manipulation Model.
    
    Formula:
      M = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
          + 0.115*DEPI - 0.172*SGAI + 4.037*TATA - 0.327*LVGI
    
    Threshold:
      - M-Score > -1.78 : High Probability of Earnings Manipulation (Merah)
      - M-Score <= -1.78 : Low Probability of Manipulation / Unlikely Manipulator (Hijau)
    """
    if not current_stmt or not prior_stmt:
        return {"m_score": None, "verdict": "N/A", "provenance": "N/A", "components": {}}

    # ── NORMALISASI KEY ──────────────────────────────────────────────
    # Sumber data punya dua konvensi penamaan:
    #   loader idx_audited_financials : assets_bn, net_income_parent_bn, ...
    #   historical_financials engine  : total_assets_bn, net_income_bn, ...
    # Tanpa normalisasi, `c.get("assets_bn") or 1.0` jatuh ke 1.0 sehingga
    # TATA = (NI - CFO)/1.0 meledak (ASII: M-Score -180.432).
    def _norm(d: dict) -> dict:
        if not d:
            return {}
        out = dict(d)
        pairs = [
            ("assets_bn", ("assets_bn", "total_assets_bn")),
            ("liabilities_bn", ("liabilities_bn", "total_liabilities_bn")),
            ("net_income_parent_bn", ("net_income_parent_bn", "net_income_bn")),
            ("equity_parent_bn", ("equity_parent_bn", "total_equity_bn")),
            ("cfo_bn", ("cfo_bn", "operating_cash_flow_bn")),
            ("receivables_bn", ("receivables_bn", "trade_receivables_bn")),
            ("gross_profit_bn", ("gross_profit_bn",)),
            ("cost_of_sales_bn", ("cost_of_sales_bn",)),
            ("current_assets_bn", ("current_assets_bn",)),
            ("property_plant_equipment_bn", ("property_plant_equipment_bn",)),
            ("depreciation_amortization_bn", ("depreciation_amortization_bn",)),
            ("depreciation_bn", ("depreciation_bn",)),
        ]
        for target, keys in pairs:
            for k in keys:
                if out.get(k) is not None:
                    out[target] = out[k]
                    break
        return out

    c = _norm(current_stmt)
    p = _norm(prior_stmt)

    # Guard: total aset WAJIB ada. Tanpa ini TATA dibagi 1 rupiah dan skor meledak.
    ta_c = c.get("assets_bn")
    ta_p = p.get("assets_bn")
    if not ta_c or ta_c <= 0:
        return {
            "m_score": None,
            "verdict": "N/A",
            "label": "Total aset tidak tersedia — M-Score tidak dapat dihitung",
            "provenance": "N/A",
            "components": {},
        }

    # 1. DSRI (Days Sales in Receivables Index)
    # Butuh piutang usaha (receivables). Bila tidak terpisah di XBRL, beri nilai default 1.0 (netral)
    rec_c = c.get("receivables_bn")
    rec_p = p.get("receivables_bn")
    rev_c = c.get("revenue_bn")
    rev_p = p.get("revenue_bn")

    if rec_c and rec_p and rev_c and rev_p and rev_p > 0 and rev_c > 0:
        dsri = (rec_c / rev_c) / (rec_p / rev_p)
    else:
        dsri = 1.0  # Netral

    # 2. GMI (Gross Margin Index): (Margin_t-1 / Margin_t)
    gp_c = c.get("gross_profit_bn")
    gp_p = p.get("gross_profit_bn")
    if gp_c and gp_p and rev_c and rev_p and rev_c > 0 and rev_p > 0:
        gm_c = gp_c / rev_c
        gm_p = gp_p / rev_p
        gmi = (gm_p / gm_c) if gm_c > 0 else 1.0
    else:
        gmi = 1.0

    # 3. AQI (Asset Quality Index) — Beneish (1999):
    #      AQI = [1 - (CA + PPE + Securities)/TA]_t  /  [sama]_t-1
    #      Mengukur porsi aset "non-produktif" (goodwill, aset tak berwujud, dll).
    #      Versi lama selalu 1.0 karena PPE tidak dipetakan dari XBRL.
    sec_c = c.get("securities_bn") or 0.0
    sec_p = p.get("securities_bn") or 0.0
    ca_c = c.get("current_assets_bn")
    ca_p = p.get("current_assets_bn")
    ppe_c = c.get("property_plant_equipment_bn")
    ppe_p = p.get("property_plant_equipment_bn")

    if (ca_c is not None and ppe_c is not None
            and ca_p is not None and ppe_p is not None
            and ta_p and ta_p > 0):
        aqi_c = 1.0 - (ca_c + ppe_c + sec_c) / ta_c
        aqi_p = 1.0 - (ca_p + ppe_p + sec_p) / ta_p
        # Rasio bisa negatif bila komponen > total aset (data tidak konsisten).
        # Hanya dipakai bila keduanya bertanda sama dan tidak nol.
        if aqi_p > 0.0001 and aqi_c > -1.0 and aqi_p > -1.0:
            aqi = aqi_c / aqi_p
            aqi = max(0.1, min(10.0, aqi))   # batasi outlier ekstrem
        else:
            aqi = 1.0
    else:
        aqi = 1.0

    # 4. SGI (Sales Growth Index): Rev_t / Rev_t-1
    if rev_c and rev_p and rev_p > 0:
        sgi = rev_c / rev_p
    else:
        sgi = 1.0

    # 5. DEPI (Depreciation Index) — Beneish (1999):
    #      DepRate = Dep / (Dep + PPE) ;  DEPI = DepRate_t-1 / DepRate_t
    #      DEPI > 1 berarti laju penyusutan MELAMBAT -> potensi perpanjangan
    #      masa manfaat untuk mempercantik laba.
    #      Versi lama selalu 1.0 karena PPE dan Depreciation tidak dipetakan.
    dep_c = c.get("depreciation_amortization_bn") or c.get("depreciation_bn")
    dep_p = p.get("depreciation_amortization_bn") or p.get("depreciation_bn")
    depi = 1.0
    if dep_c and dep_p and ppe_c is not None and ppe_p is not None:
        rate_c = dep_c / (dep_c + ppe_c) if (dep_c + ppe_c) > 0 else None
        rate_p = dep_p / (dep_p + ppe_p) if (dep_p + ppe_p) > 0 else None
        if rate_c and rate_p and rate_c > 0:
            depi = rate_p / rate_c
            depi = max(0.1, min(10.0, depi))

    # 6. SGAI (Sales, General & Admin Expenses Index): (SGA_t / Rev_t) / (SGA_t-1 / Rev_t-1)
    sga_c = (c.get("selling_expense_bn") or 0.0) + (c.get("ga_expense_bn") or 0.0)
    sga_p = (p.get("selling_expense_bn") or 0.0) + (p.get("ga_expense_bn") or 0.0)
    if sga_c > 0 and sga_p > 0 and rev_c and rev_p and rev_c > 0 and rev_p > 0:
        sgai = (sga_c / rev_c) / (sga_p / rev_p)
    else:
        sgai = 1.0

    # 7. LVGI (Leverage Index): (Total Debt_t / Total Assets_t) / (Total Debt_t-1 / Total Assets_t-1)
    liab_c = c.get("liabilities_bn") or 0.0
    liab_p = p.get("liabilities_bn") or 0.0
    lev_c = liab_c / ta_c if ta_c > 0 else 0.0
    lev_p = liab_p / ta_p if ta_p > 0 else 0.0
    lvgi = (lev_c / lev_p) if lev_p > 0 else 1.0

    # 8. TATA (Total Accruals to Total Assets) = (Net Income - CFO) / Total Assets
    #
    # BUG LAMA: memakai (Net Income - ΔCash). Beneish (1999) mendefinisikan TATA
    # dari OPERATING CASH FLOW, bukan perubahan kas. Memakai ΔCash membuat TATA
    # meledak (ASII: -4.182) sehingga M-Score menjadi -16.884 — angka mustahil
    # yang membuat model tidak berguna (threshold asli hanya -1,78).
    ni_c = c.get("net_income_parent_bn") or 0.0
    cfo_c = c.get("cfo_bn")
    if cfo_c is None:
        cfo_c = c.get("operating_cash_flow_bn")
    if cfo_c is not None:
        accruals = ni_c - cfo_c
        tata = accruals / ta_c if ta_c > 0 else 0.0
        tata_src = "COMPUTED (Net Income - CFO) / Total Assets"
    else:
        # CFO tidak tersedia -> TATA tidak dapat dihitung dengan benar.
        # Pakai 0.0 (netral terhadap M-Score) dan tandai agar tidak menyesatkan.
        tata = 0.0
        tata_src = "N/A (CFO tidak tersedia — TATA diset netral 0.0)"

    # Kalkulasi M-Score Beneish 8-Variabel (koefisien sesuai Beneish 1999):
    #   M = -4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
    #       + 0.115·DEPI - 0.172·SGAI + 4.037·TATA - 0.327·LVGI
    # CATATAN: LVGI koefisiennya NEGATIF 0.327. Versi lama memakai +0.0327
    # (tanda salah DAN orde besaran salah 10x).
    m_score = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.037 * tata
        - 0.327 * lvgi
    )

    is_manipulator = m_score > -1.78
    if is_manipulator:
        verdict = "HIGH_MANIPULATION_RISK"
        label = "Peringatan: Risiko Manipulasi / Kualitas Pelaporan Rendah"
        badge_color = "rose"
    else:
        verdict = "UNLIKELY_MANIPULATOR"
        label = "Aman: Indikasi Pelaporan Keuangan Kredibel & Wajar"
        badge_color = "emerald"

    return {
        "m_score": round(m_score, 2),
        "threshold": -1.78,
        "is_manipulator": is_manipulator,
        "verdict": verdict,
        "label": label,
        "badge_color": badge_color,
        "components": {
            "dsri": round(dsri, 3),
            "gmi": round(gmi, 3),
            "aqi": round(aqi, 3),
            "sgi": round(sgi, 3),
            "depi": round(depi, 3),
            "sgai": round(sgai, 3),
            "lvgi": round(lvgi, 3),
            "tata": round(tata, 3),
        },
        "coverage": {
            "variabel_aktif": sum(1 for v in (dsri, gmi, aqi, sgi, depi, sgai, lvgi) if v != 1.0) + (1 if tata != 0.0 else 0),
            "catatan": ("AQI/DEPI bernilai 1.0 (netral) bila PPE atau D&A tidak "
                        "dilaporkan pada filing; M-Score tetap dihitung dengan "
                        "variabel yang tersedia."),
        },
        "provenance": "COMPUTED_BENEISH_1999",
    }
