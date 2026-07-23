"""Fetching macro news headlines from Alpha Vantage's News & Sentiment API.

Parallel to fred_fetch.py (FRED) / fetch.py (Yahoo Finance) — same .env /
retry conventions. Public entry point is :func:`fetch_news`.

Docs: https://www.alphavantage.co/documentation/#news-sentiment

The API key is read from the ALPHAVANTAGE_API_KEY environment variable, or
from a local ``.env`` file (KEY=VALUE lines) if the variable is not set.
Get a free key at https://www.alphavantage.co/support/#api-key.

Alpha Vantage signals rate-limiting / bad-key errors with an HTTP 200 and
a "Note"/"Information" JSON key instead of the usual "feed" key, so those
are treated as failures worth retrying rather than parsed as empty results.
"""

from __future__ import annotations

import logging
import os
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = "https://www.alphavantage.co/query"
_ENV_FILE = ".env"
_ENV_KEY = "ALPHAVANTAGE_API_KEY"

_RETRY_DELAYS_S = (5, 15, 30)  # free tier is rate-limited; back off harder than FRED
_REQUEST_TIMEOUT_S = 30

# Alpha Vantage's fixed topic taxonomy, restricted to the macro-relevant
# subset — deliberately excludes company-specific topics (earnings, ipo,
# technology, ...) since this feeds a macro dashboard, not a stock ticker.
NEWS_TOPICS = "economy_macro,economy_fiscal,economy_monetary,financial_markets"
NEWS_LIMIT = 50

_FEED_COLUMNS = [
    "title", "url", "time_published", "source",
    "overall_sentiment_label", "overall_sentiment_score", "summary",
]


# ---------------------------------------------------------------------------
# API key handling (.env) — identical convention to fred_fetch.py
# ---------------------------------------------------------------------------

def _load_dotenv(path: str = _ENV_FILE) -> None:
    """Minimal .env loader: KEY=VALUE lines, no dependency on python-dotenv.

    Real environment variables always win over the file.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def get_api_key() -> str:
    """Return the Alpha Vantage API key from the environment or .env, or raise."""
    _load_dotenv()
    key = os.environ.get(_ENV_KEY, "").strip()
    if not key:
        raise RuntimeError(
            f"No Alpha Vantage API key found. Set {_ENV_KEY} in the "
            f"environment or in a local {_ENV_FILE} file ({_ENV_KEY}=<your key>)."
        )
    return key


# ---------------------------------------------------------------------------
# Fetch with retry
# ---------------------------------------------------------------------------

def fetch_news(
    api_key: str,
    topics: str = NEWS_TOPICS,
    limit: int = NEWS_LIMIT,
    time_from: "pd.Timestamp | None" = None,
) -> pd.DataFrame:
    """Fetch macro headlines, with retry/backoff.

    If time_from is given, only headlines published after it are requested
    (Alpha Vantage's own server-side filter) — this is what makes repeated
    calls incremental instead of re-fetching the same ~50 latest items
    (many of them reposts/re-indexes of stories already seen) every time.

    Returns a frame with columns (title, url, time_published, source,
    overall_sentiment_label, overall_sentiment_score, summary), newest
    first. Raises RuntimeError only after all retries are exhausted.
    """
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": topics,
        "sort": "LATEST",
        "limit": str(limit),
        "apikey": api_key,
    }
    if time_from is not None:
        params["time_from"] = time_from.strftime("%Y%m%dT%H%M")
    last_exc: Exception | None = None
    attempts = len(_RETRY_DELAYS_S) + 1

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(_API_URL, params=params, timeout=_REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            payload = resp.json()

            if "feed" not in payload:
                # 200 OK but rate-limited / bad key / no results — Alpha
                # Vantage reports this via a "Note"/"Information"/
                # "Error Message" key instead of an HTTP error status.
                message = (
                    payload.get("Note")
                    or payload.get("Information")
                    or payload.get("Error Message")
                    or str(payload)
                )
                raise RuntimeError(f"Alpha Vantage did not return a feed: {message}")

            feed = payload["feed"]
            if not feed:
                return pd.DataFrame(columns=_FEED_COLUMNS)

            df = pd.DataFrame(feed)
            df["time_published"] = pd.to_datetime(
                df["time_published"], format="%Y%m%dT%H%M%S", errors="coerce"
            )
            keep = [c for c in _FEED_COLUMNS if c in df.columns]
            df = df[keep].dropna(subset=["time_published"])
            df = df.sort_values("time_published", ascending=False).reset_index(drop=True)
            return df
        except Exception as exc:  # noqa: BLE001 - deliberate broad net around I/O
            last_exc = exc
            if attempt <= len(_RETRY_DELAYS_S):
                delay = _RETRY_DELAYS_S[attempt - 1]
                logger.warning(
                    "News fetch failed (%s: %s). Retrying in %ds...",
                    type(exc).__name__, exc, delay,
                )
                time.sleep(delay)

    raise RuntimeError(f"News fetch failed after {attempts} attempts") from last_exc
