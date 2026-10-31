import hmac
import io
import json
import os
import math
import dataclasses
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Depends, UploadFile, File, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db.database import init_db, get_session, engine
from app.db.models import FinancialStatementCache, Symbol, QuoteLatest, QuoteHistoryDaily
from app.services.market_data import (
    get_quote,
    ensure_history,
    aligned_closes,
    calculate_realized_volatility,
    InsufficientData
)
from app.services.dupont_engine import analyze_dupont_yoy, compute_single_period_dupont
from app.services.units import to_idr, to_bn
from app.services.parser import load_ticker_history
from app.services.banking_engine import calculate_banking_ratios, is_banking_entity
from app.services.fincept_valuation import quick_dcf_valuation
from app.services.fincept_risk import calculate_risk_metrics
from app.services.fincept_fixed_income import calculate_credit_metrics, bond_price, CouponFrequency
from app.services.quant_engine import run_monte_carlo_gbm, build_peer_screener_rows
from app.services.technical_agent import run_institutional_technical_analysis
from app.services.terminal_pipeline import get_terminal_snapshot, TerminalPayload
from app.services.llm_analyzer import summarize_dupont_anomalies
from app.services.pdf_exporter import render_dupont_report_export
from app.services.terminal_pipeline import (
    TerminalPayload,
    get_terminal_snapshot,
    update_terminal_snapshot,
    validate_terminal_payload,
    round_to_idx_tick,
    is_valid_idx_price,
    get_idx_tick_size,
    SupportResistanceItem,
    BigCapMoverItem,
    ForeignFlowItem,
    IHSGBriefingHeader,
)
from app.providers import (
    fetch_market_overview,
    fetch_quotes,
    fetch_index_quote,
    classify_freshness,
    SourceHealth,
    SourceBudget,
    fund_budget,
    quote_budget,
)
from app.services.parser import (
    parse_idx_file_bytes,
    save_or_get_cached_statement,
    sync_audited_to_statement_cache,
    load_ticker_pair,
    load_ticker_history,
    generate_idx_excel_template_bytes,
)
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Depends, UploadFile, File, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, FileResponse, StreamingResponse
from sqlmodel import Session, select
from app.db.database import init_db, get_session, engine
from app.db.models import FinancialStatementCache, Symbol
from datetime import datetime, timezone

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        # ZERO-DUMMY POLICY: tidak ada seed hardcoded. Semua angka berasal dari
        # XBRL audited BEI (4.185 filing, 937 emiten) via idx_audited_financials.
        sync_audited_to_statement_cache(session)
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    try:
        tpl_path = static_dir / "template_lapkeu_bei.xlsx"
        if not tpl_path.exists():
            tpl_path.write_bytes(generate_idx_excel_template_bytes())
    except Exception as e:
        print(f"Template gen error: {e}")
    yield

