from fastapi.testclient import TestClient
from app.main import app
from app.services.dupont_engine import (
    FinancialStatementInput,
    PeriodType,
    PrimaryDriver,
    analyze_dupont_yoy,
)
from app.services.llm_analyzer import generate_deterministic_anomaly_summary
from app.services.terminal_pipeline import is_valid_idx_price, ForeignFlowItem

def test_dupont_3_and_5_stage_reconciliation():
    prev_stmt = FinancialStatementInput(
        ticker="ASII",
        company_name="Astra International Tbk",
        year=2024,
        period_type=PeriodType.FY,
        revenue=300_000,
        ebit=42_000,
        ebt=40_000,
        net_income_parent=32_000,
        total_assets=440_000,
        total_liabilities=240_000,
        total_equity_parent=200_000,
    )
    curr_stmt = FinancialStatementInput(
        ticker="ASII",
        company_name="Astra International Tbk",
        year=2025,
        period_type=PeriodType.FY,
        revenue=330_000,
        ebit=52_000,
        ebt=49_000,
        net_income_parent=39_200,
        total_assets=460_000,
        total_liabilities=250_000,
        total_equity_parent=210_000,
    )
    bundle = analyze_dupont_yoy(curr_stmt, prev_stmt)
    assert bundle.current.reconciliation_diff_3stage < 1e-6
    assert bundle.current.reconciliation_diff_5stage < 1e-6
    assert bundle.current.balance_sheet_balanced is True
    assert bundle.primary_driver == PrimaryDriver.OPERATIONAL_MARGIN

def test_negative_equity_guardrail_blocks_false_positive_roe():
    distressed = FinancialStatementInput(
        ticker="DIST",
        company_name="Emiten Distressed Tbk",
        year=2025,
        period_type=PeriodType.FY,
        revenue=50_000,
        ebit=-5_000,
        ebt=-12_000,
        net_income_parent=-15_000,
        total_assets=100_000,
        total_liabilities=130_000,
        total_equity_parent=-30_000,
    )
    bundle = analyze_dupont_yoy(distressed)
    assert bundle.current.is_negative_equity is True
    assert bundle.current.roe is None
    assert bundle.current.equity_multiplier is None
    summary = generate_deterministic_anomaly_summary(bundle)
    assert "Defisiensi Modal" in summary.headline

def test_interim_q2_annualization():
    q2_stmt = FinancialStatementInput(
        ticker="ICBP",
        company_name="Indofood CBP Tbk",
        year=2025,
        period_type=PeriodType.Q2,
        revenue=35_000,
        ebit=7_000,
        ebt=6_500,
        net_income_parent=5_000,
        total_assets=120_000,
        total_liabilities=60_000,
        total_equity_parent=60_000,
    )
    bundle = analyze_dupont_yoy(q2_stmt)
    assert bundle.current.annualized_applied is True
    assert abs(bundle.current.roe - (10_000 / 60_000)) < 1e-6

def test_idx_tick_size_and_foreign_flow():
    assert is_valid_idx_price(185) is True
    assert is_valid_idx_price(351) is False
    assert is_valid_idx_price(5250) is True
    assert is_valid_idx_price(5260) is False

    flow = ForeignFlowItem(
        ticker="ASII",
        net_foreign_rg_1d_bn=90.0,
        net_foreign_rg_5d_bn=250.0,
        net_foreign_ng_1d_bn=-500.0,
    )
    assert flow.flow_signal == "STRONG_ACCUMULATION"

def test_end_to_end_fastapi_routes():
    with TestClient(app) as client:
        res_home = client.get("/?ticker=ASII")
        assert res_home.status_code == 200
        assert "IDX-QuantTerminal" in res_home.text

        res_dupont = client.get("/api/dupont/ICBP")
        assert res_dupont.status_code == 200
        assert res_dupont.json()["bundle"]["current"]["ticker"] == "ICBP"

        res_term = client.get("/api/terminal/snapshot")
        assert res_term.status_code == 200
        assert len(res_term.json()["movers"]) >= 4

        res_export = client.get("/api/dupont/ASII/export")
        assert res_export.status_code == 200


# ======================= REGRESSION TESTS v2.2 (bug yang terbukti di audit) =======================
import io
import asyncio
import openpyxl
import pytest
from sqlmodel import SQLModel, Session, create_engine
from app.services.parser import (
    parse_idx_file_bytes,
    save_or_get_cached_statement,
    load_ticker_pair,
)
from app.services import llm_analyzer
from app.services.llm_analyzer import (
    LLMAnomalySummary,
    numbers_are_grounded,
    QualityVerdict,
)
from app.services.terminal_pipeline import (
    TerminalPayload,
    get_terminal_snapshot,
    validate_terminal_payload,
    SupportResistanceItem,
)

