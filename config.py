"""Instrument universe for the macro market data scraper.

Each entry defines a Yahoo Finance ticker plus display metadata
(name / category / region) that gets merged into both output frames.
"""

INSTRUMENTS = [
    # Equity index futures (overnight / pre-market read)
    {"ticker": "ES=F",       "name": "S&P 500 E-mini Future",             "category": "Equity Future",   "region": "US"},
    {"ticker": "NQ=F",       "name": "Nasdaq 100 E-mini Future",          "category": "Equity Future",   "region": "US"},
    {"ticker": "YM=F",       "name": "Dow E-mini Future",                 "category": "Equity Future",   "region": "US"},
    {"ticker": "RTY=F",      "name": "Russell 2000 E-mini Future",        "category": "Equity Future",   "region": "US"},
    # US cash indices
    {"ticker": "^GSPC",      "name": "S&P 500",                           "category": "Equity Index",    "region": "US"},
    {"ticker": "^IXIC",      "name": "Nasdaq Composite",                  "category": "Equity Index",    "region": "US"},
    {"ticker": "^DJI",       "name": "Dow Jones Industrial Average",      "category": "Equity Index",    "region": "US"},
    {"ticker": "^RUT",       "name": "Russell 2000",                      "category": "Equity Index",    "region": "US"},
    # Europe
    {"ticker": "^FTSE",      "name": "FTSE 100",                          "category": "Equity Index",    "region": "UK"},
    {"ticker": "^GDAXI",     "name": "DAX",                               "category": "Equity Index",    "region": "Germany"},
    {"ticker": "^FCHI",      "name": "CAC 40",                            "category": "Equity Index",    "region": "France"},
    {"ticker": "^STOXX50E",  "name": "Euro Stoxx 50",                     "category": "Equity Index",    "region": "Europe"},
    {"ticker": "FTSEMIB.MI", "name": "FTSE MIB",                          "category": "Equity Index",    "region": "Italy"},
    # Asia / EM
    {"ticker": "^N225",      "name": "Nikkei 225",                        "category": "Equity Index",    "region": "Japan"},
    {"ticker": "^HSI",       "name": "Hang Seng",                         "category": "Equity Index",    "region": "Hong Kong"},
    {"ticker": "000001.SS",  "name": "Shanghai Composite",                "category": "Equity Index",    "region": "China"},
    {"ticker": "^NSEI",      "name": "Nifty 50",                          "category": "Equity Index",    "region": "India"},
    {"ticker": "^AXJO",      "name": "ASX 200",                           "category": "Equity Index",    "region": "Australia"},
    {"ticker": "^KS11",      "name": "KOSPI",                             "category": "Equity Index",    "region": "South Korea"},
    {"ticker": "^BVSP",      "name": "Bovespa",                           "category": "Equity Index",    "region": "Brazil"},
    # Volatility
    {"ticker": "^VIX",       "name": "CBOE Volatility Index",             "category": "Volatility",      "region": "US"},
    # FX (DXY + majors + EM)
    {"ticker": "DX-Y.NYB",   "name": "US Dollar Index (DXY)",             "category": "FX",              "region": "US"},
    {"ticker": "EURUSD=X",   "name": "EUR/USD",                           "category": "FX",              "region": "Global"},
    {"ticker": "GBPUSD=X",   "name": "GBP/USD",                           "category": "FX",              "region": "Global"},
    {"ticker": "USDJPY=X",   "name": "USD/JPY",                           "category": "FX",              "region": "Global"},
    {"ticker": "USDCHF=X",   "name": "USD/CHF",                           "category": "FX",              "region": "Global"},
    {"ticker": "AUDUSD=X",   "name": "AUD/USD",                           "category": "FX",              "region": "Global"},
    {"ticker": "USDCAD=X",   "name": "USD/CAD",                           "category": "FX",              "region": "Global"},
    {"ticker": "USDCNY=X",   "name": "USD/CNY",                           "category": "FX",              "region": "Global"},
    {"ticker": "USDMXN=X",   "name": "USD/MXN",                           "category": "FX",              "region": "Global"},
    # Rates (yields)
    {"ticker": "^TNX",       "name": "US 10Y Treasury Yield",            "category": "Rate",            "region": "US"},
    {"ticker": "^TYX",       "name": "US 30Y Treasury Yield",            "category": "Rate",            "region": "US"},
    {"ticker": "^FVX",       "name": "US 5Y Treasury Yield",             "category": "Rate",            "region": "US"},
    {"ticker": "^IRX",       "name": "US 13-Week T-Bill Yield",          "category": "Rate",            "region": "US"},
    # Bond / credit ETFs
    {"ticker": "TLT",        "name": "iShares 20+ Year Treasury ETF",     "category": "Bond ETF",        "region": "US"},
    {"ticker": "IEF",        "name": "iShares 7-10 Year Treasury ETF",    "category": "Bond ETF",        "region": "US"},
    {"ticker": "HYG",        "name": "iShares High Yield Corp Bond ETF",  "category": "Bond ETF",        "region": "US"},
    {"ticker": "LQD",        "name": "iShares IG Corp Bond ETF",          "category": "Bond ETF",        "region": "US"},
    {"ticker": "TIP",        "name": "iShares TIPS Bond ETF",             "category": "Bond ETF",        "region": "US"},
    # Commodity futures
    {"ticker": "GC=F",       "name": "Gold Future",                       "category": "Commodity Future","region": "Global"},
    {"ticker": "SI=F",       "name": "Silver Future",                     "category": "Commodity Future","region": "Global"},
    {"ticker": "HG=F",       "name": "Copper Future",                     "category": "Commodity Future","region": "Global"},
    {"ticker": "CL=F",       "name": "WTI Crude Oil Future",              "category": "Commodity Future","region": "Global"},
    {"ticker": "BZ=F",       "name": "Brent Crude Oil Future",           "category": "Commodity Future","region": "Global"},
    {"ticker": "NG=F",       "name": "Natural Gas Future",                "category": "Commodity Future","region": "Global"},
    {"ticker": "ZC=F",       "name": "Corn Future",                       "category": "Commodity Future","region": "Global"},
    {"ticker": "ZW=F",       "name": "Wheat Future",                      "category": "Commodity Future","region": "Global"},
    {"ticker": "ZS=F",       "name": "Soybean Future",                    "category": "Commodity Future","region": "Global"},
    {"ticker": "KC=F",       "name": "Coffee Future",                     "category": "Commodity Future","region": "Global"},
    {"ticker": "CC=F",       "name": "Cocoa Future",                      "category": "Commodity Future","region": "Global"},
    {"ticker": "SB=F",       "name": "Sugar Future",                      "category": "Commodity Future","region": "Global"},
    # Broad commodity / crypto
    {"ticker": "DBC",        "name": "Invesco DB Commodity Index ETF",    "category": "Commodity ETF",   "region": "Global"},
    {"ticker": "BTC-USD",    "name": "Bitcoin",                           "category": "Crypto",          "region": "Global"},
    {"ticker": "ETH-USD",    "name": "Ethereum",                          "category": "Crypto",          "region": "Global"},
]