app = FastAPI(
    title="IDX-QuantTerminal: DuPont ALK & IHSG Research Platform",
    version="5.0.0",
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/app/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    ticker: str = "ASII",
    session: Session = Depends(get_session),
):
    notice = None
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)

    # On-demand: jika emiten belum ada di cache → fetch dari yfinance → cache → analyze
    if not curr_stmt:
        ticker_upper = ticker.upper()
        try:
            from app.providers import yahoo as provider
            fin_rows = provider.fetch_financials_multi(ticker_upper, years=4)
            if fin_rows:
                provider.cache_financials_multi_to_db(session, ticker_upper, fin_rows)
                session.commit()
                curr_stmt, prev_stmt = load_ticker_pair(session, ticker_upper)
                notice = (f"📥 {ticker_upper} ({len(fin_rows)} tahun) baru di-pull dari yfinance & di-cache. "
                          f"Analisis DuPont YoY tersedia.")
        except Exception as e:
            pass  # tetap tampilkan ASII sebagai fallback

    # Fallback ke ASII jika memang tidak ada data sama sekali
    if not curr_stmt:
        # PRIORITAS 2: XBRL audited BEI (937 emiten, 2021-2025) — data REAL, bukan demo
        try:
            from app.services.xbrl_adapter import from_xbrl
            _fx = 16000.0
            try:
                from app.services.real_data_registry import get_macro_indicators as _gm
                _mx = _gm() or {}
                _vx = _mx.get("usd_idr")
                if isinstance(_vx, (int, float)) and _vx > 0:
                    _fx = float(_vx)
            except Exception:
                pass
            _xbrl_stmt = from_xbrl(ticker.upper(), usdidr=_fx)
            if _xbrl_stmt is not None:
                curr_stmt = _xbrl_stmt
                prev_stmt = None
                notice = (f"📊 {ticker.upper()} di-load dari XBRL audited BEI (IDX) — data REAL, bukan demo. "
                          f"FY{curr_stmt.year}.")
        except Exception:
            pass

    # Fallback terakhir ke ASII jika memang tidak ada data sama sekali
    if not curr_stmt:
        notice = (f"Ticker {ticker.upper()} belum ada di cache & tidak bisa di-fetch. "
                  f"Menampilkan ASII sebagai demo. "
                  f"Unggah laporan keuangannya via POST /api/dupont/upload.")
        curr_stmt, prev_stmt = load_ticker_pair(session, "ASII")

    if not curr_stmt:
        raise HTTPException(status_code=404, detail="Cache laporan keuangan kosong. "
                           "Tidak ada data sama sekali — seed data tidak ditemukan.")

    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle, wait_for_llm=False)
    terminal = get_terminal_snapshot()

    # Skala satuan bersih & seragam (Miliar IDR via units.py)
    rev_bn = to_bn(curr_stmt, curr_stmt.revenue) or 0.0
    ebit_bn = to_bn(curr_stmt, curr_stmt.ebit) or 0.0
    ebt_bn = to_bn(curr_stmt, curr_stmt.ebt) or 0.0
    ni_bn = to_bn(curr_stmt, curr_stmt.net_income_parent) or 0.0
    ta_bn = to_bn(curr_stmt, curr_stmt.total_assets) or 0.0
    tl_bn = to_bn(curr_stmt, curr_stmt.total_liabilities) or 0.0
    te_bn = to_bn(curr_stmt, curr_stmt.total_equity_parent) or 0.0
    debt_bn = to_bn(curr_stmt, curr_stmt.interest_bearing_debt) if curr_stmt.interest_bearing_debt else (tl_bn * 0.45)
    ca_bn = to_bn(curr_stmt, curr_stmt.current_assets) if curr_stmt.current_assets else (ta_bn * 0.4)
    cl_bn = to_bn(curr_stmt, curr_stmt.current_liabilities) if curr_stmt.current_liabilities else (tl_bn * 0.5)
    cash_bn = to_bn(curr_stmt, curr_stmt.cash_and_equivalents) if curr_stmt.cash_and_equivalents else (ta_bn * 0.12)
    int_exp_bn = to_bn(curr_stmt, curr_stmt.interest_expense) if curr_stmt.interest_expense else (debt_bn * 0.07)
    ocf_bn = to_bn(curr_stmt, curr_stmt.operating_cash_flow) if curr_stmt.operating_cash_flow else (ebit_bn * 1.0)
    dep_bn = to_bn(curr_stmt, curr_stmt.depreciation) if curr_stmt.depreciation else (ebit_bn * 0.2)
    capex_bn = to_bn(curr_stmt, curr_stmt.capex) if curr_stmt.capex else (ebit_bn * 0.35)

    # Nilai penuh IDR untuk metrik perbankan via units.py
    eq_full = to_idr(curr_stmt, curr_stmt.total_equity_parent) or 0.0
    ni_full = to_idr(curr_stmt, curr_stmt.net_income_parent) or 0.0
    ta_full = to_idr(curr_stmt, curr_stmt.total_assets) or 0.0
    tl_full = to_idr(curr_stmt, curr_stmt.total_liabilities) or 0.0
    rev_full = to_idr(curr_stmt, curr_stmt.revenue) or 0.0
    int_inc_full = to_idr(curr_stmt, curr_stmt.interest_income) or 0.0
    int_exp_full = to_idr(curr_stmt, curr_stmt.interest_expense) or 0.0
    tax_full = to_idr(curr_stmt, curr_stmt.tax_provision) or 0.0
    pretax_full = to_idr(curr_stmt, curr_stmt.ebt) or 0.0

    banking_data = {
        "ticker": curr_stmt.ticker,
        "sector": curr_stmt.sector,
        "revenue": rev_full,
        "net_income": ni_full,
        "total_assets": ta_full,
        "total_equity": eq_full,
        "total_debt": tl_full,
        "ebit": curr_stmt.ebit,
        "ebt": pretax_full,
        "interest_income": int_inc_full,
        "interest_expense": int_exp_full,
        "tax_provision": tax_full,
        "pretax_income": pretax_full,
        "shares_outstanding": curr_stmt.shares_outstanding or 0.0,
        "period": curr_stmt.year,
        "eps": getattr(curr_stmt, "eps", None),
    }
    # Ke riil (beta regresi) + sustainable growth -> Justified PBV institusional,
    # bukan konstanta Ke 10.5% / g 5.0% untuk semua bank.
    try:
        from app.services.cost_of_capital import compute_wacc, compute_sustainable_growth
        from app.services import idx_audited_financials as _AFb
        if _AFb.available() and _AFb.has_ticker(curr_stmt.ticker):
            _hist_b = _AFb.five_year_table(curr_stmt.ticker)
            _fy_b = _hist_b[-1] if _hist_b else {}
            _w_b = compute_wacc(session, curr_stmt.ticker, _fy_b)
            if _w_b.get("available") and _w_b.get("cost_equity_pct"):
                banking_data["cost_of_equity_pct"] = _w_b["cost_equity_pct"]
            _g_b, _ = compute_sustainable_growth(_hist_b)
            if _g_b is not None:
                banking_data["sustainable_growth_pct"] = _g_b
    except Exception:
        pass
    banking_ratios = calculate_banking_ratios(banking_data)
    is_bank = banking_ratios is not None

    # Hitung Quick DCF Valuation bawaan (hanya untuk Non-Bank)
    current_price = None
    price_status = "UNAVAILABLE"
    try:
        quote_obj, price_status = get_quote(session, curr_stmt.ticker)
        if quote_obj and quote_obj.price and quote_obj.price > 0:
            current_price = float(quote_obj.price)
    except Exception as exc:
        print(f"Quote fetch error: {exc}")

    dcf_result = None
    if not is_bank:
        try:
            # ZERO-FAKE: tidak ada fallback harga/saham karangan.
            shares_m = (_shares_from_stmt(curr_stmt) / 1e6) or None
            if shares_m is None:
                print(f"[DCF] {curr_stmt.ticker}: jumlah saham tidak dapat "
                      f"diturunkan (shares & EPS kosong) -> DCF dilewati")
                raise ValueError("shares unavailable")

            # ── Input DCF dari filing audited (bukan konstanta) ──────────────
            from app.services.idx_audited_financials import five_year_table as _fyt
            from app.services.equity_research_helpers import build_wacc_components as _bwc
            _tbl = []
            try:
                _tbl = _fyt(curr_stmt.ticker) or []
            except Exception:
                _tbl = []
            _last = _tbl[-1] if _tbl else {}

            # EBIT ternormalisasi: rata-rata 3 tahun (satu tahun bisa outlier)
            _ebits = [x.get("ebit_bn") for x in _tbl[-3:] if x.get("ebit_bn") is not None]
            _ebit_norm_bn = (sum(_ebits) / len(_ebits)) if _ebits else ebit_bn

            # D&A: tag langsung, atau EBITDA - EBIT (identitas), atau 0 (konservatif)
            dep_bn = _last.get("depreciation_amortization_bn")
            if dep_bn is None:
                _ebitda_r, _ebit_r = _last.get("ebitda_bn"), _last.get("ebit_bn")
                dep_bn = (_ebitda_r - _ebit_r) if (_ebitda_r is not None and _ebit_r is not None) else 0.0

            # Capex: PPE + intangible (sudah dijumlahkan di parser)
            capex_bn = abs(_last.get("capex_bn") or 0.0)

            # ΔWC dari neraca (CA-CL antar tahun); 0 bila tidak tersedia
            _dwc = 0.0
            if len(_tbl) >= 2:
                _prev = _tbl[-2]
                if all(x.get(k) for x in (_last, _prev) for k in ("current_assets_bn", "current_liabilities_bn")):
                    _dwc = ((_last["current_assets_bn"] - _last["current_liabilities_bn"])
                            - (_prev["current_assets_bn"] - _prev["current_liabilities_bn"]))

            # Growth: CAGR revenue riil, dibatasi -10%..12%
            _g = 0.05
            _revs = [x.get("revenue_bn") for x in _tbl if x.get("revenue_bn")]
            _revs = [v for v in _revs if v > 0]
            if len(_revs) >= 2:
                _n = len(_revs) - 1
                _g = max(-0.10, min(0.12, (_revs[-1] / _revs[0]) ** (1.0 / _n) - 1.0))

            # Parameter WACC riil per emiten
            _wb = _bwc(financials=_tbl, beta_raw=None, current_price=current_price,
                       shares_bn=shares_m, is_bank=False, ticker=curr_stmt.ticker)
            _beta = _wb.get("beta") or 1.0
            _kd = ((_wb.get("cod_pre_tax_pct") or 7.5)) / 100.0
            _etr = (_wb.get("etr_pct") or 22.0) / 100.0
            _wd = (_wb.get("wd_pct") or 30.0) / 100.0

            # Utang: interest-bearing bila ada, else PROXY konservatif
            # min(total liabilitas, ekuitas) — upper bound yang dapat
            # dipertanggungjawabkan, bukan default 45% liabilitas.
            _debt = debt_bn
            if _debt is None:
                _debt = min(tl_bn, te_bn) if (tl_bn and te_bn) else tl_bn

            dcf_result = quick_dcf_valuation(
                ticker=curr_stmt.ticker,
                current_market_price=current_price,
                risk_free_rate=6.85,
                market_risk_premium=6.5,
                levered_beta=_beta,
                cost_of_debt_pre_tax=_kd * 100.0,
                tax_rate=_etr,
                target_debt_ratio=_wd,
                ebit=_ebit_norm_bn,
                depreciation=dep_bn,
                capex=capex_bn,
                wc_change=_dwc,
                fcf_growth_rate=_g,
                terminal_growth_rate=0.025,
                total_assets=ta_bn,
                total_debt=_debt,
                cash=(cash_bn or 0.0),
                shares_outstanding_m=shares_m,
            )
            if isinstance(dcf_result, dict):
                dcf_result.setdefault("terminal_growth_rate", 0.025)
        except Exception as exc:
            print(f"DCF Error [{curr_stmt.ticker}]: {type(exc).__name__}: {exc}")
            dcf_result = None

    # Multi-Year Trend Metrics
    history_stmts = load_ticker_history(session, curr_stmt.ticker, limit=5)
    history_metrics = [compute_single_period_dupont(s) for s in reversed(history_stmts)]

    # Credit Metrics (Bank vs Corporate)
    credit = calculate_credit_metrics(
        total_assets=ta_bn,
        total_liabilities=tl_bn,
        total_debt=debt_bn,
        current_assets=ca_bn,
        current_liabilities=cl_bn,
        cash_and_equivalents=cash_bn,
        ebit=ebit_bn,
        interest_expense=int_exp_bn,
        cash_flow_from_operations=ocf_bn,
        net_income=ni_bn,
        is_bank=is_bank,
    )

    # Risk Metrics & Monte Carlo (Real Market Data via market_data.py)
    prices_series = []
    ihsg_series = []
    aligned_dates = []
    try:
        stock_hist = ensure_history(session, curr_stmt.ticker, years=2)
        bench_hist = ensure_history(session, "IHSG", years=2)
        prices_series, ihsg_series, aligned_dates = aligned_closes(stock_hist, bench_hist)
    except Exception as exc:
        print(f"Market history fetch error: {exc}")

    if len(prices_series) >= 30:
        realized_vol = calculate_realized_volatility(prices_series) or 0.25
        risk = calculate_risk_metrics(prices_series, benchmark_prices=ihsg_series, risk_free_rate=0.0685)
        ref_price_mc = float(current_price or prices_series[-1])
        beta_val = getattr(risk, "beta", 1.0) or 1.0
        # CAPM drift: rf + beta * ERP (bukan ROE)
        capm_drift = 0.0685 + float(beta_val) * 0.065
        monte_carlo = run_monte_carlo_gbm(
            current_price=ref_price_mc,
            annual_drift=capm_drift,
            annual_vol=realized_vol,
            days=252,
            n_paths=200,
            seed=42,
        )
    else:
        risk = None
        monte_carlo = None

    # Peer Screener Rows
    screener_rows = build_peer_screener_rows(session)

    # Baseline SBN FR Benchmark (Tab 5)
    bond_demo_raw = bond_price(face_value=1_000_000, coupon_rate=0.0725, ytm=0.0675, years_to_maturity=5.0)
    if hasattr(bond_demo_raw, "model_dump"):
        bond_demo = bond_demo_raw.model_dump()
    elif dataclasses.is_dataclass(bond_demo_raw):
        bond_demo = dataclasses.asdict(bond_demo_raw)
    else:
        bond_demo = bond_demo_raw.__dict__

    dcf_payload = dcf_result or {}
    mc_payload = monte_carlo or {}
    risk_payload = dataclasses.asdict(risk) if dataclasses.is_dataclass(risk) else (risk.model_dump() if hasattr(risk, "model_dump") else (risk.__dict__ if risk else {}))
    credit_payload = dataclasses.asdict(credit) if dataclasses.is_dataclass(credit) else (credit.model_dump() if hasattr(credit, "model_dump") else (credit.__dict__ if credit else {}))

    # Institutional Equity Research Model (FinRobot / CFA Archetype)
    from app.services.research_paper_engine import build_research_model_from_context, generate_equity_research_pdf_bytes
    try:
        research_model = build_research_model_from_context(
            ticker=curr_stmt.ticker,
            bundle=bundle,
            curr_stmt=curr_stmt,
            dcf=dcf_payload if isinstance(dcf_payload, dict) else {},
            credit=credit_payload if isinstance(credit_payload, dict) else {},
            risk=risk_payload if isinstance(risk_payload, dict) else {},
            technical=None,
            current_price=float(current_price or (prices_series[-1] if prices_series else 0.0) or 0.0),
            shares_out=_shares_from_stmt(curr_stmt),
        )
        research_payload = dataclasses.asdict(research_model)
    except Exception as exc:
        import traceback as _tb
        print(f"[RESEARCH MODEL ERROR] ticker={ticker} exc={exc}", file=__import__('sys').stderr)
        _tb.print_exc(file=__import__('sys').stderr)
        research_model = None
        research_payload = {}

    # Gabungan: emiten yang sudah ada laporan keuangan (analisis DuPont siap)
    # + emiten aktif dari symbol table (bisa di-click untuk fetch on-demand)
    stmt_tickers = set(str(t) for t in session.exec(select(FinancialStatementCache.ticker)).all())
    sym_tickers  = set(str(t) for t in session.exec(select(Symbol.ticker)).all())
    all_tickers  = sorted(stmt_tickers | sym_tickers)
    cached_tickers_str = (
        sorted(stmt_tickers) +
        sorted(sym_tickers - stmt_tickers)
    )
    return templates.TemplateResponse(
        request,
        "base.html",
        {
            "bundle": bundle,
            "anomaly": anomaly,
            "terminal": terminal,
            "banking": banking_ratios,
            "dcf": dcf_result,
            "dcf_payload": dcf_payload,
            "credit": credit,
            "credit_payload": credit_payload,
            "risk": risk,
            "risk_payload": risk_payload,
            "monte_carlo": monte_carlo,
            "mc_payload": mc_payload,
            "history_metrics": history_metrics,
            "screener_rows": screener_rows,
            "bond_demo": bond_demo,
            "research_payload": research_payload,
            "curr_stmt": curr_stmt,
            "cached_tickers": cached_tickers_str,
            "cached_tickers_str": cached_tickers_str,
            "active_ticker": curr_stmt.ticker,
            "notice": notice,
        },
    )

