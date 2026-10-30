"""
Working Capital & Cash Conversion Cycle (Institutional Grade)
Standar: CFA Institute Corporate Finance, McKinsey Valuation.

CCC = DIO + DSO - DPO
  DIO (Days Inventory Outstanding)     = Inventories / COGS * 365
  DSO (Days Sales Outstanding)         = Trade Receivables / Revenue * 365
  DPO (Days Payables Outstanding)      = Trade Payables / COGS * 365

ZERO-FAKE: semua input dari XBRL audited. Field hilang -> None -> UI render N/A.
"""
from __future__ import annotations

from typing import Dict, Optional, Any

DAYS = 365.0


def _r(num: Optional[float], den: Optional[float], mult: float = DAYS) -> Optional[float]:
    """Rasio aman: None jika pembilang/penyebut kosong atau penyebut <= 0."""
    if num is None or den is None or den <= 0:
        return None
    return (num / den) * mult


def compute_working_capital(fy: dict, bank: bool = False) -> Dict[str, Any]:
    """
    Hitung Cash Conversion Cycle dari satu baris tahunan audited.

    Bank TIDAK punya inventory/CCC bermakna -> return unavailable (jujur, bukan 0).
    """
    out: Dict[str, Any] = {
        "available": False,
        "reason": None,
        "dio_days": None,
        "dso_days": None,
        "dpo_days": None,
        "ccc_days": None,
        "inventories_bn": fy.get("inventories_bn"),
        "receivables_bn": fy.get("trade_receivables_bn"),
        "payables_bn": fy.get("trade_payables_bn"),
        "cogs_bn": fy.get("cost_of_sales_bn"),
        "revenue_bn": fy.get("revenue_bn"),
        "provenance": {},
    }

    if bank:
        out["reason"] = "Bank tidak memiliki siklus konversi kas operasional (tanpa inventory/COGS)"
        return out

    cogs = fy.get("cost_of_sales_bn")
    rev = fy.get("revenue_bn")

    dio = _r(fy.get("inventories_bn"), cogs)
    dso = _r(fy.get("trade_receivables_bn"), rev)
    dpo = _r(fy.get("trade_payables_bn"), cogs)

    out["dio_days"] = round(dio, 1) if dio is not None else None
    out["dso_days"] = round(dso, 1) if dso is not None else None
    out["dpo_days"] = round(dpo, 1) if dpo is not None else None

    # CCC hanya bisa dihitung jika ketiga komponen tersedia (tidak boleh parsial)
    if dio is not None and dso is not None and dpo is not None:
        ccc = dio + dso - dpo
        out["ccc_days"] = round(ccc, 1)
        out["available"] = True
        out["provenance"] = {
            "dio": "COMPUTED (Inventories/COGS)",
            "dso": "COMPUTED (Receivables/Revenue)",
            "dpo": "COMPUTED (Payables/COGS)",
            "ccc": "COMPUTED (DIO+DSO-DPO)",
        }
    else:
        missing = []
        if dio is None:
            missing.append("Inventory" if fy.get("inventories_bn") is None else "COGS")
        if dso is None:
            missing.append("Receivables" if fy.get("trade_receivables_bn") is None else "Revenue")
        if dpo is None:
            missing.append("Payables" if fy.get("trade_payables_bn") is None else "COGS")
        out["reason"] = "Komponen tidak lengkap: " + ", ".join(sorted(set(missing)))

    return out


def interpret_ccc(ccc: Optional[float], dpo: Optional[float] = None) -> Dict[str, str]:
    """
    Interpretasi institusional CCC -> label + warna + implikasi.

    PENTING: CCC negatif TIDAK otomatis berarti efisien. DPO ekstrem (>120 hari)
    pada emiten dengan ekuitas negatif atau rugi adalah tanda DISTRESS — perusahaan
    menunggak pemasok karena tidak punya kas, bukan karena punya daya tawar.
    Membedakan keduanya mencegah salah baca yang fatal.
    """
    if ccc is None:
        return {"label": "N/A", "tone": "neutral", "note": "Data tidak lengkap di XBRL audited"}

    if ccc < 0:
        # DPO sangat panjang bisa berarti daya tawar (retail) ATAU tunggakan (distress).
        if dpo is not None and dpo > 120:
            return {
                "label": "NEGATIF (Perlu Waspada)",
                "tone": "warn",
                "note": (
                    f"DPO {dpo:.0f} hari — pemasok menanggung operasi dalam waktu lama. "
                    "Bisa daya tawar kuat (retail modern), tapi bila disertai ekuitas "
                    "negatif/rugi ini indikasi tunggakan akibat tekanan likuiditas."
                ),
            }
        return {
            "label": "NEGATIF (Efisien)",
            "tone": "good",
            "note": "Pemasok membiayai operasi — model bisnis ringan modal kerja (contoh: retail modern, marketplace)",
        }
    if ccc <= 30:
        return {
            "label": "SANGAT EFISIEN",
            "tone": "good",
            "note": "Siklus kas pendek, modal kerja ringan",
        }
    if ccc <= 90:
        return {
            "label": "NORMAL",
            "tone": "ok",
            "note": "Siklus kas wajar untuk sektor manufaktur/distribusi",
        }
    if ccc <= 180:
        return {
            "label": "PANJANG",
            "tone": "warn",
            "note": "Modal kerja berat — perhatikan risiko likuiditas & biaya bunga",
        }
    return {
        "label": "SANGAT PANJANG (Risiko)",
        "tone": "bad",
        "note": "Kas terkunci lama di persediaan/piutang — tekanan likuiditas tinggi",
    }


def compute_ebitda(fy: dict) -> Dict[str, Any]:
    """
    EBITDA jujur = EBIT (Top-Down/Bottom-Up) + D&A.
    Jika EBIT atau D&A tidak tersedia -> None (bukan 0, bukan karangan).
    """
    ebit = fy.get("ebit_bn_computed")
    if ebit is None:
        ebit = fy.get("ebit_bn")
    if ebit is None:
        # fallback hitung Top-Down di sini jika engine belum mengisi
        gp = fy.get("gross_profit_bn")
        if gp is not None:
            ebit = gp - (fy.get("selling_expense_bn") or 0.0) - (fy.get("ga_expense_bn") or 0.0)
    da = fy.get("depreciation_amortization_bn")

    ebitda = (ebit + da) if (ebit is not None and da is not None) else None
    rev = fy.get("revenue_bn")

    return {
        "ebit_bn": ebit,
        "da_bn": da,
        "ebitda_bn": ebitda,
        "ebitda_margin_pct": round(ebitda / rev * 100, 1) if (ebitda is not None and rev) else None,
        "da_pct_revenue": round(da / rev * 100, 1) if (da is not None and rev) else None,
        "available": ebitda is not None,
        "provenance": {
            "ebit": "COMPUTED (Gross Profit - S&M - G&A)" if fy.get("gross_profit_bn") is not None else "N/A",
            "da": "REPORTED (XBRL Depreciation + Amortization)" if da is not None else "N/A (xsi:nil di filing)",
            "ebitda": "COMPUTED (EBIT + D&A)" if ebitda is not None else "N/A",
        },
    }
