"""Penjelasan hasil backtesting dalam bahasa awam.

Modul ini menerjemahkan angka metrik menjadi kalimat yang bisa dibaca tanpa
latar belakang keuangan. Aturan penting:
  - Setiap kalimat HARUS merujuk angka riil dari hasil hitung (tidak generik).
  - Bila metrik tidak tersedia (None), tidak ada kalimat karangan -> dilewati.
  - Ambang batas mengikuti konvensi standar (Sharpe >1 baik, >2 sangat baik;
    Calmar >1 berarti CAGR mengalahkan drawdown; dst).
"""

from typing import Any, Dict, List, Optional


def _fmt(v: Optional[float], dec: int = 2, suffix: str = "") -> str:
    if v is None:
        return "N/A"
    return f"{v:,.{dec}f}{suffix}".replace(",", ".")


def _tone(value: Optional[float], good: float, bad: float,
          higher_is_better: bool = True) -> str:
    """'good' | 'warn' | 'bad' | 'na'."""
    if value is None:
        return "na"
    if higher_is_better:
        if value >= good:
            return "good"
        if value >= bad:
            return "warn"
        return "bad"
    if value <= good:
        return "good"
    if value <= bad:
        return "warn"
    return "bad"


def build_interpretation(r: Dict[str, Any]) -> Dict[str, Any]:
    """Bangun ringkasan + penjelasan per metrik dari hasil compute_performance."""
    if not r.get("available"):
        return {"available": False}

    items: List[Dict[str, str]] = []
    tk = r.get("ticker") or "Emiten"
    yrs = r.get("years")
    obs = r.get("observations")
    p0, p1 = r.get("period_start"), r.get("period_end")

    # ── 1. Return: apa yang terjadi dengan uang Anda ──────────────────
    cagr = r.get("cagr_pct")
    tot = r.get("total_return_pct")
    if cagr is not None:
        if cagr >= 15:
            v, t = "Tumbuh cepat", "good"
            x = (f"CAGR {_fmt(cagr,2,'%')} per tahun tergolong tinggi. "
                 f"Uang Rp10 juta menjadi sekitar Rp{_fmt(10*(1+cagr/100)**(yrs or 5),1)} juta "
                 f"dalam {_fmt(yrs,1)} tahun.")
        elif cagr >= 8:
            v, t = "Tumbuh wajar", "good"
            x = (f"CAGR {_fmt(cagr,2,'%')} per tahun mengalahkan inflasi. "
                 f"Total return {_fmt(tot,1,'%')} selama {_fmt(yrs,1)} tahun.")
        elif cagr >= 0:
            v, t = "Tumbuh tipis", "warn"
            x = (f"CAGR {_fmt(cagr,2,'%')} per tahun sangat tipis — nyaris setara "
                 f"deposito, padahal Anda menanggung risiko saham.")
        else:
            v, t = "Menyusut", "bad"
            x = (f"CAGR {_fmt(cagr,2,'%')} per tahun berarti nilai turun. "
                 f"Total return {_fmt(tot,1,'%')} selama {_fmt(yrs,1)} tahun.")
        # CAGR (geometrik) vs rata-rata aritmetik sering berbeda jauh. Tanpa
        # penjelasan, pembaca mengira ada dua angka yang saling bertentangan.
        ann = r.get("annual_return_pct")
        if ann is not None and abs(ann - cagr) > 1.5:
            x += (f" Catatan: ada angka 'rata-rata tahunan' {_fmt(ann,2,'%')} — "
                  f"itu rata-rata aritmetik yang selalu lebih tinggi. Yang benar-benar "
                  f"terjadi pada uang Anda adalah CAGR {_fmt(cagr,2,'%')}, karena "
                  f"fluktuasi menggerus hasil (volatility drag).")
        items.append({"key": "return", "label": "Imbal Hasil (CAGR)",
                      "verdict": v, "tone": t, "text": x})

    # ── 2. Sharpe: apakah return sepadan dengan risiko ────────────────
    sh = r.get("sharpe")
    rf = r.get("risk_free_pct")
    if sh is not None:
        if sh >= 2:
            v, t = "Sangat efisien", "good"
            x = (f"Sharpe {_fmt(sh)} berarti setiap 1% risiko yang Anda tanggung "
                 f"dibayar {_fmt(sh)}% imbal hasil di atas risk-free {_fmt(rf,1,'%')}. "
                 f"Ini tergolong sangat baik (>2).")
        elif sh >= 1:
            v, t = "Efisien", "good"
            x = (f"Sharpe {_fmt(sh)}: imbal hasil sepadan dengan risikonya (>1 dianggap baik). "
                 f"Anda dibayar layak untuk fluktuasi yang Anda alami.")
        elif sh >= 0:
            v, t = "Kurang efisien", "warn"
            x = (f"Sharpe {_fmt(sh)}: imbal hasil hanya sedikit di atas risk-free "
                 f"{_fmt(rf,1,'%')}, padahal risikonya jauh lebih besar daripada deposito. "
                 f"Anda menanggung fluktuasi tanpa bayaran yang sepadan.")
        else:
            v, t = "Tidak efisien", "bad"
            x = (f"Sharpe {_fmt(sh)} (negatif): hasilnya KUAT di bawah risk-free "
                 f"{_fmt(rf,1,'%')}. Anda menanggung risiko saham tetapi hasilnya "
                 f"lebih buruk daripada menaruh uang di SBN/deposito.")
        items.append({"key": "sharpe", "label": "Sharpe Ratio",
                      "verdict": v, "tone": t, "text": x})

    # ── 3. Max Drawdown: sakit terbesar yang harus ditahan ────────────
    dd = r.get("max_drawdown_pct")
    dur = r.get("max_dd_duration_days")
    rec = r.get("max_dd_recovery")
    if dd is not None:
        depth = abs(dd)
        if depth <= 10:
            v, t = "Ringan", "good"
            x = (f"Penurunan terdalam {_fmt(dd,2,'%')} — relatif ringan. "
                 f"Pemegang saham paling buruk hanya melihat nilai turun {_fmt(depth,1,'%')}.")
        elif depth <= 25:
            v, t = "Sedang", "warn"
            x = (f"Penurunan terdalam {_fmt(dd,2,'%')}. Artinya Rp100 juta bisa "
                 f"menjadi Rp{_fmt(100*(1-depth/100),1)} juta di titik terburuk.")
        else:
            v, t = "Dalam", "bad"
            x = (f"Penurunan terdalam {_fmt(dd,2,'%')}. Rp100 juta pernah menyusut "
                 f"menjadi Rp{_fmt(100*(1-depth/100),1)} juta — banyak orang panik "
                 f"jual di titik ini dan mengunci kerugian.")
        if dur:
            x += f" Butuh {dur} hari sampai menyentuh titik terburuk."
        if rec:
            x += f" Baru pulih penuh pada {rec}."
        items.append({"key": "maxdd", "label": "Max Drawdown",
                      "verdict": v, "tone": t, "text": x})

    # ── 4. Beta: ikut pasar atau bergerak sendiri ─────────────────────
    beta = r.get("beta")
    if beta is not None:
        if beta < 0.8:
            v, t = "Defensif", "good"
            x = (f"Beta {_fmt(beta)}: saham ini bergerak lebih tenang daripada IHSG. "
                 f"Kalau IHSG turun 10%, saham ini cenderung turun sekitar "
                 f"{_fmt(beta*10,1,'%')}.")
        elif beta <= 1.2:
            v, t = "Mengikuti pasar", "warn"
            x = (f"Beta {_fmt(beta)}: gerakannya nyaris sejalan IHSG. Membeli saham ini "
                 f"sebagian besar berarti membeli pasar, bukan keunggulan khusus emiten.")
        else:
            v, t = "Agresif", "bad"
            x = (f"Beta {_fmt(beta)}: lebih liar daripada IHSG. Kalau IHSG turun 10%, "
                 f"saham ini cenderung turun sekitar {_fmt(beta*10,1,'%')}.")
        items.append({"key": "beta", "label": "Beta vs IHSG",
                      "verdict": v, "tone": t, "text": x})

    # ── 5. Alpha: nilai tambah di atas pasar ──────────────────────────
    al = r.get("alpha_pct")
    if al is not None:
        if al > 2:
            v, t = "Ada nilai tambah", "good"
            x = (f"Alpha {_fmt(al,2,'%')} per tahun: setelah memperhitungkan risiko pasar, "
                 f"saham ini secara statistik memberi tambahan {_fmt(al,2,'%')} di atas "
                 f"yang seharusnya.")
        elif al >= 0:
            v, t = "Netral", "warn"
            x = (f"Alpha {_fmt(al,2,'%')} per tahun: praktis tidak ada nilai tambah "
                 f"di atas risiko pasar yang sudah ditanggung.")
        else:
            v, t = "Kurang dari pasar", "bad"
            x = (f"Alpha {_fmt(al,2,'%')} per tahun: hasilnya lebih buruk daripada "
                 f"yang seharusnya mengingat risiko yang diambil. Indeks pasif "
                 f"lebih masuk akal kalau ini berlanjut.")
        # REKONSILIASI: alpha dihitung dari rata-rata ARITMETIK return harian
        # (konvensi regresi Jensen), sedangkan CAGR bersifat GEOMETRIK. Pada
        # saham volatil keduanya bisa berlawanan arah dan tanpa penjelasan
        # pembaca melihat angka yang saling bertentangan.
        # Alpha positif TIDAK otomatis berarti cuan: bila CAGR negatif, uang
        # pemegang saham tetap menyusut. Jangan pernah menulis "emiten bagus".
        if al > 0 and cagr is not None and cagr < 0:
            x += (f" TETAPI CAGR {_fmt(cagr,2,'%')} negatif — nilai uang Anda "
                  f"susut. Alpha di sini berarti 'rugi lebih sedikit daripada "
                  f"IHSG', bukan untung.")
            t = "warn"
            v = "Unggul relatif, tetap rugi absolut"
        elif al > 3 and cagr is not None and cagr < 6:
            x += (f" PENTING: alpha ini memakai rata-rata aritmetik, sedangkan "
                  f"CAGR {_fmt(cagr,2,'%')} bersifat geometrik. Volatilitas "
                  f"menggerus selisihnya — jadi 'unggul secara statistik' belum "
                  f"tentu jadi uang lebih di kantong Anda.")
            t = "warn"
            v = "Ada nilai tambah (netral setelah volatilitas)"
        items.append({"key": "alpha", "label": "Jensen Alpha",
                      "verdict": v, "tone": t, "text": x})

    # ── 6. VaR: kerugian harian yang wajar terjadi ────────────────────
    var95 = r.get("var_95_daily_pct")
    var99 = r.get("var_99_daily_pct")
    worst = r.get("worst_day_pct")
    if var95 is not None:
        x = (f"Pada 95% hari perdagangan, kerugian harian tidak melebihi "
             f"{_fmt(abs(var95),2,'%')}. Artinya dari 20 hari kerja, sekitar 1 hari "
             f"bisa rugi lebih dari itu.")
        if var99 is not None:
            x += (f" Pada kasus ekstrem (1 dari 100 hari), kerugian bisa mencapai "
                  f"{_fmt(abs(var99),2,'%')}.")
        if worst is not None:
            x += f" Hari terburuk sepanjang periode: {_fmt(worst,2,'%')}."
        items.append({"key": "var", "label": "Risiko Harian (VaR)",
                      "verdict": "Ukuran kerugian harian", "tone": "info", "text": x})

    # ── 7. Konsistensi: seberapa sering menang ────────────────────────
    hit = r.get("hit_rate_pct")
    mhit = r.get("monthly_hit_rate_pct")
    pm, tm = r.get("positive_months"), r.get("total_months")
    if mhit is not None:
        if mhit >= 60:
            v, t = "Konsisten", "good"
        elif mhit >= 45:
            v, t = "Campuran", "warn"
        else:
            v, t = "Tidak konsisten", "bad"
        x = (f"{_fmt(mhit,1,'%')} bulan ditutup positif")
        if pm and tm:
            x += f" ({pm} dari {tm} bulan)"
        if hit is not None:
            x += f"; harian: {_fmt(hit,1,'%')} hari positif"
        x += ". Angka ini menunjukkan apakah kenaikan terjadi merata atau hanya di beberapa bulan tertentu."
        items.append({"key": "consistency", "label": "Konsistensi",
                      "verdict": v, "tone": t, "text": x})

    # ── 8. Perbandingan dengan benchmark ──────────────────────────────
    bcg = r.get("benchmark_cagr_pct")
    ir = r.get("information_ratio")
    if cagr is not None and bcg is not None:
        diff = cagr - bcg
        if diff > 1:
            v, t = "Mengalahkan IHSG", "good"
            x = (f"CAGR {_fmt(cagr,2,'%')} vs IHSG {_fmt(bcg,2,'%')} — unggul "
                 f"{_fmt(diff,2,'%')} per tahun.")
        elif diff >= -1:
            v, t = "Setara IHSG", "warn"
            x = (f"CAGR {_fmt(cagr,2,'%')} vs IHSG {_fmt(bcg,2,'%')} — praktis sama. "
                 f"Beli reksa dana indeks lebih murah dan sederhana kalau hasilnya serupa.")
        else:
            v, t = "Kalah dari IHSG", "bad"
            x = (f"CAGR {_fmt(cagr,2,'%')} vs IHSG {_fmt(bcg,2,'%')} — tertinggal "
                 f"{_fmt(abs(diff),2,'%')} per tahun. Memilih saham ini berarti "
                 f"mendapat hasil lebih rendah daripada membeli indeks.")
        if ir is not None:
            x += f" Information ratio {_fmt(ir)} (konsistensi unggul: >0,5 baik)."
        items.append({"key": "vs_benchmark", "label": "vs IHSG",
                      "verdict": v, "tone": t, "text": x})

    # ── Ringkasan satu paragraf ───────────────────────────────────────
    good = sum(1 for i in items if i["tone"] == "good")
    bad = sum(1 for i in items if i["tone"] == "bad")

    # Sharpe adalah ukuran tunggal terpenting: imbal hasil per unit risiko.
    # Jangan pernah menyimpulkan "Menarik" bila Sharpe di bawah risk-free —
    # itu akan menyesatkan meski metrik lain terlihat bagus.
    if sh is not None and sh < 0:
        overall, otone = "Tidak layak", "bad"
    elif sh is not None and sh < 0.5:
        overall, otone = "Kurang efisien", "bad"
    elif good >= bad + 3 and (sh is None or sh >= 1.0):
        overall, otone = "Menarik", "good"
    elif bad > good:
        overall, otone = "Kurang menarik", "bad"
    else:
        overall, otone = "Campuran", "warn"

    summary = (
        f"{tk}: dari {obs} hari perdagangan ({p0} sampai {p1}, {_fmt(yrs,1)} tahun) "
        f"imbal hasil {_fmt(cagr,2,'%')} per tahun dengan Sharpe {_fmt(sh)}. "
    )
    if dd is not None:
        summary += (f"Untuk mendapat itu, pemegang saham harus sanggup menahan "
                    f"penurunan {_fmt(abs(dd),1,'%')}. ")
    if bcg is not None and cagr is not None:
        summary += ("Kinerjanya mengalahkan IHSG." if cagr - bcg > 1
                    else "Kinerjanya tidak mengalahkan IHSG." if cagr - bcg < -1
                    else "Kinerjanya setara IHSG.")
    summary += " Bukan ramalan ke depan — ini rekam jejak yang sudah terjadi."

    return {
        "available": True,
        "overall": overall,
        "overall_tone": otone,
        "summary": summary,
        "items": items,
        "note": ("Semua angka dihitung dari harga penutupan harian yang tersimpan. "
                 "Tidak ada proyeksi maupun simulasi. Kinerja masa lalu bukan jaminan "
                 "kinerja masa depan; rezim pasar (suku bunga, komoditas, regulasi) "
                 "bisa berubah."),
    }
