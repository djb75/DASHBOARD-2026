"""Entry point: fetch macro headlines from Alpha Vantage, save a pickle.

Parallel to fred_main.py (FRED) / main.py (Yahoo Finance) — run independently.

Usage:
    pip install requests pandas
    python news_main.py

Requires an Alpha Vantage API key in the ALPHAVANTAGE_API_KEY environment
variable or in a local .env file (ALPHAVANTAGE_API_KEY=<key>). Get one free
at https://www.alphavantage.co/support/#api-key.

Output (native pandas pickle, no CSV/JSON/parquet):
    news.pkl — latest macro headlines, newest first
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from news_fetch import fetch_news, get_api_key

NEWS_PATH = "news.pkl"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_summary(news_df: pd.DataFrame) -> None:
    """Human-readable summary — the only place we use print()."""
    print()
    print("=" * 100)
    print("MACRO NEWS — FETCH SUMMARY")
    print("=" * 100)
    print(f"Headlines fetched : {len(news_df)}")
    print(f"Saved             : {NEWS_PATH}")
    print("-" * 100)

    if news_df.empty:
        print("No headlines returned.")
        return

    for _, row in news_df.head(20).iterrows():
        ts = row["time_published"].strftime("%Y-%m-%d %H:%M")
        sentiment = row.get("overall_sentiment_label", "")
        print(f"  [{ts}] ({sentiment:<18}) {row['source']:<20} {row['title']}")
    print("=" * 100)


def main() -> int:
    _configure_logging()
    log = logging.getLogger("news_main")

    try:
        api_key = get_api_key()
        news_df = fetch_news(api_key)
    except Exception:
        log.exception("Fatal: could not fetch news.")
        return 1

    news_df.to_pickle(NEWS_PATH)
    log.info("Wrote %s (%d headlines).", NEWS_PATH, len(news_df))

    _print_summary(news_df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
