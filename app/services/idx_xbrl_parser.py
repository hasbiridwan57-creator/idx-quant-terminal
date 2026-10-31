"""
Parse XBRL IDX (audited FY) -> dict metrik fundamental.
ZERO-FAKE: hanya ambil konsep yang benar-benar ada di file. Tidak ada estimasi.
Satuan XBRL = rupiah penuh (unitRef IDR).
"""
import lzma
import re
from typing import Any, Dict, Optional

# Konsep yang dipakai, urut prioritas
CONCEPTS = {
    # P&L (duration)
    "revenue_sales": ["SalesAndRevenue", "RevenueFromSales", "Revenue"],
    "interest_income": ["InterestIncome"],
    "other_op_income": ["IncomeFromOtherOperatingTransactions", "OtherOperatingIncome"],
    "gross_profit": ["GrossProfit"],
    "operating_expense": ["GeneralAndAdministrativeExpenses"],
    "profit_before_tax": ["ProfitLossBeforeIncomeTax"],
    "net_income_total": ["ProfitLoss"],
    "net_income_parent": ["ProfitLossAttributableToParentEntity"],
    "eps": ["BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsLossPerShare"],
    # Bank syariah
    "mudharib_revenue": ["RevenueFromFundManagementAsMudharib"],
    "third_party_profit_share": ["ThirdPartiesShareOnReturnOfTemporarySyirkahFunds"],
    "psak_revenue": ["SalesAndRevenue"],
    # Multifinance / sekuritas / asuransi (tak ada baris "Pendapatan" tunggal)
    "administration_income": ["AdministrationIncome"],
    "income_consumer_financing": ["IncomeFromConsumerFinancing"],
    "income_finance_lease": ["IncomeFromFinanceLease"],
    "income_murabahah": ["IncomeFromMurabahahAndIstishna"],
    "income_provision_commission": ["IncomeFromProvisionsAndCommissions"],
    "recovery_written_off": ["IncomeFromRecoveryOfWrittenOffAssets"],
    "income_ijarah": ["IncomeFromIjarah"],
    "income_factoring": ["IncomeFromFactoring"],
    # Sekuritas / perusahaan investasi
    "income_brokerage": ["IncomeFromBrokerageActivity"],
    "income_investment_mgmt": ["IncomeFromInvestmentManagementServices"],
    "income_financing_tx": ["IncomeFromFinancingTransactions"],
    "income_underwriting": ["IncomeFromUnderwritingActivitiesAndSellingFees"],
    "finance_income": ["FinanceIncome"],
    "other_income": ["OtherIncome"],
    # Asuransi
    "insurance_premiums": ["RevenueFromInsurancePremiums"],
    "receipts_premiums": ["ReceiptsFromInsurancePremiums"],
    "net_investment_income": ["NetInvestmentIncome"],
    "receipts_investment_income": ["ReceiptsOfInvestmentIncome"],
    # Balance sheet (instant)
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity_total": ["Equity"],
    "equity_parent": ["EquityAttributableToEquityOwnersOfParentEntity",
                      "EquityAttributableToParentEntity"],
    # Bank melaporkan `Cash` (bukan CashAndCashEquivalents).
    # 258 dari 281 record bank kehilangan kas karena tag ini tidak dipetakan
    # -> net cash N/A dan net debt salah di seluruh valuasi bank.
    "cash": ["CashAndCashEquivalents", "Cash"],
    # Neraca terklasifikasi (non-bank) — untuk Altman Z'' dan Invested Capital presisi
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "non_current_assets": ["NonCurrentAssets"],
    "non_current_liabilities": ["NonCurrentLiabilities"],
    "retained_earnings_unappropriated": ["UnappropriatedRetainedEarnings"],
    "retained_earnings_appropriated": ["AppropriatedRetainedEarnings"],
    # Utang jangka pendek berbunga (untuk memisahkan interest-bearing dari CL)
    "current_maturities_bank_loans": ["CurrentMaturitiesOfBankLoans"],
    "short_term_bank_loans": ["ShortTermBankLoans"],
    "current_maturities_bonds": ["CurrentMaturitiesOfBondsPayable"],
    "current_maturities_lease": ["CurrentMaturitiesOfFinanceLeaseLiabilities"],
    # Aset tidak lancar produktif — untuk AQI/DEPI Beneish yang benar.
    # AQI = [1 - (CA + PPE + Securities)/TA]  -> butuh PPE.
    # DEPI = DepRate_t-1 / DepRate_t, DepRate = Dep / (Dep + PPE).
    "property_plant_equipment": ["PropertyPlantAndEquipment"],
    "investment_property": ["InvestmentProperty"],
    "intangible_assets": ["IntangibleAssetsOtherThanGoodwill"],
    "loans_gross": ["TotalLoansGross"],
    "selling_expense": ["SellingExpenses"],
    "ga_expense": ["GeneralAndAdministrativeExpenses"],
    "finance_costs": ["InterestAndFinanceCosts", "FinanceCosts"],
    "interest_expense": ["InterestExpenses", "BorrowingsInterestExpense"],
    # Bank / FIG: PPOP asli dari filing (BUKAN proxy)
    "ppop": ["ProfitFromOperation"],
    "interest_income_bank": ["InterestIncome"],
    # Beban CKPN / impairment yang diakui di laba rugi (nama tag XBRL IDX sebenarnya)
    "impairment_losses": ["ProvisionDuringTheYearofAllowanceforImpairmentLossesonLoans",
                          "ProvisionDuringTheYearOfAllowanceForImpairmentLossesOnShariaReceivables"],
    # Saldo penyisihan CKPN (neraca)
    "allowance_impairment_loans": ["AllowanceForImpairmentLossesForLoans"],
    # Portofolio kredit bruto/neto (nama tag sebenarnya di taksonomi IDX)
    "loans_gross_tag": ["TotalLoansGross"],
    "loans_net_tag": ["TotalLoansNet"],
    "loans_third_parties": ["LoansThirdParties"],
    "loans_related_parties": ["LoansRelatedParties"],
    # HPP (Cost of Sales and Revenue) — derivasi gross profit
    "cost_of_sales": ["CostOfSalesAndRevenue"],
    "other_operating_income": ["OtherOperatingIncome"],
    "total_loans": ["TotalLoansGross", "TotalLoansNet"],
    "other_operating_expenses": ["OtherOperatingExpenses"],
    # D&A (flow) — untuk EBITDA yang jujur. Tag Depreciation & Amortization terpisah di IDX.
    "depreciation": ["Depreciation", "DepreciationAndAmortisationExpenses"],
    "amortization": ["Amortization"],
    # Working capital (instant) — untuk Cash Conversion Cycle
    "inventories": ["Inventories", "CurrentInventories"],
    "trade_receivables": ["TradeReceivablesThirdParties", "TradeReceivablesRelatedParties"],
    "trade_payables": ["TradePayablesThirdParties", "TradePayablesRelatedParties"],
    # Arus kas operasi (CFO) — tag ada di 4.185/4.185 filing. Wajib untuk Sloan Accruals.
    "operating_cash_flow": ["NetCashFlowsReceivedFromUsedInOperatingActivities",
                            "CashFlowsFromUsedInOperatingActivities"],
    # Beban pajak P&L: cari konsep yang benar (bukan arus kas)
    "tax_expense": ["TaxBenefitExpenses", "TaxExpense", "IncomeTaxExpense", "CurrentTaxExpense"],
    # Dividen kas dibayar — PAYOUT RATIO riil (g = ROE x (1 - payout)).
    # Konsep "DistributionsOfCashDividends" ada di 4.185/4.185 filing.
    "dividends_paid": ["DistributionsOfCashDividends",
                       "DividendsPaidFromFinancingActivities",
                       "DividendsPaidFromOperatingActivities"],
    "treasury_stock": ["TreasuryStocks"],
    "npl_gross": ["NonPerformingFinancingGross"],
    "npl_net": ["NonPerformingFinancingNet"],
    # Capex = PPE + Intangible (keduanya komponen investasi). Tag filing BEI
    # memakai "PropertyAndEquipment" (bukan "...PlantAndEquipment").
    "capex_ppe": ["PaymentsForAcquisitionOfPropertyAndEquipment",
                  "PaymentsForAcquisitionOfPropertyPlantAndEquipment"],
    "capex_intangible": ["PaymentsForAcquisitionOfIntangibleAssets"],
    # Syariah: total liabilitas wajib + dana syirkah temporer (PSAK 101/105)
    "liab_syirkah_equity": ["LiabilitiesTemporarySyirkahFundsAndEquity"],
    "temporary_syirkah": ["TemporarySyirkahFunds"],
}

