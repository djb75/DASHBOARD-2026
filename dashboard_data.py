"""Loads and combines the Yahoo Finance and FRED macro pkl files into one
long-format table, and defines how series are grouped into dashboard tabs.
"""

import pandas as pd
import streamlit as st

YAHOO_HISTORY_PATH = "history.pkl"
FRED_HISTORY_PATH = "fred_history.pkl"

# Tab label -> list of `category` values (as tagged in the source pkl files)
# to include in that tab. No category name collides between Yahoo and FRED.
TAB_CONFIG = {
    "Rates & Policy": ["Rate", "Rates", "Policy"],
    "Inflation": ["Inflation"],
    "Growth & Labor": ["Growth", "Labor"],
    "Credit Spreads": ["Credit", "Bond ETF"],
    "Equities & Volatility": ["Equity Index", "Equity Future", "Volatility"],
    "FX & Commodities": ["FX", "Commodity Future", "Commodity ETF", "Crypto"],
    "Housing": ["Housing"],
    "Liquidity & Fiscal": ["Liquidity", "Fiscal"],
    "Consumer": ["Consumer"],
    "International": ["Intl", "External"],
}


@st.cache_data
def load_data() -> pd.DataFrame:
    """Return one long-format DataFrame combining Yahoo + FRED history.

    Columns: series_id, date, value, open, high, low, name, category,
    source, frequency, units. FRED rows have no OHLC (open/high/low = NaN)
    since FRED only publishes single observations, not trading ranges.
    """
    yahoo = pd.read_pickle(YAHOO_HISTORY_PATH)
    yahoo = yahoo.assign(
        series_id=yahoo["ticker"],
        value=yahoo["close"],
        source="Yahoo Finance",
        frequency="d",
        units="",
    )

    fred = pd.read_pickle(FRED_HISTORY_PATH)
    fred = fred.assign(source="FRED", open=pd.NA, high=pd.NA, low=pd.NA)

    cols = [
        "series_id", "date", "value", "open", "high", "low",
        "name", "category", "source", "frequency", "units",
    ]
    combined = pd.concat([yahoo[cols], fred[cols]], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.dropna(subset=["value"])
    combined = combined.sort_values(["category", "series_id", "date"])
    return combined