def _stmt(**kw):
    base = dict(
        ticker="TEST", company_name="Test Tbk", year=2025, period_type=PeriodType.FY,
        revenue=1000, ebit=200, ebt=180, net_income_parent=140,
        total_assets=1000, total_liabilities=450, total_equity_parent=550,
    )
    base.update(kw)
    return FinancialStatementInput(**base)

def _mem_session():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return Session(eng)

def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def test_parser_ignores_subtotal_rows_and_reads_consolidated_equity():
    data = _xlsx([
        ("ticker", "TEST"), ("year", 2025),
        ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset lancar", 300), ("Jumlah aset", 1000),
        ("Jumlah liabilitas jangka pendek", 150), ("Jumlah liabilitas", 400),
        ("Jumlah ekuitas yang dapat diatribusikan kepada pemilik entitas induk", 550),
        ("Jumlah ekuitas", 600),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.total_assets == 1000
    assert s.total_liabilities == 400
    assert s.total_equity_parent == 550
    assert s.total_equity_consolidated == 600
    assert s.balance_sheet_discrepancy_pct <= 0.05

def test_parser_single_equity_row_used_as_parent():
    data = _xlsx([
        ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset", 1000), ("Jumlah liabilitas", 450), ("Jumlah ekuitas", 550),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.total_equity_parent == 550

def test_parser_bilingual_label_and_not_ebitda():
    data = _xlsx([
        ("Pendapatan usaha", 1000), ("EBITDA", 999999), ("Laba usaha / Operating profit", 200),
        ("Laba sebelum pajak", 180),
        ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
        ("Jumlah aset / Total assets", 1000), ("Jumlah liabilitas / Total liabilities", 450),
        ("Jumlah ekuitas / Total equity", 550),
    ])
    s = parse_idx_file_bytes("t.xlsx", data)
    assert s.ebit == 200
    assert s.total_assets == 1000

def test_yoy_pairs_exactly_previous_year_and_same_period_type():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2024, revenue=900))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, period_type=PeriodType.Q2, revenue=500))
        cur, prev = load_ticker_pair(se, "TEST")
        assert (cur.year, cur.period_type) == (2025, PeriodType.FY)
        assert (prev.year, prev.period_type) == (2024, PeriodType.FY)

def test_yoy_none_when_prior_year_missing_not_same_year():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, period_type=PeriodType.Q2, revenue=500))
        cur, prev = load_ticker_pair(se, "TEST")
        assert cur.year == 2025 and prev is None

def test_reupload_same_period_replaces_row_instead_of_duplicating():
    with _mem_session() as se:
        save_or_get_cached_statement(se, _stmt(year=2024, revenue=900))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1000))
        save_or_get_cached_statement(se, _stmt(year=2025, revenue=1010))
        cur, prev = load_ticker_pair(se, "TEST")
        assert cur.revenue == 1010
        assert prev.year == 2024

def test_margin_collapse_is_flagged_as_deterioration_not_high_quality():
    prev = _stmt(year=2024, ebit=200, ebt=190, net_income_parent=150)
    curr = _stmt(year=2025, ebit=50, ebt=45, net_income_parent=35)
    b = analyze_dupont_yoy(curr, prev)
    assert b.roe_direction == "DOWN"
    assert b.primary_driver == PrimaryDriver.OPERATIONAL_MARGIN
    assert b.primary_driver_effect == "NEGATIVE"
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.OPERATIONAL_DETERIORATION
    assert "High Quality" not in s.quality_verdict
    assert "sehat" not in s.driver_explanation

def test_falling_leverage_is_not_described_as_expansion():
    prev = _stmt(year=2024, total_liabilities=700, total_equity_parent=300, total_assets=1000)
    curr = _stmt(year=2025, total_liabilities=400, total_equity_parent=600, total_assets=1000)
    b = analyze_dupont_yoy(curr, prev)
    assert b.primary_driver == PrimaryDriver.FINANCIAL_LEVERAGE
    assert b.primary_driver_effect == "NEGATIVE"
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.DELEVERAGING
    assert "ekspansi" not in s.driver_explanation.lower()

def test_rising_leverage_with_rising_roe_is_flagged_as_debt_driven():
    prev = _stmt(year=2024, total_liabilities=300, total_equity_parent=700, total_assets=1000)
    curr = _stmt(year=2025, total_liabilities=700, total_equity_parent=300, total_assets=1000)
    b = analyze_dupont_yoy(curr, prev)
    s = generate_deterministic_anomaly_summary(b)
    assert b.roe_direction == "UP"
    assert s.quality_verdict == QualityVerdict.LEVERAGE_DRIVEN

