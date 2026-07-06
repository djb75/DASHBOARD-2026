"""FRED series universe for the macro data scraper.

Parallel to config.py (the Yahoo Finance price universe) — this file defines
the economic data series pulled from the FRED API, one entry per series.

Fields per entry:
    series_id  — FRED series identifier (case-sensitive)
    name       — display name for the dashboard
    category   — dashboard grouping
    region     — geography the series describes
    frequency  — native release frequency: "d" daily, "w" weekly,
                 "m" monthly, "q" quarterly. Drives how much history is
                 requested and how YoY comparisons are computed.
    units      — short human-readable unit label (FRED native units)
"""

SERIES = [
    # ------------------------------------------------------------------
    # Growth / activity
    # ------------------------------------------------------------------
    {"series_id": "GDPC1",             "name": "Real GDP (level)",                    "category": "Growth",     "region": "US",        "frequency": "q", "units": "Bil. chn 2017 $"},
    {"series_id": "A191RL1Q225SBEA",   "name": "Real GDP (% SAAR)",                   "category": "Growth",     "region": "US",        "frequency": "q", "units": "% SAAR"},
    {"series_id": "INDPRO",            "name": "Industrial Production",               "category": "Growth",     "region": "US",        "frequency": "m", "units": "Index 2017=100"},
    {"series_id": "RSAFS",             "name": "Retail Sales",                        "category": "Growth",     "region": "US",        "frequency": "m", "units": "Mil. $"},
    {"series_id": "DGORDER",           "name": "Durable Goods New Orders",            "category": "Growth",     "region": "US",        "frequency": "m", "units": "Mil. $"},
    {"series_id": "TCU",               "name": "Capacity Utilization",                "category": "Growth",     "region": "US",        "frequency": "m", "units": "%"},
    # ------------------------------------------------------------------
    # Labor market
    # ------------------------------------------------------------------
    {"series_id": "PAYEMS",            "name": "Nonfarm Payrolls (level)",            "category": "Labor",      "region": "US",        "frequency": "m", "units": "Thous."},
    {"series_id": "UNRATE",            "name": "Unemployment Rate",                   "category": "Labor",      "region": "US",        "frequency": "m", "units": "%"},
    {"series_id": "ICSA",              "name": "Initial Jobless Claims",              "category": "Labor",      "region": "US",        "frequency": "w", "units": "Number"},
    {"series_id": "JTSJOL",            "name": "JOLTS Job Openings",                  "category": "Labor",      "region": "US",        "frequency": "m", "units": "Thous."},
    {"series_id": "CES0500000003",     "name": "Average Hourly Earnings",             "category": "Labor",      "region": "US",        "frequency": "m", "units": "$/hour"},
    {"series_id": "CIVPART",           "name": "Labor Force Participation",           "category": "Labor",      "region": "US",        "frequency": "m", "units": "%"},
    # ------------------------------------------------------------------
    # Inflation
    # ------------------------------------------------------------------
    {"series_id": "CPIAUCSL",          "name": "CPI (headline)",                      "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "CPILFESL",          "name": "CPI (core)",                          "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "PCEPI",             "name": "PCE Price Index (headline)",          "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "PCEPILFE",          "name": "PCE Price Index (core)",              "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "PPIFIS",            "name": "PPI Final Demand",                    "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "T10YIE",            "name": "10Y Breakeven Inflation",             "category": "Inflation",  "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "T5YIFR",            "name": "5Y5Y Forward Inflation Expectation",  "category": "Inflation",  "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "UMCSENT",           "name": "U. Michigan Consumer Sentiment",      "category": "Inflation",  "region": "US",        "frequency": "m", "units": "Index 1966=100"},
    # ------------------------------------------------------------------
    # Monetary policy / rates / liquidity
    # ------------------------------------------------------------------
    {"series_id": "DFF",               "name": "Fed Funds Effective Rate (daily)",    "category": "Policy",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "DFEDTARU",          "name": "Fed Target Range (upper)",            "category": "Policy",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "DFEDTARL",          "name": "Fed Target Range (lower)",            "category": "Policy",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "SOFR",              "name": "SOFR",                                "category": "Policy",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "DGS2",              "name": "2Y Treasury Yield (CMT)",             "category": "Rates",      "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "DGS10",             "name": "10Y Treasury Yield (CMT)",            "category": "Rates",      "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "DGS30",             "name": "30Y Treasury Yield (CMT)",            "category": "Rates",      "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "T10Y2Y",            "name": "10Y-2Y Spread",                       "category": "Rates",      "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "T10Y3M",            "name": "10Y-3M Spread",                       "category": "Rates",      "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "WALCL",             "name": "Fed Balance Sheet (total assets)",    "category": "Liquidity",  "region": "US",        "frequency": "w", "units": "Mil. $"},
    {"series_id": "M2SL",              "name": "M2 Money Supply",                     "category": "Liquidity",  "region": "US",        "frequency": "m", "units": "Bil. $"},
    {"series_id": "RRPONTSYD",         "name": "Overnight Reverse Repo",              "category": "Liquidity",  "region": "US",        "frequency": "d", "units": "Bil. $"},
    # ------------------------------------------------------------------
    # Credit / financial conditions
    # ------------------------------------------------------------------
    {"series_id": "BAMLH0A0HYM2",      "name": "High Yield OAS",                      "category": "Credit",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "BAMLC0A0CM",        "name": "Investment Grade OAS",                "category": "Credit",     "region": "US",        "frequency": "d", "units": "%"},
    {"series_id": "NFCI",              "name": "Chicago Fed Financial Conditions",    "category": "Credit",     "region": "US",        "frequency": "w", "units": "Index"},
    # ------------------------------------------------------------------
    # Housing
    # ------------------------------------------------------------------
    {"series_id": "HOUST",             "name": "Housing Starts",                      "category": "Housing",    "region": "US",        "frequency": "m", "units": "Thous. SAAR"},
    {"series_id": "PERMIT",            "name": "Building Permits",                    "category": "Housing",    "region": "US",        "frequency": "m", "units": "Thous. SAAR"},
    {"series_id": "CSUSHPINSA",        "name": "Case-Shiller Home Price Index",       "category": "Housing",    "region": "US",        "frequency": "m", "units": "Index"},
    {"series_id": "MORTGAGE30US",      "name": "30Y Mortgage Rate",                   "category": "Housing",    "region": "US",        "frequency": "w", "units": "%"},
    # ------------------------------------------------------------------
    # Consumer / fiscal / external
    # ------------------------------------------------------------------
    {"series_id": "PI",                "name": "Personal Income",                     "category": "Consumer",   "region": "US",        "frequency": "m", "units": "Bil. $ SAAR"},
    {"series_id": "PCE",               "name": "Personal Consumption Expenditures",   "category": "Consumer",   "region": "US",        "frequency": "m", "units": "Bil. $ SAAR"},
    {"series_id": "PSAVERT",           "name": "Personal Savings Rate",               "category": "Consumer",   "region": "US",        "frequency": "m", "units": "%"},
    {"series_id": "BOPGSTB",           "name": "Trade Balance (goods & services)",    "category": "External",   "region": "US",        "frequency": "m", "units": "Mil. $"},
    {"series_id": "GFDEBTN",           "name": "Federal Debt (total)",                "category": "Fiscal",     "region": "US",        "frequency": "q", "units": "Mil. $"},
    # ------------------------------------------------------------------
    # International. Eurostat/central-bank-sourced series are live; the
    # OECD MEI mirrors stopped updating after OECD's 2024 licensing change
    # and FRED has NO fresh monthly replacement (verified via the FRED
    # search API, 2026-07). The three marked STALE below are kept for
    # their history — the snapshot's last_date column shows the staleness.
    # For current Japan/UK CPI and Euro unemployment a non-FRED source
    # (Eurostat, ONS, e-Stat, or DBnomics) will be needed eventually.
    # ------------------------------------------------------------------
    {"series_id": "CLVMNACSCAB1GQEA19","name": "Euro Area Real GDP",                  "category": "Intl",       "region": "Euro Area", "frequency": "q", "units": "Mil. chn 2010 EUR"},
    {"series_id": "CP0000EZ19M086NEST","name": "Euro Area HICP",                      "category": "Intl",       "region": "Euro Area", "frequency": "m", "units": "Index 2015=100"},
    {"series_id": "LRHUTTTTEZM156S",   "name": "EA Unemployment (STALE, ends 2023-01)","category": "Intl",      "region": "Euro Area", "frequency": "m", "units": "%"},
    {"series_id": "ECBDFR",            "name": "ECB Deposit Facility Rate",           "category": "Intl",       "region": "Euro Area", "frequency": "d", "units": "%"},
    {"series_id": "GBRCPIALLMINMEI",   "name": "UK CPI (STALE, ends 2025-03)",        "category": "Intl",       "region": "UK",        "frequency": "m", "units": "Index 2015=100"},
    {"series_id": "JPNCPIALLMINMEI",   "name": "Japan CPI (STALE, ends 2021-06)",     "category": "Intl",       "region": "Japan",     "frequency": "m", "units": "Index 2015=100"},
    {"series_id": "IRLTLT01DEM156N",   "name": "Germany 10Y Yield",                   "category": "Intl",       "region": "Germany",   "frequency": "m", "units": "%"},
]
