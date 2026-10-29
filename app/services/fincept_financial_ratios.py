"""
Di-ekstrak langsung dari FinceptTerminal: finance_financial_ratios.ipynb
Fungsional murni rasio finansial untuk melengkapi DuPont Engine.
"""

# --- CELL 2 ---
try:
    import numpy as np
    import pandas as pd
except ImportError:
    raise SystemExit("Fincept Notebook needs pandas + numpy — install with: pip install pandas numpy")

# Fincept Demo Corp — all figures in $ thousands
FIN = {
    # Income statement
    'revenue':            12000.0,
    'cogs':                7200.0,
    'operating_expenses':  2400.0,
    'interest_expense':     300.0,
    'taxes':                540.0,
    # Balance sheet — current assets
    'cash':                1500.0,
    'accounts_receivable': 1800.0,
    'inventory':           2200.0,
    # Balance sheet — non-current assets
    'net_ppe':             6500.0,
    # Balance sheet — liabilities
    'accounts_payable':    1400.0,
    'short_term_debt':      900.0,
    'long_term_debt':      3600.0,
    # Balance sheet — equity
    'common_equity':       6600.0,
}

# Build the income statement as a derived Series
gross_profit = FIN['revenue'] - FIN['cogs']
operating_income = gross_profit - FIN['operating_expenses']
pretax_income = operating_income - FIN['interest_expense']
net_income = pretax_income - FIN['taxes']
income_statement = pd.Series({
    'Revenue': FIN['revenue'],
    'COGS': -FIN['cogs'],
    'Gross profit': gross_profit,
    'Operating expenses': -FIN['operating_expenses'],
    'Operating income (EBIT)': operating_income,
    'Interest expense': -FIN['interest_expense'],
    'Pretax income': pretax_income,
    'Taxes': -FIN['taxes'],
    'Net income': net_income,
}, name='$000s')

current_assets = FIN['cash'] + FIN['accounts_receivable'] + FIN['inventory']
total_assets = current_assets + FIN['net_ppe']
current_liabilities = FIN['accounts_payable'] + FIN['short_term_debt']
total_liabilities = current_liabilities + FIN['long_term_debt']
balance_sheet = pd.Series({
    'Cash': FIN['cash'],
    'Accounts receivable': FIN['accounts_receivable'],
    'Inventory': FIN['inventory'],
    'Total current assets': current_assets,
    'Net PP&E': FIN['net_ppe'],
    'TOTAL ASSETS': total_assets,
    'Current liabilities': current_liabilities,
    'Long-term debt': FIN['long_term_debt'],
    'Total liabilities': total_liabilities,
    'Common equity': FIN['common_equity'],
    'LIAB + EQUITY': total_liabilities + FIN['common_equity'],
}, name='$000s')

print("FINCEPT DEMO CORP — Income Statement ($000s)")
print(income_statement.round(1).to_string())
print()
print("FINCEPT DEMO CORP — Balance Sheet ($000s)")
print(balance_sheet.round(1).to_string())
print()
print(f"Balance check: Assets {total_assets:,.0f} == Liab+Equity {total_liabilities + FIN['common_equity']:,.0f}")


# --- CELL 4 ---
try:
    import numpy as np
    import pandas as pd
except ImportError:
    raise SystemExit("Fincept Notebook needs pandas + numpy — install with: pip install pandas numpy")

FIN = {
    'revenue': 12000.0, 'cogs': 7200.0, 'operating_expenses': 2400.0,
    'interest_expense': 300.0, 'taxes': 540.0,
    'cash': 1500.0, 'accounts_receivable': 1800.0, 'inventory': 2200.0,
    'net_ppe': 6500.0, 'accounts_payable': 1400.0, 'short_term_debt': 900.0,
    'long_term_debt': 3600.0, 'common_equity': 6600.0,
}

current_assets = FIN['cash'] + FIN['accounts_receivable'] + FIN['inventory']
current_liabilities = FIN['accounts_payable'] + FIN['short_term_debt']

current_ratio = current_assets / current_liabilities
quick_ratio = (current_assets - FIN['inventory']) / current_liabilities

liquidity = pd.DataFrame({
    'Ratio': ['Current ratio', 'Quick ratio'],
    'Value': [current_ratio, quick_ratio],
    'Formula': ['CA / CL', '(CA - Inventory) / CL'],
    'Interpretation': [
        'Comfortable short-term cushion (>1.5 is healthy)',
        'Can meet current bills without selling inventory',
    ],
})
liquidity['Value'] = liquidity['Value'].round(2)
print("LIQUIDITY RATIOS — Fincept Demo Corp")
print(liquidity.to_string(index=False))


# --- CELL 6 ---
try:
    import numpy as np
    import pandas as pd
except ImportError:
    raise SystemExit("Fincept Notebook needs pandas + numpy — install with: pip install pandas numpy")

FIN = {
    'revenue': 12000.0, 'cogs': 7200.0, 'operating_expenses': 2400.0,
    'interest_expense': 300.0, 'taxes': 540.0,
    'cash': 1500.0, 'accounts_receivable': 1800.0, 'inventory': 2200.0,
    'net_ppe': 6500.0, 'accounts_payable': 1400.0, 'short_term_debt': 900.0,
    'long_term_debt': 3600.0, 'common_equity': 6600.0,
}