def test_log_contributions_sum_to_log_roe_change():
    import math
    prev = _stmt(year=2024)
    curr = _stmt(year=2025, revenue=1100, ebit=260, ebt=240, net_income_parent=190,
                 total_assets=1200, total_liabilities=600, total_equity_parent=600)
    b = analyze_dupont_yoy(curr, prev)
    total = sum(b.driver_contributions_pct.values())
    expected = math.log(b.current.roe / b.previous.roe) * 100
    assert abs(total - expected) < 1e-6

def test_single_period_summary_has_no_fake_yoy_claims():
    b = analyze_dupont_yoy(_stmt())
    s = generate_deterministic_anomaly_summary(b)
    assert s.quality_verdict == QualityVerdict.SINGLE_PERIOD
    assert "bps" not in s.headline

def test_llm_output_with_invented_numbers_is_rejected():
    b = analyze_dupont_yoy(_stmt(year=2025), _stmt(year=2024, revenue=900))
    ok = generate_deterministic_anomaly_summary(b)
    assert numbers_are_grounded(ok, b) is True
    bad = LLMAnomalySummary(
        headline="ROE melonjak 87.65% YoY", quality_verdict="X",
        driver_explanation="Karena margin 77.77%.", anomaly_bullets=["a", "b"], risk_watchout="r",
    )
    assert numbers_are_grounded(bad, b) is False

def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9")
    llm_analyzer._LLM_CACHE.clear()
    b = analyze_dupont_yoy(_stmt(year=2025), _stmt(year=2024, revenue=900))
    s = asyncio.run(llm_analyzer.summarize_dupont_anomalies(b, wait_for_llm=True))
    assert s.source == "DETERMINISTIC"
    assert s.headline

def test_ingest_rejects_invalid_tick_and_ordering():
    snap = get_terminal_snapshot()
    bad_sr = SupportResistanceItem(ticker="ASII", last_price=5260, s2=4950, s1=5100, r1=5400, r2=5600)
    payload = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[bad_sr],
    )
    errs = validate_terminal_payload(payload)
    assert any("Fraksi" in e for e in errs)
    inverted = SupportResistanceItem(ticker="ASII", last_price=5250, s2=5100, s1=4950, r1=5400, r2=5600)
    payload2 = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[inverted],
    )
    assert any("urutan" in e for e in validate_terminal_payload(payload2))

def test_ingest_endpoint_422_on_bad_payload_and_auth(monkeypatch):
    snap = get_terminal_snapshot()
    bad = SupportResistanceItem(ticker="ASII", last_price=5260, s2=4950, s1=5100, r1=5400, r2=5600)
    body = TerminalPayload(
        header=snap.header, movers=snap.movers, foreign_flows=snap.foreign_flows, sr_matrix=[bad],
    ).model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/api/terminal/ingest", json=body).status_code == 422
        monkeypatch.setenv("INGEST_API_KEY", "rahasia")
        assert client.post("/api/terminal/ingest", json=snap.model_dump(mode="json")).status_code == 401
        ok = client.post(
            "/api/terminal/ingest", json=snap.model_dump(mode="json"), headers={"X-API-Key": "rahasia"}
        )
        assert ok.status_code == 200

def test_unknown_ticker_shows_notice_instead_of_silent_fallback():
    with TestClient(app) as client:
        res = client.get("/?ticker=ZZZZ")
        assert res.status_code == 200
        assert "belum ada di cache" in res.text

def test_upload_endpoint_end_to_end_json_and_xlsx():
    json_body = _stmt(ticker="UPLD", year=2024).model_dump_json().encode()
    with TestClient(app) as client:
        r1 = client.post("/api/dupont/upload", files={"file": ("a.json", json_body)}, data={"ticker": "UPLD"})
        assert r1.status_code == 200
        xlsx = _xlsx([
            ("ticker", "UPLD"), ("year", 2025),
            ("Pendapatan usaha", 1000), ("Laba usaha", 200), ("Laba sebelum pajak", 180),
            ("Laba tahun berjalan yang dapat diatribusikan kepada pemilik entitas induk", 140),
            ("Jumlah aset lancar", 300), ("Jumlah aset", 1000), ("Jumlah liabilitas", 450),
            ("Jumlah ekuitas", 550),
        ])
        r2 = client.post("/api/dupont/upload", files={"file": ("b.xlsx", xlsx)}, data={"ticker": "UPLD"})
        assert r2.status_code == 200
        body = r2.json()
        assert body["bundle"]["previous"]["year"] == 2024
        assert body["bundle"]["current"]["balance_sheet_balanced"] is True
        r3 = client.post("/api/dupont/upload", files={"file": ("c.txt", b"x")})
        assert r3.status_code == 400

def test_export_returns_content_and_node_colors_rendered():
    with TestClient(app) as client:
        res = client.get("/api/dupont/ASII/export")
        assert res.status_code == 200 and len(res.content) > 500
        home = client.get("/?ticker=TLKM")
        assert "text-emerald-400" in home.text or "text-amber-300" in home.text