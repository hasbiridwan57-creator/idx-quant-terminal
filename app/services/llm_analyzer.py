import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

import httpx
# Manual .env parser tanpa dependensi python-dotenv
def _load_env_file():
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k and not os.environ.get(k):
                            os.environ[k] = v
        except Exception:
            pass

_load_env_file()

from pydantic import BaseModel, Field
from app.services.dupont_engine import DuPontAnalysisBundle, PrimaryDriver

class QualityVerdict:
    OPERATIONAL_DRIVEN = "OPERATIONAL_DRIVEN (High Quality)"
    OPERATIONAL_DETERIORATION = "OPERATIONAL_DETERIORATION (Margin/Turnover Melemah)"
    LEVERAGE_DRIVEN = "LEVERAGE_DRIVEN (Debt Expansion Alert)"
    DELEVERAGING = "DELEVERAGING (Leverage Menurun)"
    TAX_INTEREST_DISTORTED = "NON_OPERATIONAL_DISTORTED (Tax/Interest Shift)"
    STABLE = "STABLE (ROE Relatif Stabil)"
    MIXED = "MIXED_SIGNALS (Faktor Saling Berlawanan)"
    SINGLE_PERIOD = "BASELINE (Belum Ada Pembanding YoY)"
    DISTRESS_ALERT = "EQUITY_OR_EARNINGS_DISTRESS"

class LLMAnomalySummary(BaseModel):
    headline: str = Field(..., description="Ringkasan utama 1 kalimat perubahan ROE YoY")
    quality_verdict: str
    driver_explanation: str = Field(..., description="Analisis apakah ROE digerakkan oleh margin, turnover, atau utang")
    anomaly_bullets: List[str] = Field(..., min_length=2, max_length=5)
    risk_watchout: str
    source: str = Field(default="DETERMINISTIC", description="DETERMINISTIC atau LLM (tervalidasi)")

SYSTEM_PROMPT_EQUITY_RESEARCH = """
Anda adalah Senior Equity Research Analyst khusus pasar modal Indonesia (BEI/IDX).
Tugas Anda adalah merangkum anomali rasio DuPont 3-Stage dan 5-Stage berdasarkan JSON yang diberikan.

ATURAN KERAS (ANTI-HALUSINASI):
1. DILARANG menghitung ulang rasio atau mengarang angka baru. Gunakan HANYA angka yang tertera di JSON input.
2. Jawab pertanyaan inti: Apakah perubahan ROE dibanding tahun sebelumnya didorong oleh kualitas operasional (EBIT Margin / Asset Turnover) atau didorong oleh penambahan utang (Equity Multiplier)?
3. Patuhi field `roe_direction` (UP/DOWN/FLAT) dan `primary_driver_effect` (POSITIVE/NEGATIVE). Jangan menyebut ROE "naik" jika roe_direction = DOWN, dan jangan menyebut faktor "ekspansi" jika efeknya NEGATIVE.
4. Jika `is_negative_equity` bernilai true, jelaskan bahwa emiten mengalami defisiensi modal sehingga ROE tidak bermakna secara analitis (NM).
5. Kembalikan HANYA JSON valid dengan kunci persis: headline (string), quality_verdict (string), driver_explanation (string), anomaly_bullets (array 2-5 string), risk_watchout (string).
""".strip()

_DRIVER_LABEL = {
    PrimaryDriver.OPERATIONAL_MARGIN: "EBIT Margin (margin operasional)",
    PrimaryDriver.ASSET_EFFICIENCY: "Asset Turnover (efisiensi aset)",
    PrimaryDriver.FINANCIAL_LEVERAGE: "Equity Multiplier (financial leverage)",
    PrimaryDriver.TAX_OR_INTEREST_BURDEN: "beban bunga & pajak (Interest/Tax Burden)",
}
_DRIVER_DELTA_KEYS = {
    PrimaryDriver.OPERATIONAL_MARGIN: "ebit_margin",
    PrimaryDriver.ASSET_EFFICIENCY: "asset_turnover",
    PrimaryDriver.FINANCIAL_LEVERAGE: "equity_multiplier",
}

def _pct(v: Optional[float]) -> str:
    return "NM" if v is None else f"{v * 100:.2f}%"

def _mult(v: Optional[float]) -> str:
    return "NM" if v is None else f"{v:.2f}x"

def _verdict(bundle: DuPontAnalysisBundle) -> str:
    driver, effect, direction = bundle.primary_driver, bundle.primary_driver_effect, bundle.roe_direction
    if direction == "FLAT":
        return QualityVerdict.STABLE
    if driver in (PrimaryDriver.OPERATIONAL_MARGIN, PrimaryDriver.ASSET_EFFICIENCY):
        if effect == "POSITIVE" and direction == "UP":
            return QualityVerdict.OPERATIONAL_DRIVEN
        if effect == "NEGATIVE":
            return QualityVerdict.OPERATIONAL_DETERIORATION
        return QualityVerdict.MIXED
    if driver == PrimaryDriver.FINANCIAL_LEVERAGE:
        if effect == "POSITIVE" and direction == "UP":
            return QualityVerdict.LEVERAGE_DRIVEN
        if effect == "NEGATIVE":
            return QualityVerdict.DELEVERAGING
        return QualityVerdict.MIXED
    if driver == PrimaryDriver.TAX_OR_INTEREST_BURDEN:
        return QualityVerdict.TAX_INTEREST_DISTORTED
    return QualityVerdict.MIXED