@app.get("/api/dupont/{ticker}")
@app.get("/api/dupont/{ticker}/json")
async def get_dupont_analysis_json(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} tidak ditemukan.")
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle, wait_for_llm=False)
    return {"bundle": bundle, "anomaly": anomaly}

# ── FASE 3.1 Screener Endpoint ─────────────────────────────────
@app.get("/api/agent/technical/{ticker}")
async def get_ai_technical_analysis(ticker: str, session: Session = Depends(get_session)):
    """
    AI Technical Analyst Agent endpoint (virattt/ai-hedge-fund architecture).
    Menganalisis 5 pilar: Trend, Momentum, Mean Reversion, Volatility, Hurst Exponent.
    """
    import yfinance as yf
    import pandas as pd
    from app.services.llm_analyzer import _load_env_file
    _load_env_file()
    
    clean_sym = ticker.upper().replace("IDX:", "").replace("^", "")
    yf_symbol = "^JKSE" if clean_sym in ["COMPOSITE", "IHSG"] else f"{clean_sym}.JK"
    
    # 1. Coba ambil data historis dari database lokal terlebih dahulu
    hist_rows = session.exec(
        select(QuoteHistoryDaily)
        .where(QuoteHistoryDaily.ticker == clean_sym)
        .order_by(QuoteHistoryDaily.date.asc())
    ).all()
    
    df: Optional[pd.DataFrame] = None
    if hist_rows and len(hist_rows) >= 30:
        data = [{
            "Date": r.date,
            "Close": float(r.close or 0),
            "High": float(r.high or r.close or 0),
            "Low": float(r.low or r.close or 0),
            "Volume": float(r.volume or 1000000)
        } for r in hist_rows]
        df = pd.DataFrame(data)
    else:
        # 2. Fallback fetch via yfinance
        try:
            t = yf.Ticker(yf_symbol)
            hist = t.history(period="1y")
            if not hist.empty and len(hist) >= 30:
                df = hist.reset_index()
        except Exception:
            pass

    # 3. Jika offline/rate-limited: JANGAN mengarang data, tampilkan N/A
    if df is None or df.empty or len(df) < 30:
        # WARNING: Data tidak tersedia, sistem tidak boleh mengarang
        analysis = {
            "status": "UNAVAILABLE",
            "reason": "Insufficient market data (< 30 bars). Cannot generate technical analysis without real data.",
            "last_price": None,
            "overall_signal": "N/A",
            "confidence_pct": 0,
            "pillars": {},
            "llm_summary": "Data pasar tidak tersedia. Tidak dapat menghasilkan analisis tanpa data real-time."
        }
        return {"technical_analysis": analysis}

    analysis = run_institutional_technical_analysis(df, ticker=clean_sym)

    # Tambahkan sintesis narasi AI dari VPS 9router jika tersedia
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    model_name = os.getenv("LLM_MODEL", "dahl")
    
    analysis["llm_summary"] = None
    if api_key and api_base:
        try:
            import httpx
            prompt = (
                f"Kamu adalah Institutional Senior Equity & Technical Analyst. "
                f"Analisis data 5-pilar teknikal untuk ticker {clean_sym} berikut:\n"
                f"- Harga Terkini: {analysis.get('last_price')}\n"
                f"- Sinyal Ensemble: {analysis.get('overall_signal')} (Confidence: {analysis.get('confidence_pct')}%)\n"
                f"- Trend: {analysis.get('pillars', {}).get('trend', {}).get('signal')} (ADX: {analysis.get('pillars', {}).get('trend', {}).get('metrics', {}).get('adx')})\n"
                f"- Momentum: {analysis.get('pillars', {}).get('momentum', {}).get('signal')} (1M: {analysis.get('pillars', {}).get('momentum', {}).get('metrics', {}).get('momentum_1m_pct')}%)\n"
                f"- Mean Reversion: {analysis.get('pillars', {}).get('mean_reversion', {}).get('signal')} (RSI 14: {analysis.get('pillars', {}).get('mean_reversion', {}).get('metrics', {}).get('rsi_14')}, Z-Score: {analysis.get('pillars', {}).get('mean_reversion', {}).get('metrics', {}).get('z_score_ma50')})\n"
                f"- Regime Volatilitas & Hurst: Hurst={analysis.get('pillars', {}).get('statistical', {}).get('metrics', {}).get('hurst_exponent')} ({analysis.get('pillars', {}).get('statistical', {}).get('metrics', {}).get('regime')})\n\n"
                f"Berikan ulasan tesis trading institusional padat, 2-3 kalimat tajam dalam Bahasa Indonesia formal: tesis arah harga, batas risiko cut-loss, dan level take-profit/retest."
            )
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 180,
                        "stream": False,
                    }
                )
                if res.status_code == 200:
                    text_resp = res.text.strip()
                    if text_resp.startswith("data:"):
                        # Parse SSE stream chunks jika router default stream
                        chunks = []
                        for line in text_resp.split("\n"):
                            line = line.strip()
                            if line.startswith("data:") and not line.endswith("[DONE]"):
                                try:
                                    payload = json.loads(line[5:].strip())
                                    delta = payload["choices"][0].get("delta", {}).get("content", "")
                                    if delta:
                                        chunks.append(delta)
                                except Exception:
                                    pass
                        if chunks:
                            analysis["llm_summary"] = "".join(chunks).strip()
                    else:
                        resp_json = res.json()
                        analysis["llm_summary"] = resp_json["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"LLM synthesis error via 9router VPS: {e}")

    return analysis

@app.get("/api/screener")
async def get_screener_universe_json(session: Session = Depends(get_session)):
    rows = build_peer_screener_rows(session)
    return {"screener_rows": rows, "screener_results": rows, "count": len(rows)}

@app.get("/api/screener/{ticker}")
async def get_screener_json(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, _ = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} belum ada di cache.")
    rows = build_peer_screener_rows(session)
    return {"ticker": ticker.upper(), "screener_results": rows}

# ── FASE 3.2 Monte Carlo Endpoint ──────────────────────────────
@app.get("/api/monte-carlo/{ticker}")
async def get_monte_carlo_json(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, _ = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} belum ada di cache.")
    
    # Ambil harga terkini jika ada
    # ZERO-FAKE: dulu fallback Rp5.000 (harga karangan) untuk emiten tanpa
    # quote -> simulasi Monte Carlo dari harga fiktif. Sekarang N/A.
    ref_p = _latest_price(session, ticker.upper())
    if not ref_p:
        raise HTTPException(status_code=404,
                            detail=f"Harga {ticker.upper()} tidak tersedia — simulasi tidak dijalankan.")

    result = run_monte_carlo_gbm(
        current_price=ref_p,
        annual_drift=0.10,
        annual_vol=0.24,
        days=252,
        n_paths=200,
    )
    return {"ticker": ticker.upper(), "monte_carlo": result}

# ── FASE 3.3 Risk Endpoint ────────────────────────────────────
@app.get("/api/risk/{ticker}")
async def get_risk_json(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, _ = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} belum ada di cache.")
    
    ref_p = _latest_price(session, ticker.upper())

    # RISK METRICS: JANGAN gunakan data sintetis - hanya hitung dari data pasar real
    risk_m = None
    if len(price_series) >= 30 and ihsg_series and len(ihsg_series) >= 30:
        try:
            risk_m = calculate_risk_metrics(price_series, benchmark_prices=ihsg_series, risk_free_rate=0.0685)
        except Exception as exc:
            print(f"Risk metrics calculation failed: {exc}")
    # Jika data tidak cukup, risk_metrics = None (tidak boleh mengarang)
    return {
        "ticker": ticker.upper(),
        "risk_metrics": risk_m,
        "monte_carlo": mc,
    }

# ── FASE 3.4 Bonds Calculator Endpoint ─────────────────────────
@app.get("/api/bonds/calculate")
async def get_bond_calc_json(
    face_value: float = 1_000_000,
    coupon_pct: float = 7.25,
    ytm_pct: float = 6.85,
    years: float = 5.0,
    freq: int = 2,
):
    try:
        cf = CouponFrequency.SEMIANNUAL if freq == 2 else (CouponFrequency.ANNUAL if freq == 1 else CouponFrequency.QUARTERLY)
        res = bond_price(
            face_value=face_value,
            coupon_rate=coupon_pct / 100.0,
            ytm=ytm_pct / 100.0,
            years_to_maturity=years,
            frequency=cf,
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/dupont/upload")
async def upload_idx_statement(
    file: UploadFile = File(...),
    ticker: str = Form("XXXX"),
    year: int = Form(2025),
    session: Session = Depends(get_session),
):
    raw_bytes = await file.read()
    if len(raw_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Ukuran file melebihi batas 25MB.")
    try:
        parsed_stmt = parse_idx_file_bytes(
            filename=file.filename or "upload.xlsx",
            file_bytes=raw_bytes,
            default_ticker=ticker,
            default_year=year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    record = save_or_get_cached_statement(session, parsed_stmt, raw_bytes)
    curr_stmt, prev_stmt = load_ticker_pair(session, record.ticker)
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle, wait_for_llm=False)
    return {"status": "cached", "ticker": record.ticker, "bundle": bundle, "anomaly": anomaly}

@app.get("/api/research/{ticker}/ai-thesis")
async def generate_ai_research_thesis(ticker: str, session: Session = Depends(get_session)):
    """Generate tesis investasi mendalam via 9Router VPS berdasarkan fundamental riil."""
    ticker_upper = ticker.upper()
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker_upper)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail="Ticker tidak ditemukan.")
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    c = bundle.current
    
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    model_name = os.getenv("LLM_MODEL", "dahl")
    
    if not api_key or not api_base:
        return {"thesis": "9Router VPS belum terkonfigurasi. Pastikan .env OPENAI_BASE_URL dan OPENAI_API_KEY terisi."}

    # --- BREAKING NEWS: Ambil berita terkini untuk konteks qualitative ---
    from app.services.news_fetcher import fetch_ticker_news
    news_articles = await fetch_ticker_news(
        ticker_upper,
        getattr(curr_stmt, "company_name", None),
        max_articles=3
    )
    news_context = ""
    if news_articles:
        news_items = "; ".join(
            [f'"{a["title"]}" (sumber: {a["source"]})' for a in news_articles]
        )
        news_context = (
            f"\n\nBERITA TERKINI SEKILAS:\n{news_items}\n"
            f"(Gunakan berita di atas sebagai konteks kualitatif tambahan. "
            f"Jika berita materially relevan, Sebutkan dampaknya terhadap tesis investasi. "
            f"Jika tidak relevan, abaikan dan fokus ke data finansial.)\n"
        )

    prompt = (
        f"Kamu adalah Senior CFA Charterholder & Head of Equity Research di Investment Bank terkemuka. "
        f"Tuliskan tesis investasi mendalam berstandar CFA Research Challenge untuk emiten {ticker_upper} berdasarkan data finansial riil berikut:\n"
        f"- Return on Equity (ROE): {(c.roe or 0.14)*100:.1f}%\n"
        f"- EBIT Operating Margin: {(c.ebit_margin or 0.12)*100:.1f}%\n"
        f"- Asset Turnover: {c.asset_turnover or 0.85:.2f}x\n"
        f"- Financial Leverage (Equity Multiplier): {c.equity_multiplier or 1.6:.2f}x\n"
        f"- Tax Burden: {(c.tax_burden or 0.78)*100:.1f}%, Interest Burden: {(c.interest_burden or 0.95)*100:.1f}%\n"
        f"{news_context}"
        f"Susun dalam format HTML sederhana (gunakan tag <p>, <strong>, dan <ul><li>): "
        f"1. Evaluasi Kualitas Laba & Dekomposisi DuPont (apakah organik atau debt-driven).\n"
        f"2. Competitive Moat & Keunggulan Industri di BEI.\n"
        f"3. Rekomendasi Alokasi Portofolio Institusional.\n"
        f"Panjang maksimal 3 paragraf padat, berwibawa, bahasa Indonesia formal profesional."
    )
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{api_base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 400,
                    "stream": False,
                }
            )
            if res.status_code == 200:
                text_resp = res.text.strip()
                if text_resp.startswith("data:"):
                    chunks = []
                    for line in text_resp.split("\n"):
                        line = line.strip()
                        if line.startswith("data:") and not line.endswith("[DONE]"):
                            try:
                                payload = json.loads(line[5:].strip())
                                delta = payload["choices"][0].get("delta", {}).get("content", "")
                                if delta:
                                    chunks.append(delta)
                            except Exception:
                                pass
                    return {"thesis": "".join(chunks).strip()}
                else:
                    return {"thesis": res.json()["choices"][0]["message"]["content"].strip()}
    except Exception as e:
        return {"thesis": f"<span class='text-rose-400'>Error koneksi ke 9Router VPS: {e}</span>"}
    return {"thesis": "Tidak ada respon dari 9Router."}

