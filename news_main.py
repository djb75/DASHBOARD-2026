"""Entry point: fetch macro headlines from Alpha Vantage, save a pickle.

Parallel to fred_main.py (FRED) / main.py (Yahoo Finance) — run independently.

Usage:
    pip install requests pandas
    python news_main.py

Requires an Alpha Vantage API key in the ALPHAVANTAGE_API_KEY environment
variable or in a local .env file (ALPHAVANTAGE_API_KEY=<key>). Get one free
at https://www.alphavantage.co/support/#api-key.

Incremental: only asks Alpha Vantage for headlines newer than the latest one
already saved (via time_from), rather than re-requesting the same ~50
"latest" items on every run — the free tier's quota is scarce, and macro
news topics have low genuine volume, so re-fetching the same items repeatedly
was both wasteful and why the archive never grew past 50 items. New results
are appended to the existing archive rather than replacing it, deduped
(Alpha Vantage frequently re-indexes the same story across regional mirror
URLs — e.g. troweprice.com's /hk/, /sg/, /no/ editions of one article — so
dedup is by title, not just url), and capped at MAX_STORED_HEADLINES so the
file doesn't grow forever.

Output (native pandas pickle, no CSV/JSON/parquet):
    news.pkl — macro headlines, newest first
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from news_fetch import fetch_news, get_api_key

NEWS_PATH = "news.pkl"
MAX_STORED_HEADLINES = 500


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


def _load_existing() -> pd.DataFrame:
    try:
        return pd.read_pickle(NEWS_PATH)
    except (FileNotFoundError, OSError):
        return pd.DataFrame()


def main() -> int:
    _configure_logging()
    log = logging.getLogger("news_main")

    existing = _load_existing()
    time_from = None
    if not existing.empty:
        # A minute past our newest saved headline, so the request boundary
        # doesn't re-count the same latest article against the day's quota.
        time_from = existing["time_published"].max() + pd.Timedelta(minutes=1)

    try:
        api_key = get_api_key()
        fetched_df = fetch_news(api_key, time_from=time_from)
    except Exception:
        log.exception("Fatal: could not fetch news.")
        return 1

    combined = pd.concat([fetched_df, existing], ignore_index=True)
    combined = combined.drop_duplicates(subset="url", keep="first")
    combined = combined.drop_duplicates(subset="title", keep="first")
    combined = combined.sort_values("time_published", ascending=False).reset_index(drop=True)
    combined = combined.head(MAX_STORED_HEADLINES)

    combined.to_pickle(NEWS_PATH)
    log.info(
        "Wrote %s (%d newly fetched, %d total after dedupe/cap).",
        NEWS_PATH, len(fetched_df), len(combined),
    )

    _print_summary(combined)
    return 0


if __name__ == "__main__":
    sys.exit(main())