def generate_deterministic_anomaly_summary(bundle: DuPontAnalysisBundle) -> LLMAnomalySummary:
    curr = bundle.current
    deltas = bundle.yoy_deltas

    if curr.is_negative_equity:
        return LLMAnomalySummary(
            headline=f"[{curr.ticker}] Peringatan Defisiensi Modal: Ekuitas Entitas Induk bernilai negatif.",
            quality_verdict=QualityVerdict.DISTRESS_ALERT,
            driver_explanation="Kalkulasi ROE dan Equity Multiplier dinonaktifkan (NM) untuk mencegah distorsi matematis akibat ekuitas negatif.",
            anomaly_bullets=[
                f"Net Profit Margin tercatat sebesar {_pct(curr.net_profit_margin)} dengan EBIT Margin {_pct(curr.ebit_margin)}.",
                "Struktur permodalan membutuhkan restrukturisasi atau injeksi ekuitas sebelum rasio pengembalian ekuitas dapat dievaluasi.",
            ],
            risk_watchout="Risiko solvabilitas tinggi; fokuskan analisis pada arus kas operasional dan rasio cakupan bunga.",
            source="DETERMINISTIC",
        )

    roe_str = _pct(curr.roe)
    roe_d = deltas.get("roe")
    has_prev = bundle.previous is not None and roe_d is not None and roe_d.bps_change is not None
    bps_text = f"({roe_d.bps_change:+.0f} bps YoY)" if has_prev else "(periode tunggal, belum ada pembanding YoY)"

    base_bullets = [
        f"ROE: {roe_str} {bps_text} | NPM: {_pct(curr.net_profit_margin)} | EBIT Margin: {_pct(curr.ebit_margin)}.",
        f"Perputaran Aset (AT): {_mult(curr.asset_turnover)} | Financial Leverage (EM): {_mult(curr.equity_multiplier)}.",
        f"Dekomposisi 5-Stage: Interest Burden {_mult(curr.interest_burden)} | Tax Burden {_mult(curr.tax_burden)}.",
    ]

    if not has_prev or bundle.primary_driver == PrimaryDriver.INSUFFICIENT_PRIOR_DATA:
        bullets = base_bullets + bundle.warnings[:2]
        return LLMAnomalySummary(
            headline=f"[{curr.ticker} {curr.year} {curr.period_type.value}] ROE {roe_str} — baseline tanpa pembanding YoY",
            quality_verdict=QualityVerdict.SINGLE_PERIOD,
            driver_explanation=(
                f"ROE {roe_str} terdiri dari NPM {_pct(curr.net_profit_margin)} x AT {_mult(curr.asset_turnover)} "
                f"x EM {_mult(curr.equity_multiplier)}. Unggah laporan periode sejenis tahun sebelumnya untuk atribusi YoY."
            ),
            anomaly_bullets=bullets[:5],
            risk_watchout="Tanpa pembanding YoY, arah dan kualitas perubahan ROE belum dapat dinilai.",
            source="DETERMINISTIC",
        )

    direction_word = {"UP": "naik", "DOWN": "turun", "FLAT": "relatif stabil"}.get(bundle.roe_direction, "berubah")
    driver = bundle.primary_driver
    label = _DRIVER_LABEL[driver]
    dkey = _DRIVER_DELTA_KEYS.get(driver)
    if dkey and dkey in deltas and deltas[dkey].previous_val is not None and deltas[dkey].current_val is not None:
        is_rate = dkey in ("ebit_margin",)
        fmt = _pct if is_rate else _mult
        factor_move = f"{fmt(deltas[dkey].previous_val)} menjadi {fmt(deltas[dkey].current_val)}"
        factor_dir = "naik" if bundle.primary_driver_effect == "POSITIVE" else "turun"
    else:
        factor_move, factor_dir = "berubah", ("naik" if bundle.primary_driver_effect == "POSITIVE" else "turun")

    verdict = _verdict(bundle)
    if verdict == QualityVerdict.STABLE:
        driver_exp = f"ROE {roe_str} {bps_text} relatif stabil; perubahan antar komponen DuPont saling mengimbangi (faktor terbesar: {label})."
    elif verdict == QualityVerdict.LEVERAGE_DRIVEN:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text} terutama karena {label} {factor_dir} ({factor_move}), "
            f"yaitu dorongan utang, bukan perbaikan margin operasional."
        )
    elif verdict == QualityVerdict.DELEVERAGING:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; faktor terbesar adalah penurunan {label} ({factor_move}), "
            f"artinya emiten mengurangi leverage sehingga efek pengungkit pada ROE melemah."
        )
    elif verdict == QualityVerdict.OPERATIONAL_DRIVEN:
        driver_exp = (
            f"ROE naik ke {roe_str} {bps_text} ditopang perbaikan operasional: {label} {factor_dir} ({factor_move}), "
            f"bukan dari penambahan utang."
        )
    elif verdict == QualityVerdict.OPERATIONAL_DETERIORATION:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text} akibat pelemahan operasional: {label} {factor_dir} ({factor_move}). "
            f"Ini penurunan kualitas laba, bukan efek leverage."
        )
    elif verdict == QualityVerdict.TAX_INTEREST_DISTORTED:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; pergerakannya banyak dipengaruhi {label} "
            f"(Interest Burden {_mult(curr.interest_burden)}, Tax Burden {_mult(curr.tax_burden)})."
        )
    else:
        driver_exp = (
            f"ROE {direction_word} ke {roe_str} {bps_text}; faktor terbesar ({label}) bergerak berlawanan "
            f"dengan arah ROE sehingga sinyalnya campuran."
        )

    bullets = list(base_bullets)
    if bundle.driver_contributions_pct:
        names = {
            "OPERATIONAL_MARGIN": "Margin", "ASSET_EFFICIENCY": "Turnover",
            "FINANCIAL_LEVERAGE": "Leverage", "TAX_OR_INTEREST_BURDEN": "Bunga/Pajak",
        }
        parts = ", ".join(f"{names[k]} {v:+.1f}%" for k, v in bundle.driver_contributions_pct.items())
        bullets.append(f"Kontribusi ke perubahan ROE (log, aditif): {parts}.")
    if bundle.warnings:
        bullets.extend(bundle.warnings[:1])

    return LLMAnomalySummary(
        headline=f"[{curr.ticker} {curr.year} {curr.period_type.value}] ROE {roe_str} {bps_text} — driver: {driver.value} ({bundle.primary_driver_effect})",
        quality_verdict=verdict,
        driver_explanation=driver_exp,
        anomaly_bullets=bullets[:5],
        risk_watchout="Pantau konsistensi EBIT Margin dan Interest Burden jika Equity Multiplier melampaui 2.50x.",
        source="DETERMINISTIC",
    )