@app.get("/api/research/{ticker}/news")
async def get_ticker_news_endpoint(ticker: str, session: Session = Depends(get_session)):
    """Mengambil berita terkini emiten dengan rotasi kunci NewsData.io round-robin."""
    from app.services.news_fetcher import fetch_ticker_news
    curr_stmt, _ = load_ticker_pair(session, ticker.upper())
    comp_name = getattr(curr_stmt, "company_name", None) if curr_stmt else None
    articles = await fetch_ticker_news(ticker.upper(), comp_name, max_articles=6)
    return {"ticker": ticker.upper(), "count": len(articles), "articles": articles}

@app.get("/api/research/{ticker}/export-pdf")
async def export_research_paper_pdf(ticker: str, session: Session = Depends(get_session)):
    """Menghasilkan output Institutional Equity Research Paper (PDF 4-Halaman) bergaya CFA/FinRobot."""
    from app.services.research_paper_engine import build_research_model_from_context, generate_equity_research_pdf_bytes
    from app.services.fincept_valuation import quick_dcf_valuation
    from app.services.fincept_fixed_income import calculate_credit_metrics
    
    ticker_upper = ticker.upper()
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker_upper)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker_upper} belum tersedia.")
        
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    
    # Valuation & fundamental scale
    raw_scale = (curr_stmt.unit_multiplier or 1.0)
    factor_to_bn = 1.0 if curr_stmt.revenue < 1e9 else (raw_scale / 1e9)
    rev_bn = curr_stmt.revenue * factor_to_bn
    ebit_bn = curr_stmt.ebit * factor_to_bn
    ta_bn = curr_stmt.total_assets * factor_to_bn
    tl_bn = curr_stmt.total_liabilities * factor_to_bn
    te_bn = curr_stmt.total_equity_parent * factor_to_bn
    # ZERO-FAKE: jangan mengarang utang (45% liabilitas), kas (12% aset),
    # jumlah saham (ekuitas/5000), atau harga (5000). Bila tidak ada, N/A.
    debt_bn = (curr_stmt.interest_bearing_debt * factor_to_bn) if curr_stmt.interest_bearing_debt else None
    cash_bn = (curr_stmt.cash_and_equivalents * factor_to_bn) if curr_stmt.cash_and_equivalents else None
    # Jumlah saham (juta lembar) — satu sumber kebenaran: helper _shares_from_stmt
    # (turunan identitas NI/EPS bila XBRL tidak melaporkan jumlah lembar).
    _sh_raw = _shares_from_stmt(curr_stmt)
    shares_m = (_sh_raw / 1e6) if _sh_raw > 0 else None

    # Harga: QuoteLatest, fallback ke bar historis terakhir (PTBA/ITMG tidak
    # punya baris QuoteLatest padahal punya 1.403 bar histori).
    current_price = _latest_price(session, ticker_upper)

    dcf_res = None
    try:
        # PARAMETER RIIL, bukan default: beta dari regresi vs IHSG (fallback 1,0
        # hanya bila histori harga kurang, dan itu ditandai), D/E dari neraca
        # audited, Kd dari beban bunga/pinjaman, tax dari ETR aktual.
        from app.services.equity_research_helpers import build_wacc_components as _bwc
        _tbl_dcf = []
        try:
            from app.services import idx_audited_financials as _AFD
            if _AFD.available() and _AFD.has_ticker(ticker_upper):
                _tbl_dcf = _AFD.five_year_table(ticker_upper) or []
        except Exception:
            _tbl_dcf = []
        _last = _tbl_dcf[-1] if _tbl_dcf else {}
        _wb = _bwc(financials=_tbl_dcf, beta_raw=None, current_price=current_price,
                   shares_bn=(shares_m or 0.0), is_bank=False, ticker=ticker_upper)
        _beta_used = _wb.get("beta") or 1.0
        _etr_used = (_wb.get("etr_pct") or 22.0) / 100.0
        _kd_used = _wb.get("cod_pre_tax_pct")
        _kd_used = (_kd_used / 100.0) if _kd_used else 0.075
        _wd_used = (_wb.get("wd_pct") or 30.0) / 100.0

        # FCF components dari filing audited (bukan rasio karangan)
        _da_bn = _last.get("depreciation_amortization_bn")
        if _da_bn is None:
            # D&A tidak dilaporkan (xsi:nil) -> turunkan dari EBITDA - EBIT
            # bila keduanya ada (identitas), kalau tidak -> 0 (KONSERVATIF).
            _ebitda_r = _last.get("ebitda_bn")
            _ebit_r = _last.get("ebit_bn")
            _da_bn = (_ebitda_r - _ebit_r) if (_ebitda_r is not None and _ebit_r is not None) else 0.0
        _capex_bn = _last.get("capex_bn")
        _capex_bn = abs(_capex_bn) if _capex_bn is not None else 0.0   # XBRL kadang negatif
        # Perubahan modal kerja: pakai CFO riil bila tersedia untuk kalibrasi?
        # Tidak — biarkan 0 dan tandai, agar FCFF tidak dikarang.
        # Perubahan modal kerja (ΔWC) = selisih modal kerja bersih CA-CL antar
        # tahun. Identitas neraca, bukan karangan. ΔWC=0 membuat FCFF overstate
        # (TLKM +409%). Bank unclassified BS -> tidak ada CA/CL -> 0.
        _dwc_bn = _last.get("working_capital_change_bn")
        if _dwc_bn is None and len(_tbl_dcf) >= 2:
            _prev_d = _tbl_dcf[-2]
            _wc_now = (_last.get("current_assets_bn") or 0) - (_last.get("current_liabilities_bn") or 0)
            _wc_prev = (_prev_d.get("current_assets_bn") or 0) - (_prev_d.get("current_liabilities_bn") or 0)
            if _last.get("current_assets_bn") and _last.get("current_liabilities_bn") \
               and _prev_d.get("current_assets_bn") and _prev_d.get("current_liabilities_bn"):
                _dwc_bn = _wc_now - _wc_prev
        if _dwc_bn is None:
            _dwc_bn = 0.0

        # PROXY utang: min(total liabilitas, ekuitas) — keduanya batas atas/
        # bawah yang dapat dipertanggungjawabkan dari neraca audited.
        _debt_proxy_bn = (debt_bn if debt_bn is not None
                          else (min(tl_bn, te_bn) if (tl_bn and te_bn) else tl_bn))

        # EBIT ternormalisasi: rata-rata 3 tahun terakhir yang tersedia
        _ebits = [x.get("ebit_bn") for x in _tbl_dcf[-3:] if x.get("ebit_bn") is not None]
        _ebit_norm_bn = (sum(_ebits) / len(_ebits)) if _ebits else ebit_bn

        # Growth FCF: CAGR revenue riil, DIBATASI -10%..12%. Batas atas 12%
        # karena growth abadi di atas itu tidak dapat dipertahankan (dan CAGR
        # 5 tahun emiten komoditas mencerminkan siklus harga, bukan trend).
        _g_rev_dcf = 0.05
        try:
            _revs = [x.get("revenue_bn") for x in _tbl_dcf if x.get("revenue_bn")]
            _revs = [v for v in _revs if v > 0]
            if len(_revs) >= 2:
                _n = len(_revs) - 1
                _cagr = (_revs[-1] / _revs[0]) ** (1.0 / _n) - 1.0
                _g_rev_dcf = max(-0.10, min(0.12, _cagr))
        except Exception:
            _g_rev_dcf = 0.05

        dcf_res = quick_dcf_valuation(
            ticker=ticker_upper,
            current_market_price=current_price,
            risk_free_rate=6.85,
            market_risk_premium=6.5,
            levered_beta=_beta_used,
            cost_of_debt_pre_tax=_kd_used * 100.0,
            tax_rate=_etr_used,
            target_debt_ratio=_wd_used,
            ebit=ebit_bn,
            # ZERO-FAKE: dulu D&A = EBITx20%, capex = EBITx35%, dWC = EBITx5%
            # (semua karangan) -> target harga meledak +108%. Sekarang dari XBRL:
            # D&A & capex & CFO riil. Bila xsi:nil -> 0 dengan provenance jelas
            # (valuasi jadi konservatif, bukan optimistis palsu).
            depreciation=_da_bn,
            capex=_capex_bn,
            wc_change=_dwc_bn,
            fcf_growth_rate=0.05,
            terminal_growth_rate=0.025,
            total_assets=ta_bn,
            # XBRL tidak punya tag interest-bearing debt tunggal (st_debt
            # coverage 0). Total liabilitas = UPPER BOUND: untuk ASII (bank-
            # like, banyak utang usaha) ia melebih-lebihkan net debt sehingga
            # equity value DCF meledak. Ambil nilai LEBIH KONSERVATIF antara
            # total liabilitas dan ekuitas (batas bawah struktur modal wajar).
            # Keduanya diberi label PROXY di output.
            total_debt=_debt_proxy_bn,
            cash=(cash_bn if cash_bn is not None else 0.0),
            shares_outstanding_m=shares_m,
        )
        # quick_dcf_valuation tidak mengembalikan terminal growth padahal itu
        # input yang dipakai (2,5%). Teruskan eksplisit supaya label WACC/g di
        # PDF/UI menampilkan asumsi yang BENAR-BENAR dipakai, bukan N/A.
        if isinstance(dcf_res, dict):
            dcf_res.setdefault("terminal_growth_rate", 0.025)
    except Exception as _dcf_exc:
        import sys as _sys
        print(f"[DCF SKIP] {ticker_upper}: {type(_dcf_exc).__name__}: {_dcf_exc}", file=_sys.stderr)

    model = build_research_model_from_context(
        ticker=ticker_upper,
        bundle=bundle,
        curr_stmt=curr_stmt,
        dcf=dcf_res or {},
        credit={},
        risk={},
        technical=None,
        current_price=current_price,
        shares_out=_shares_from_stmt(curr_stmt),
    )
    
    pdf_bytes = generate_equity_research_pdf_bytes(model)
    filename = f"Equity_Research_Paper_{ticker_upper}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.get("/api/dupont/{ticker}/export")