_MAIN_CTX_DUR = ("CurrentYearDuration", "PriorYearDuration")
_MAIN_CTX_INST = ("CurrentYearInstant", "PriorEndYearInstant")


def _extract(raw: str, concept: str):
    """Return list of (contextRef, unitRef, value_str) untuk exact concept (bukan prefix)."""
    out = []
    pat = re.compile(r"<idx-cor:" + concept + r"\b([^>]*)>([-\d.,]+)</idx-cor:" + concept + r">")
    for m in pat.finditer(raw):
        attrs, val = m.group(1), m.group(2)
        ctx = re.search(r'contextRef="([^"]+)"', attrs)
        unit = re.search(r'unitRef="([^"]+)"', attrs)
        out.append((ctx.group(1) if ctx else "", unit.group(1) if unit else "", val))
    return out


def _num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def parse_xbrl_file(path: str) -> Dict[str, Any]:
    with lzma.open(path, "rb") as f:
        raw = f.read().decode("utf-8", "replace")

    res: Dict[str, Any] = {"parse_ok": False}
    currency = "IDR"
    if 'unitRef="USD"' in raw:
        currency = "USD"

    for field, candidates in CONCEPTS.items():
        is_flow = field in ("revenue_sales", "interest_income", "other_op_income",
                            "gross_profit", "operating_expense", "profit_before_tax",
                            "net_income_total", "net_income_parent", "eps",
                            "mudharib_revenue", "third_party_profit_share", "psak_revenue",
                            "administration_income", "income_consumer_financing",
                            "income_finance_lease", "income_murabahah",
                            "income_provision_commission", "recovery_written_off",
                            "income_ijarah", "income_factoring",
                            "income_brokerage", "income_investment_mgmt",
                            "income_financing_tx", "income_underwriting",
                            "finance_income", "other_income",
                            "insurance_premiums", "receipts_premiums",
                            "net_investment_income", "receipts_investment_income",
                            "selling_expense", "ga_expense", "tax_expense",
                            "finance_costs", "interest_expense",
                            "ppop", "interest_income_bank", "impairment_losses",
                            "cost_of_sales", "other_operating_income",
                            "other_operating_expenses", "depreciation", "amortization",
                            "operating_cash_flow",
                            "dividends_paid", "capex_ppe", "capex_intangible")
        allowed = _MAIN_CTX_DUR if is_flow else _MAIN_CTX_INST
        val = None
        used_concept = None
        for c in candidates:
            hits = [h for h in _extract(raw, c) if h[0] in allowed]
            # pilih context utama
            for want in allowed:
                for ctx, unit, v in hits:
                    if ctx == want:
                        n = _num(v)
                        if n is not None:
                            val = n
                            used_concept = c
                        break
                if val is not None:
                    break
            if val is not None:
                break
        res[field] = val
        if used_concept:
            res.setdefault("_concepts", {})[field] = used_concept

    # Capex = penjumlahan komponen (versi lama hanya mengambil tag pertama,
    # sehingga TLKM tercatat capex 2.897 B padahal PPE saja 22.871 B).
    _cpx = [abs(v) for v in (res.get("capex_ppe"), res.get("capex_intangible"))
            if isinstance(v, (int, float)) and v]
    res["capex"] = sum(_cpx) if _cpx else None
    if _cpx:
        res.setdefault("_concepts", {})["capex"] = "+".join(
            k for k in ("capex_ppe", "capex_intangible") if res.get(k))

    # --- REVENUE resolution (tiered, no invention) ---
    # Tier A: baris "Pendapatan"/"Penjualan" PSAK umum
    # Tier B: bank konvensional = InterestIncome + OtherOperatingIncome
    # Tier C: bank syariah = mudharib revenue - hak pihak ketiga dana syirkah
    # Tier D: multifinance/sekuritas/asuransi = penjumlahan baris pendapatan eksplisit
    if res.get("revenue_sales") is None:
        if (res.get("mudharib_revenue") or 0.0) > 0:
            tps = res.get("third_party_profit_share") or 0.0
            res["revenue_sales"] = res["mudharib_revenue"] + tps  # tps sudah negatif di XBRL
            res.setdefault("_concepts", {})["revenue_sales"] = "derived:Mudharib+ThirdPartyShare"
        elif (res.get("interest_income") or 0.0) > 0:
            oth = res.get("other_op_income") or 0.0
            res["revenue_sales"] = res["interest_income"] + oth
            res.setdefault("_concepts", {})["revenue_sales"] = "derived:InterestIncome+OtherOpIncome"
        else:
            parts = ["administration_income", "income_consumer_financing", "income_finance_lease",
                     "income_murabahah", "income_provision_commission", "income_ijarah",
                     "income_factoring", "recovery_written_off",
                     "income_brokerage", "income_investment_mgmt", "income_financing_tx",
                     "income_underwriting", "finance_income", "other_income"]
            got = {p: res.get(p) for p in parts if res.get(p) is not None}
            if got and sum(got.values()) > 0:
                res["revenue_sales"] = sum(got.values())
                res["_concepts"] = res.get("_concepts", {})
                res["_concepts"]["revenue_sales"] = "sum:" + "+".join(sorted(got))
            elif res.get("insurance_premiums") is not None:
                # asuransi: pendapatan premi + hasil investasi bersih
                rev = (res.get("insurance_premiums") or 0.0) + (res.get("net_investment_income") or 0.0)
                res["revenue_sales"] = rev
                res.setdefault("_concepts", {})["revenue_sales"] = "derived:Premiums+NetInvestmentIncome"

    # --- Neraca: sebagian bank (termasuk konvensional dengan unit syariah) melaporkan
    # "Liabilitas, Dana Syirkah Temporer dan Ekuitas" sebagai total. Jika total itu yang
    # cocok dengan aset sementara liabilitas+ekuitas tidak, maka dana syirkah temporer
    # MATERIAL dan wajib dipakai untuk uji neraca. Ini fakta terhitung, bukan label.
    a = res.get("assets")
    liab = res.get("liabilities")
    eq = res.get("equity_total")
    syk = res.get("liab_syirkah_equity")
    includes_syirkah = False
    if a and syk and abs(a - syk) / abs(a) < 0.005:
        gap = abs(syk - ((liab or 0.0) + (eq or 0.0)))
        if gap / abs(a) > 0.005:
            includes_syirkah = True
    res["balance_includes_syirkah"] = includes_syirkah
    res["balance_total_reported"] = syk if includes_syirkah else None
    res["is_syariah"] = False  # tidak diklaim: tak bisa dipastikan dari neraca saja

    # --- BANK: portofolio kredit bruto = LoansThirdParties + LoansRelatedParties ---
    if res.get("loans_gross") is None:
        ltp = res.get("loans_third_parties")
        lrp = res.get("loans_related_parties")
        if ltp is not None:
            res["loans_gross"] = ltp + (lrp or 0.0)
            res.setdefault("_concepts", {})["loans_gross"] = "derived:LoansThirdParties+LoansRelatedParties"
    if res.get("total_loans") is None and res.get("loans_gross") is not None:
        res["total_loans"] = res["loans_gross"]

    # --- Working capital: trade receivable/payable dipecah TP + RP, wajib dijumlah ---
    # Ekstrak dua komponen secara eksplisit (CONCEPTS hanya menyimpan hit pertama)
    for field, cands in (("_ar_tp", ["TradeReceivablesThirdParties"]),
                         ("_ar_rp", ["TradeReceivablesRelatedParties"]),
                         ("_ap_tp", ["TradePayablesThirdParties"]),
                         ("_ap_rp", ["TradePayablesRelatedParties"])):
        val_c = None
        for c in cands:
            for ctx, unit, v in _extract(raw, c):
                if ctx == "CurrentYearInstant":
                    val_c = _num(v)
                    break
            if val_c is not None:
                break
        res[field] = val_c
    _ar_tp, _ar_rp = res.pop("_ar_tp", None), res.pop("_ar_rp", None)
    _ap_tp, _ap_rp = res.pop("_ap_tp", None), res.pop("_ap_rp", None)
    if _ar_tp is not None or _ar_rp is not None:
        res["trade_receivables"] = (_ar_tp or 0.0) + (_ar_rp or 0.0)
        res.setdefault("_concepts", {})["trade_receivables"] = "derived:TradeReceivablesTP+RP"
    if _ap_tp is not None or _ap_rp is not None:
        res["trade_payables"] = (_ap_tp or 0.0) + (_ap_rp or 0.0)
        res.setdefault("_concepts", {})["trade_payables"] = "derived:TradePayablesTP+RP"

    # --- D&A gabungan: Depreciation + Amortization (keduanya flow terpisah di IDX) ---
    _dep, _amort = res.get("depreciation"), res.get("amortization")
    if _dep is not None or _amort is not None:
        res["depreciation_amortization"] = (_dep or 0.0) + (_amort or 0.0)
        res.setdefault("_concepts", {})["depreciation_amortization"] = "derived:Depreciation+Amortization"
    else:
        res["depreciation_amortization"] = None

    # --- GROSS PROFIT derivation (jika tidak dilaporkan langsung) ---
    # GrossProfit = SalesAndRevenue - CostOfSalesAndRevenue (identitas akuntansi)
    if res.get("gross_profit") is None:
        rev0 = res.get("revenue_sales")
        cogs = res.get("cost_of_sales")
        if rev0 is not None and cogs is not None and rev0 != 0:
            res["gross_profit"] = rev0 - cogs
            res.setdefault("_concepts", {})["gross_profit"] = "derived:SalesAndRevenue-CostOfSalesAndRevenue"

    # Bank/finansial: ada portofolio kredit, atau tak punya laba bruto & penjualan tapi punya pendapatan bunga/mudharib
    res["is_bank"] = bool(
        res.get("loans_gross") is not None
        or (res.get("gross_profit") is None
            and res.get("psak_revenue") is None
            and ((res.get("interest_income") or 0.0) > 0
                 or (res.get("mudharib_revenue") or 0.0) > 0))
    )

    res["currency"] = currency
    res["parse_ok"] = res.get("assets") is not None and res.get("net_income_parent") is not None
    return res


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:]:
        r = parse_xbrl_file(p)
        print(json.dumps({"file": p.split("/")[-1], **r}, indent=2, default=str))