# ---------------------------------------------------------------- validasi angka LLM
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
ALLOWED_CONSTANTS = {2.5}

def _collect_numbers(obj: Any, out: Set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        v = abs(float(obj))
        out.update({v, v * 100.0, v * 10000.0})
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            out.add(abs(float(tok.replace(",", "."))))

def numbers_are_grounded(summary: LLMAnomalySummary, bundle: DuPontAnalysisBundle) -> bool:
    allowed: Set[float] = set(ALLOWED_CONSTANTS)
    _collect_numbers(bundle.model_dump(mode="json"), allowed)
    text = " ".join(
        [summary.headline, summary.quality_verdict, summary.driver_explanation, summary.risk_watchout]
        + list(summary.anomaly_bullets)
    )
    for tok in _NUM_RE.findall(text):
        val = abs(float(tok.replace(",", ".")))
        if val.is_integer() and val <= 5:
            continue
        if not any(abs(val - a) <= max(0.06, abs(a) * 0.01) for a in allowed):
            return False
    return True

# ---------------------------------------------------------------- cache & orkestrasi
_LLM_CACHE: Dict[str, LLMAnomalySummary] = {}
_INFLIGHT: Dict[str, asyncio.Task[None]] = {}
_CACHE_MAX = 256

def _cache_key(bundle: DuPontAnalysisBundle) -> str:
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    return hashlib.sha256((model + bundle.model_dump_json()).encode("utf-8")).hexdigest()

async def _call_llm(bundle: DuPontAnalysisBundle) -> Optional[LLMAnomalySummary]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_name,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT_EQUITY_RESEARCH},
                        {"role": "user", "content": bundle.model_dump_json()},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            raw_json = json.loads(resp.json()["choices"][0]["message"]["content"])
            raw_json["source"] = "LLM (angka tervalidasi)"
            summary = LLMAnomalySummary(**raw_json)
    except Exception:
        return None
    return summary if numbers_are_grounded(summary, bundle) else None

async def _warm_cache(key: str, bundle: DuPontAnalysisBundle) -> None:
    try:
        result = await _call_llm(bundle)
        if result is not None:
            if len(_LLM_CACHE) >= _CACHE_MAX:
                _LLM_CACHE.pop(next(iter(_LLM_CACHE)))
            _LLM_CACHE[key] = result
    finally:
        _INFLIGHT.pop(key, None)

async def summarize_dupont_anomalies(
    bundle: DuPontAnalysisBundle, wait_for_llm: bool = True
) -> LLMAnomalySummary:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return generate_deterministic_anomaly_summary(bundle)

    key = _cache_key(bundle)
    if key in _LLM_CACHE:
        return _LLM_CACHE[key]

    if not wait_for_llm:
        if key not in _INFLIGHT:
            _INFLIGHT[key] = asyncio.create_task(_warm_cache(key, bundle))
        return generate_deterministic_anomaly_summary(bundle)

    result = await _call_llm(bundle)
    if result is None:
        return generate_deterministic_anomaly_summary(bundle)
    _LLM_CACHE[key] = result
    return result