gross_profit = FIN['revenue'] - FIN['cogs']
operating_income = gross_profit - FIN['operating_expenses']
pretax_income = operating_income - FIN['interest_expense']
net_income = pretax_income - FIN['taxes']
total_assets = FIN['cash'] + FIN['accounts_receivable'] + FIN['inventory'] + FIN['net_ppe']

profitability = pd.DataFrame({
    'Ratio': ['Gross margin', 'Operating margin', 'Net margin', 'Return on assets (ROA)', 'Return on equity (ROE)'],
    'Value': [
        gross_profit / FIN['revenue'],
        operating_income / FIN['revenue'],
        net_income / FIN['revenue'],
        net_income / total_assets,
        net_income / FIN['common_equity'],
    ],
    'Interpretation': [
        'Share of revenue left after direct costs',
        'Profitability of core operations (pre-interest/tax)',
        'Bottom-line profit per revenue dollar',
        'Profit generated per dollar of assets',
        'Profit generated per dollar of shareholder equity',
    ],
})
profitability['Value %'] = (profitability['Value'] * 100).round(1)
profitability = profitability[['Ratio', 'Value %', 'Interpretation']]
print("PROFITABILITY RATIOS — Fincept Demo Corp (all shown as %)")
print(profitability.to_string(index=False))


# --- CELL 8 ---
try:
    import numpy as np
    import pandas as pd
except ImportError:
    raise SystemExit("Fincept Notebook needs pandas + numpy — install with: pip install pandas numpy")

FIN = {
    'revenue': 12000.0, 'cogs': 7200.0, 'operating_expenses': 2400.0,
    'interest_expense': 300.0, 'taxes': 540.0,
    'cash': 1500.0, 'accounts_receivable': 1800.0, 'inventory': 2200.0,
    'net_ppe': 6500.0, 'accounts_payable': 1400.0, 'short_term_debt': 900.0,
    'long_term_debt': 3600.0, 'common_equity': 6600.0,
}

gross_profit = FIN['revenue'] - FIN['cogs']
operating_income = gross_profit - FIN['operating_expenses']   # EBIT
total_assets = FIN['cash'] + FIN['accounts_receivable'] + FIN['inventory'] + FIN['net_ppe']
total_debt = FIN['short_term_debt'] + FIN['long_term_debt']

debt_to_equity = total_debt / FIN['common_equity']
interest_coverage = operating_income / FIN['interest_expense']
asset_turnover = FIN['revenue'] / total_assets

lev_eff = pd.DataFrame({
    'Family': ['Leverage', 'Leverage', 'Efficiency'],
    'Ratio': ['Debt-to-equity', 'Interest coverage', 'Asset turnover'],
    'Value': [debt_to_equity, interest_coverage, asset_turnover],
    'Unit': ['x', 'x', 'x'],
    'Interpretation': [
        'Debt is below equity — moderate leverage',
        'EBIT covers interest many times over — low default risk',
        'Each $1 of assets generates this much revenue',
    ],
})
lev_eff['Value'] = lev_eff['Value'].round(2)
print("LEVERAGE & EFFICIENCY RATIOS — Fincept Demo Corp")
print(lev_eff.to_string(index=False))


# --- CELL 10 ---
try:
    import numpy as np
    import pandas as pd
except ImportError:
    raise SystemExit("Fincept Notebook needs pandas + numpy — install with: pip install pandas numpy")

FIN = {
    'revenue': 12000.0, 'cogs': 7200.0, 'operating_expenses': 2400.0,
    'interest_expense': 300.0, 'taxes': 540.0,
    'cash': 1500.0, 'accounts_receivable': 1800.0, 'inventory': 2200.0,
    'net_ppe': 6500.0, 'accounts_payable': 1400.0, 'short_term_debt': 900.0,
    'long_term_debt': 3600.0, 'common_equity': 6600.0,
}

gross_profit = FIN['revenue'] - FIN['cogs']
operating_income = gross_profit - FIN['operating_expenses']
pretax_income = operating_income - FIN['interest_expense']
net_income = pretax_income - FIN['taxes']
current_assets = FIN['cash'] + FIN['accounts_receivable'] + FIN['inventory']
total_assets = current_assets + FIN['net_ppe']
current_liabilities = FIN['accounts_payable'] + FIN['short_term_debt']
total_debt = FIN['short_term_debt'] + FIN['long_term_debt']

rows = [
    ('Liquidity',     'Current ratio',     current_assets / current_liabilities,            'x'),
    ('Liquidity',     'Quick ratio',       (current_assets - FIN['inventory']) / current_liabilities, 'x'),
    ('Profitability', 'Gross margin',      gross_profit / FIN['revenue'] * 100,             '%'),
    ('Profitability', 'Operating margin',  operating_income / FIN['revenue'] * 100,         '%'),
    ('Profitability', 'Net margin',        net_income / FIN['revenue'] * 100,               '%'),
    ('Profitability', 'ROA',               net_income / total_assets * 100,                 '%'),
    ('Profitability', 'ROE',               net_income / FIN['common_equity'] * 100,         '%'),
    ('Leverage',      'Debt-to-equity',    total_debt / FIN['common_equity'],               'x'),
    ('Leverage',      'Interest coverage', operating_income / FIN['interest_expense'],      'x'),
    ('Efficiency',    'Asset turnover',    FIN['revenue'] / total_assets,                   'x'),
]
summary = pd.DataFrame(rows, columns=['Family', 'Ratio', 'Value', 'Unit'])
summary['Value'] = summary['Value'].round(2)
print("FINCEPT DEMO CORP — RATIO SCORECARD")
print(summary.to_string(index=False))