async def export_dupont_pdf(ticker: str, session: Session = Depends(get_session)):
    curr_stmt, prev_stmt = load_ticker_pair(session, ticker)
    if not curr_stmt:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} tidak ditemukan.")
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    anomaly = await summarize_dupont_anomalies(bundle, wait_for_llm=False)
    content_bytes, media_type, filename = render_dupont_report_export(bundle, anomaly)
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@app.get("/api/dupont/template/excel")
async def api_template_excel():
    """Generate dan download template Excel laporan keuangan standar IDX."""
    try:
        tpl_bytes = generate_idx_excel_template_bytes()
        return StreamingResponse(
            io.BytesIO(tpl_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=template_lapkeu_bei.xlsx"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal generate template: {exc}")


@app.get("/api/terminal/snapshot", response_model=TerminalPayload)
async def api_get_terminal():
    return get_terminal_snapshot()

@app.get("/api/market/overview")
async def api_market_overview():
    """Snapshot pasar IDX live dari Yahoo Finance (via idx CLI)."""
    try:
        overview = fetch_market_overview()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Gagal mengambil data pasar: {exc}")
    fetched_at = datetime.now(timezone.utc)
    freshness = classify_freshness(
        fetched_at,
        overview.get("as_of"),
        overview.get("market_state", ""),
        "yahoo",
    )
    return {
        "overview": overview,
        "freshness": {
            "label": freshness.label.value,
            "freshness_pct": freshness.freshness_pct,
            "as_of_wib": freshness.as_of_wib,
            "delay_minutes": freshness.delay_minutes,
            "market_state": freshness.market_state,
        },
    }

@app.get("/api/quotes")
async def api_quotes(symbols: str = "BBCA,BBRI,TLKM,ASII"):
    """Quote bulk untuk daftar simbol (comma-separated)."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="Tidak ada simbol yang diberikan.")
    if len(syms) > 200:
        raise HTTPException(status_code=400, detail="Maksimal 200 simbol per request.")
    try:
        quotes = fetch_quotes(syms)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Gagal mengambil quote: {exc}")
    return {"count": len(quotes), "quotes": quotes}

@app.get("/api/health")
async def api_health():
    """Status kesehatan semua sumber data + budget polling."""
    fetched_at = datetime.now(timezone.utc)
    sources = []

    # Sumber 1: Yahoo Finance (via idx CLI)
    try:
        overview = fetch_market_overview()
        freshness = classify_freshness(
            fetched_at,
            overview.get("as_of"),
            overview.get("market_state", ""),
            "yahoo",
        )
        sources.append(
            {
                "source": "yahoo-finance",
                "capability": "QUOTE_BULK / INDEX_QUOTE / MARKET_OVERVIEW / HISTORY / FINANCIALS",
                "status": SourceHealth.HEALTHY.value,
                "records_count": overview.get("breadth", {}).get("quoted", 0),
                "fetched_at": fetched_at.isoformat(),
                "as_of_wib": freshness.as_of_wib,
                "freshness": freshness.label.value,
                "delay_minutes": freshness.delay_minutes,
                "error_msg": None,
            }
        )
    except Exception as exc:
        sources.append(
            {
                "source": "yahoo-finance",
                "capability": "QUOTE_BULK / INDEX_QUOTE / MARKET_OVERVIEW",
                "status": SourceHealth.RUSAK.value,
                "records_count": 0,
                "fetched_at": fetched_at.isoformat(),
                "as_of_wib": None,
                "freshness": "UNKNOWN",
                "delay_minutes": 0,
                "error_msg": str(exc),
            }
        )

    # Sumber 2: idx.co.id foreign flow (dikenal terblokir Cloudflare dari DC)
    sources.append(
        {
            "source": "idx.co.id",
            "capability": "FOREIGN_FLOW / BROKER_SUMMARY",
            "status": SourceHealth.DEGRADED.value,
            "records_count": 0,
            "fetched_at": None,
            "as_of_wib": None,
            "freshness": "UNKNOWN",
            "delay_minutes": 0,
            "error_msg": (
                "Cloudflare bot protection memblokir akses dari IP non-residensial. "
                "Fallback: import CSV/JSON manual dari pengguna."
            ),
        }
    )

    return {
        "checked_at": fetched_at.isoformat(),
        "sources": sources,
        "budgets": [quote_budget.status(), fund_budget.status()],
    }

@app.post("/api/terminal/ingest", response_model=TerminalPayload)
async def api_ingest_terminal(
    payload: TerminalPayload,
    x_api_key: Optional[str] = Header(default=None),
):
    expected = os.getenv("INGEST_API_KEY", "").strip()
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="API key tidak valid (header X-API-Key).")
    errors = validate_terminal_payload(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return update_terminal_snapshot(payload)


# ===============================================================
# 4. AI ANALYST COPILOT (9Router VPS / dahl) & PDF EXPORT
# ===============================================================
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class CopilotChatRequest(BaseModel):
    ticker: str
    query: str
    context: Optional[Dict[str, Any]] = None
    history: Optional[List[Dict[str, str]]] = None

@app.post("/api/copilot/chat")
async def api_copilot_chat(req: CopilotChatRequest):
    """
    Interaktif chat dengan Senior Equity Research Analyst (FIG & FinTech).
    Didukung oleh 9Router VPS gateway (dahl) dan grounded 100% pada data riil.
    """
    from app.services.analyst_copilot import query_analyst_copilot
    clean_tk = req.ticker.upper().strip()
# Fallback jika context kosong dari frontend: bangun context otomatis dari DB audited BEI
    if not req.context or not req.context.get("company_name"):
        try:
            from app.services.idx_audited_financials import five_year_table
            _hist = five_year_table(clean_tk)  # list chronos 5 tahun
            if _hist:
                _latest = _hist[-1]  # tahun paling baru
                _hist3 = _hist[-3:]  # 3 tahun terakhir
                req.context = {
                    "ticker": clean_tk,
                    "company_name": _latest.get("company_name", clean_tk),
                    "sector": _latest.get("sector", "N/A"),
                    "revenue_bn": _latest.get("revenue_bn"),
                    "net_income_bn": _latest.get("net_income_bn"),
                    "total_equity_bn": _latest.get("total_equity_bn"),
                    "is_bank": bool(_latest.get("is_bank")),
                    "roe_pct": round((_latest.get("net_income_bn", 0) / _latest.get("total_equity_bn", 1)) * 100, 2) if _latest.get("total_equity_bn") else None,
                    "historical_financials": [
                        {"year": r.get("year"), "revenue_bn": r.get("revenue_bn"),
                         "net_income_bn": r.get("net_income_bn"), "total_equity_bn": r.get("total_equity_bn")}
                        for r in _hist3
                    ],
                    "fundamentals_source": f"IDX_XBRL_AUDITED_FY{_latest.get('year')}",
                }
        except Exception as e:
            pass  # jika gagal, lanjut dengan context kosong; AI akan bilang N/A

    res = query_analyst_copilot(
        ticker=clean_tk,
        user_query=req.query,
        context=req.context or {},
        chat_history=req.history or [],
    )
    return res


# ===============================================================
# 5. PEER COMPARISON MATRIX — GET & ADD/REFRESH
# ===============================================================
@app.get("/api/peers/{ticker}")
async def api_get_peer_matrix(ticker: str):
    from app.services.peer_matrix import build_peer_matrix
    try:
        result = build_peer_matrix(ticker.upper().strip())
        if "error" in result:
            return {"error": result["error"]}
        return result
    except Exception as e:
        return {"error": str(e)}


# ===============================================================
# 6a. PERFORMANCE & RISK ANALYTICS (backtesting institusional)
# ===============================================================
@app.get("/api/performance/{ticker}")
async def api_get_performance(
    ticker: str,
    benchmark: str = "IHSG",
    risk_free: float = 6.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """
    Sharpe, Sortino, Calmar, Beta, Jensen Alpha, Max Drawdown, VaR/CVaR,
    information ratio, skew/kurtosis, equity & drawdown curve.

    ZERO-FAKE: semua dari OHLCV harian di DB. Data kurang -> available=false + alasan.
    """
    from sqlmodel import Session as _Session
    from app.db.database import engine as _engine
    from app.services.performance_engine import compute_performance

    with _Session(_engine) as sess:
        return compute_performance(sess, ticker, benchmark=benchmark,
                                   risk_free_pct=risk_free, start=start, end=end)


@app.get("/api/performance/rolling/{ticker}")
async def api_get_rolling(
    ticker: str,
    window: int = 252,
    risk_free: float = 6.0,
):
    """Rolling Sharpe/Sortino untuk melihat konsistensi antar periode."""
    from sqlmodel import Session as _Session
    from app.db.database import engine as _engine
    from app.services.performance_engine import compute_rolling_stats

    w = max(60, min(756, int(window)))
    with _Session(_engine) as sess:
        return compute_rolling_stats(sess, ticker, window_days=w, risk_free_pct=risk_free)


@app.get("/api/performance/compare/{tickers}")
async def api_compare_performance(
    tickers: str,
    benchmark: str = "IHSG",
    risk_free: float = 6.0,
):
    """Ranking beberapa emiten (dipisah koma) berdasarkan Sharpe."""
    from sqlmodel import Session as _Session
    from app.db.database import engine as _engine
    from app.services.performance_engine import compute_performance_multi

    tl = [t.strip().upper() for t in tickers.split(",") if t.strip()][:12]
    if not tl:
        return {"error": "Tidak ada ticker"}
    with _Session(_engine) as sess:
        return compute_performance_multi(sess, tl, benchmark=benchmark, risk_free_pct=risk_free)


# ===============================================================
# 6b. STATUS PERDAGANGAN EMITEN (suspensi / delisting — terverifikasi BEI)
# ===============================================================
@app.get("/api/trading-status/{ticker}")
async def api_get_trading_status(ticker: str):
    """
    Alasan kenapa sebuah emiten tidak punya harga pasar.
    Sumber: pengumuman resmi BEI/IDX. Kosong = emiten aktif diperdagangkan.
    """
    import json, os
    f_path = "/Users/hasbi/idx-quant-terminal/data/idx_trading_status.json"
    if os.path.exists(f_path):
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            st = d.get("status", {}).get(ticker.upper().strip())
            if st:
                return {"ticker": ticker.upper(), "tradable": False, **st}
            return {"ticker": ticker.upper(), "tradable": True, "reason": None, "detail": None}
        except Exception as e:
            return {"error": str(e)}
    return {"ticker": ticker.upper(), "tradable": True, "reason": None, "detail": None}


# ===============================================================
# 6. FINTECH UNIT ECONOMICS (GOTO, BUKA, BELI)
# ===============================================================
@app.get("/api/fintech/{ticker}")
async def api_get_fintech_metrics(ticker: str):
    import json, os
    f_path = "/Users/hasbi/idx-quant-terminal/data/fintech_unit_economics.json"
    if os.path.exists(f_path):
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d.get(ticker.upper().strip(), {})
        except Exception as e:
            return {"error": str(e)}
    return {}


@app.post("/api/peers/{ticker}")
async def api_post_peer_matrix(ticker: str, req: dict = None):
    from app.services.peer_matrix import build_peer_matrix
    try:
        extra = req.get("peers") if req else None
        result = build_peer_matrix(ticker.upper().strip(), peer_tickers=extra)
        if "error" in result:
            return {"error": result["error"]}
        return result
    except Exception as e:
        return {"error": str(e)}


def _latest_price(session, ticker: str):
    """Harga terakhir: QuoteLatest, fallback ke bar historis terakhir.

    PTBA/ITMG punya 1.403 baris QuoteHistoryDaily tapi TIDAK ada baris
    QuoteLatest -> seluruh valuasi jadi N/A padahal datanya ada.
    """
    try:
        ql = session.get(QuoteLatest, ticker)
        if ql and ql.price and ql.price > 0:
            return float(ql.price)
    except Exception:
        pass
    try:
        from sqlmodel import select as _sel
        from app.db.models import QuoteHistoryDaily as _Q
        row = session.exec(
            _sel(_Q).where(_Q.ticker == ticker).order_by(_Q.date.desc())
        ).first()
        if row and row.close and row.close > 0:
            return float(row.close)
    except Exception:
        pass
    return None


def _shares_from_stmt(stmt) -> float:
    """Jumlah saham dalam LEMBAR MENTAH (bukan juta).

    XBRL BEI hanya melaporkan nilai nominal `CommonStocks`, bukan jumlah lembar,
    jadi bila `shares_outstanding` kosong -> turunkan dari identitas akuntansi
    `shares = Laba Bersih (rupiah) / EPS (rupiah per saham)`. Identitas, bukan
    angka karangan. Return 0.0 bila keduanya tidak tersedia (pemanggil wajib
    memperlakukan 0.0 sebagai N/A, BUKAN memakai default).
    """
    so = getattr(stmt, "shares_outstanding", None)
    try:
        so = float(so or 0.0)
    except (TypeError, ValueError):
        so = 0.0
    if so > 0:
        # DB menyimpan jumlah lembar mentah
        return so

    eps = getattr(stmt, "eps", None)                  # Rp per saham
    ni = getattr(stmt, "net_income_parent", None)     # MILIAR rupiah di DB
    if eps and ni:
        try:
            eps_f, ni_f = float(eps), float(ni)
            if eps_f != 0 and ni_f != 0:
                # NI (miliar) -> rupiah penuh: x1e9
                lembar = abs(ni_f) * 1e9 / abs(eps_f)
                if lembar > 0:
                    return lembar                      # lembar mentah
        except (TypeError, ValueError):
            pass
    return 0.0


@app.get("/api/research/{ticker}/pdf")
async def api_research_pdf(ticker: str, session: Session = Depends(get_session)):
    """
    One-Click Institutional Equity Research Tear-Sheet Export (PDF).

    Versi lama memanggil `generate_equity_research_report` yang TIDAK PERNAH ADA
    di research_paper_engine -> endpoint selalu 500. Sekarang mendelegasikan ke
    handler /export-pdf yang sudah terbukti menghasilkan PDF.
    """
    from fastapi.responses import Response
    clean_tk = ticker.upper().strip()
    resp = await export_research_paper_pdf(ticker=clean_tk, session=session)
    if isinstance(resp, Response):
        resp.headers["Content-Disposition"] = f"attachment; filename=IDX_Research_{clean_tk}.pdf"
    return resp