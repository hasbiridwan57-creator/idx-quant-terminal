"""Verifikasi: sel baseline matriks sensitivitas == Enterprise Value kartu utama.

Sebelum perbaikan, matriks memakai growth 3% sementara kartu memakai
fcf_growth_rate dari input (5%) -> selisih ~13%. Uji ini mengunci perilaku
benar supaya tidak regresi.
"""
from app.services.fincept_valuation import DCFModel

model = DCFModel("TEST")
base_fcf = 1000.0
wacc = 0.1163
tg = 0.025
growth = 0.05

# EV baseline persis seperti yang dihitung comprehensive_dcf.
proj_main = model.project_cash_flows(base_fcf, growth, 5)
tv_main = model.calculate_terminal_value(proj_main[-1], tg, wacc)
ev_main = model.calculate_enterprise_value(proj_main, tv_main, wacc)

sens = model.sensitivity_analysis(base_fcf, wacc, tg, 5, fcf_growth=growth)
# Baris tengah = TG baseline, kolom tengah = WACC baseline.
row_mid = sens["ev_matrix"][2]
ev_cell_trillion = row_mid[2]
ev_cell = ev_cell_trillion * 1000.0

diff_pct = abs(ev_cell - ev_main) / ev_main * 100
print(f"EV kartu utama : {ev_main:,.2f} miliar")
print(f"EV sel baseline: {ev_cell:,.2f} miliar")
print(f"selisih        : {diff_pct:.4f}%")

assert diff_pct < 0.5, f"matriks tidak konsisten dengan kartu utama ({diff_pct:.2f}%)"

# Dan growth matriks memang mengikuti parameter, bukan 3% hardcode.
sens3 = model.sensitivity_analysis(base_fcf, wacc, tg, 5, fcf_growth=0.03)
assert sens3["ev_matrix"][2][2] != row_mid[2], "growth parameter diabaikan"
print("OK: baseline konsisten, growth parameter dipakai")
