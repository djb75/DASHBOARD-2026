"""Loads cached macro headlines (news.pkl) for the dashboard's news ticker.

Parallel to dashboard_data.py. news.pkl is produced by news_main.py
(Alpha Vantage News & Sentiment API) and is optional — the dashboard
must still work before it's ever been fetched.
"""

import pandas as pd
import streamlit as st

NEWS_PATH = "news.pkl"

_EMPTY_COLUMNS = [
    "title", "url", "time_published", "source",
    "overall_sentiment_label", "overall_sentiment_score", "summary",
]


@st.cache_data(ttl=300)
def load_news() -> pd.DataFrame:
    """Return cached headlines, newest first, or an empty frame if none yet."""
    try:
        df = pd.read_pickle(NEWS_PATH)
    except (FileNotFoundError, OSError):
        return pd.DataFrame(columns=_EMPTY_COLUMNS)

    if df.empty:
        return df

    return df.sort_values("time_published", ascending=False).reset_index(drop=True)
