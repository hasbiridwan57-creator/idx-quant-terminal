# app/services/units.py
"""
Standarisasi konversi satuan laporan keuangan ke Rupiah penuh (IDR) dan Miliar Rupiah (Bn IDR).
Menghilangkan heuristik 'revenue < 1e9' yang merusak laporan dalam satuan jutaan.
"""
from typing import Any, Optional

def to_idr(stmt: Any, value: Optional[float]) -> Optional[float]:
    """
    Konversi nilai laporan ke Rupiah penuh.
    Menggunakan stmt.unit_multiplier (default 1.0 jika None / 0).
    Aman untuk None.
    """
    if value is None:
        return None
    multiplier = getattr(stmt, "unit_multiplier", None) or 1.0
    try:
        return float(value) * float(multiplier)
    except (ValueError, TypeError):
        return None

def to_bn(stmt: Any, value: Optional[float]) -> Optional[float]:
    """
    Konversi nilai laporan ke Miliar Rupiah (Bn IDR = IDR / 1e9).
    Aman untuk None.
    """
    idr_val = to_idr(stmt, value)
    if idr_val is None:
        return None
    return idr_val / 1e9
