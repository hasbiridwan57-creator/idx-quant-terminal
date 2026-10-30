"""
AI Equity Research Copilot (Institutional FinTech Specialist)
Connects directly to 24/7 VPS 9Router Gateway (https://huahua-server-01-131.tail0bec67.ts.net/v1)
Model: dahl
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

# Load .env fallback if not present in os.environ
_ENV_PATH = "/Users/hasbi/idx-quant-terminal/.env"
if os.path.exists(_ENV_PATH):
    try:
        with open(_ENV_PATH) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    if _k.strip() not in os.environ:
                        os.environ[_k.strip()] = _v.strip().strip("'\"")
    except Exception:
        pass

# Fallback config
VPS_URL = os.getenv("OPENAI_BASE_URL", "https://huahua-server-01-131.tail0bec67.ts.net/v1")
MODEL_NAME = os.getenv("LLM_MODEL", "dahl")
API_KEY = os.getenv("OPENAI_API_KEY", "")


SYSTEM_PROMPT = """Kamu adalah Senior Equity Research Analyst di Divisi Global Investment Research (GIR) firma tier-1 (ex-Goldman Sachs / Morgan Stanley FIG & FinTech).
Kamu memegang lisensi CFA (Chartered Financial Analyst) dan berspesialisasi dalam perbankan, teknologi finansial (FinTech), dan valuasi kuantitatif di Bursa Efek Indonesia (BEI/IDX).

PRINSIP WAJIB:
1. ZERO FAKE DATA: Gunakan HANYA angka yang ada di dalam Financial Context yang diberikan. Jika suatu metrik bernilai null / N/A, katakan dengan jujur "Data tidak dilaporkan pada XBRL audited BEI" dan jelaskan dampaknya terhadap valuasi. Jangan sekali-kali mengarang angka.
2. DISIPLIN AKUNTANSI TIER-1:
   - Bedakan tegas Non-Bank vs Bank: Bank TIDAK memakai EBIT atau Gross Profit, melainkan PPOP (Pre-Provision Operating Profit) dan NIM.
   - Bedakan Top-Down EBIT (GP - SGA) vs Bottom-Up (PBT + Finance Costs). Untuk konglomerat (seperti ASII), sebutkan kontribusi laba entitas asosiasi.
   - Gunakan terminologi institusional: ROIC, NOPAT, Invested Capital, WACC, Altman Z'', Beneish M-Score, Sloan Accruals, Cost of Risk (CoR).
3. GAYA JAWABAN:
   - Terstruktur, analitis, tajam, padat, berbobot institusional.
   - Gunakan bahasa Indonesia profesional finansial (campuran istilah teknis Inggris standar pasar modal: ROE, WACC, Margin, Free Cash Flow, Coverage, Downside Protection).
   - Berikan rekomendasi (BUY / HOLD / SELL) yang koheren dengan margin of safety target price terhadap harga pasar.
"""


def query_analyst_copilot(
    ticker: str,
    user_query: str,
    context: Dict[str, Any],
    chat_history: Optional[List[Dict[str, str]]] = None,
    timeout_s: int = 120
) -> Dict[str, Any]:
    """
    Kirim query analisis ke 9Router VPS dengan menyertakan context fundamental riil.
    """
    url = f"{VPS_URL.rstrip('/')}/chat/completions"

    # Ringkas context fundamental agar hemat token tapi kaya data
    ctx_summary = {
        "ticker": ticker,
        "company_name": context.get("company_name"),
        "sector": context.get("sector"),
        "current_price": context.get("current_price"),
        "target_price": context.get("target_price"),
        "recommendation": context.get("recommendation"),
        "upside_pct": context.get("upside_pct"),
        "wacc_pct": context.get("wacc_pct"),
        "pe_ratio": context.get("pe_ratio"),
        "pbv_ratio": context.get("pbv_ratio"),
        "roe_pct": context.get("roe_pct"),
        "is_bank": context.get("is_bank"),
        "fundamentals_source": context.get("fundamentals_source"),
        "historical_financials_summary": context.get("historical_financials", [])[-3:],
        "forensic_sloan": context.get("sloan_accruals"),
        "forensic_beneish": context.get("beneish_m_score"),
        "dupont_5way": context.get("dupont_5way"),
        "wacc_build_up": context.get("wacc_build_up"),
    }

    user_msg_with_context = f"""[FINANCIAL CONTEXT RESMI DARI TERMINAL]:
{json.dumps(ctx_summary, indent=2, ensure_ascii=False)}

[PERTANYAAN PENGGUNA]:
{user_query}
"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if chat_history:
        for msg in chat_history[-6:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_msg_with_context})

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 8000,  # Thinking model → perlu ruang besar untuk CoT + jawaban final
        "stream": False,
    }
    # Tuple timeout = (connect_timeout, read_timeout); give gateway room to breathe
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}" if API_KEY else "Bearer none",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            # Bersihkan blok reasoning  yang bocor dari model dahl
            import re as _re
            answer = _re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", answer, flags=_re.S | _re.I).strip()
            return {
                "success": True,
                "answer": answer or "(Model tidak mengembalikan jawaban final.)",
                "model": data.get("model", MODEL_NAME),
                "source": "9Router VPS (dahl)",
            }
    except Exception as exc:
        return {
            "success": False,
            "answer": f"Analyst Copilot sedang offline / timeout ({type(exc).__name__}: {str(exc)}). Pastikan koneksi gateway 9Router aktif.",
            "error": str(exc),
            "source": "FALLBACK_OFFLINE",
        }
