"""Fetching and reshaping of macro market data from Yahoo Finance.

Public entry point is :func:`fetch_all`, which:

1. Downloads 1y of daily bars for the whole universe in ONE batched
   ``yf.download`` call (with retry/backoff) — never one call per ticker,
   because Yahoo rate-limits aggressively (429 / YFRateLimitError).
2. Reshapes the MultiIndex result into a tidy long ``history_df``.
3. Builds a one-row-per-ticker ``snapshot_df`` with last price, daily
   change, and 1w / 1m / YTD returns.

SSL note: this module deliberately does NOT touch SSL configuration.
Modern yfinance uses curl_cffi (libcurl) under the hood, which honours the
CURL_CA_BUNDLE / SSL_CERT_FILE environment variables — corporate-proxy CA
bundles must be supplied through those. We only WARN if neither is set.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from typing import Iterable
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Yahoo field name -> tidy lower-case column name
_FIELD_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}

# Yield tickers Yahoo reports inconsistently (sometimes x1, sometimes x10).
_YIELD_TICKERS = {"^TNX", "^TYX", "^FVX", "^IRX"}
_YIELD_PLAUSIBLE_RANGE = (0.0, 20.0)  # percent

# Trading-day lookbacks for period returns (approximate calendar 1w / 1m).
_LOOKBACK_1W = 5
_LOOKBACK_1M = 21

_RETRY_DELAYS_S = (2, 4, 8)  # exponential backoff between batch retries

# Static quote-currency map. yf.download returns no currency metadata, and
# querying it per ticker (fast_info/info) would mean ~55 extra HTTP calls —
# exactly the per-ticker hammering that triggers Yahoo's rate limiter. The
# universe is fixed in config.py, so a static map is the robust choice.
# Anything not listed defaults to USD (all US assets, commodities, crypto).
_CURRENCY_MAP = {
    # European indices
    "^FTSE": "GBP", "^GDAXI": "EUR", "^FCHI": "EUR",
    "^STOXX50E": "EUR", "FTSEMIB.MI": "EUR",
    # Asia / EM indices
    "^N225": "JPY", "^HSI": "HKD", "000001.SS": "CNY", "^NSEI": "INR",
    "^AXJO": "AUD", "^KS11": "KRW", "^BVSP": "BRL",
    # FX pairs -> quote currency (price is expressed in this currency)
    "EURUSD=X": "USD", "GBPUSD=X": "USD", "AUDUSD=X": "USD",
    "USDJPY=X": "JPY", "USDCHF=X": "CHF", "USDCAD=X": "CAD",
    "USDCNY=X": "CNY", "USDMXN=X": "MXN",
    # Pure numbers (index points / percent) rather than a currency
    "^VIX": "PTS", "DX-Y.NYB": "PTS",
    "^TNX": "%", "^TYX": "%", "^FVX": "%", "^IRX": "%",
}
_DEFAULT_CURRENCY = "USD"


# ---------------------------------------------------------------------------
# Environment sanity check
# ---------------------------------------------------------------------------

def check_ssl_env() -> None:
    """Warn if no CA-bundle env var is set (likely cert error behind a proxy).

    We never modify SSL settings ourselves; the caller owns the CA bundle
    via CURL_CA_BUNDLE / SSL_CERT_FILE (honoured by curl_cffi / libcurl).
    """
    if not os.environ.get("CURL_CA_BUNDLE") and not os.environ.get("SSL_CERT_FILE"):
        logger.warning(
            "Neither CURL_CA_BUNDLE nor SSL_CERT_FILE is set. Behind an "
            "HTTPS-intercepting proxy this will likely cause an SSL "
            "certificate verification error — point one of them at your "
            "corporate CA .pem before running."
        )


# ---------------------------------------------------------------------------
# Download with retry
# ---------------------------------------------------------------------------

def download_history(tickers: list[str]) -> pd.DataFrame:
    """One batched ``yf.download`` for the whole universe, with retries.

    Retries up to len(_RETRY_DELAYS_S) times with exponential backoff
    (2s, 4s, 8s) if the batch call raises or comes back completely empty.
    Raises RuntimeError only if every attempt fails — individual bad
    tickers do NOT raise (they just come back as all-NaN columns and are
    filtered downstream).
    """
    last_exc: Exception | None = None
    attempts = len(_RETRY_DELAYS_S) + 1  # initial try + retries

    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Downloading %d tickers (attempt %d/%d)...",
                len(tickers), attempt, attempts,
            )
            raw = yf.download(
                tickers,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
            if raw is None or raw.empty:
                # Treat a fully-empty batch (e.g. rate-limited) as a failure
                # worth retrying, rather than silently returning nothing.
                raise RuntimeError("yf.download returned an empty frame")
            logger.info("Batch download OK: %d rows of raw data.", len(raw))
            return raw
        except Exception as exc:  # noqa: BLE001 - deliberate broad net around I/O
            last_exc = exc
            if attempt <= len(_RETRY_DELAYS_S):
                delay = _RETRY_DELAYS_S[attempt - 1]
                logger.warning(
                    "Batch download failed (%s: %s). Retrying in %ds...",
                    type(exc).__name__, exc, delay,
                )
                time.sleep(delay)

    raise RuntimeError(f"Batch download failed after {attempts} attempts") from last_exc


# ---------------------------------------------------------------------------
# Reshape: MultiIndex -> tidy long
# ---------------------------------------------------------------------------

def reshape_history(raw: pd.DataFrame, tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Turn the wide MultiIndex download into a tidy long frame.

    With ``group_by="ticker"`` the raw columns are a 2-level MultiIndex of
    (ticker, field). We slice out each ticker's sub-frame, drop rows where
    every field is NaN (Yahoo pads all tickers onto a shared date index, so
    a Tokyo holiday shows up as a NaN row under ^N225), and stack the
    survivors into long format.

    Returns (history_df, failed_tickers). Tickers with no usable data are
    logged as WARNING and skipped — they never abort the run.
    """
    frames: list[pd.DataFrame] = []
    failed: list[str] = []

    # Defensive: if only one ticker survives, yfinance can return flat
    # (single-level) columns instead of a MultiIndex. Normalise that case.
    if not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1)

    available = set(raw.columns.get_level_values(0))

    for ticker in tickers:
        if ticker not in available:
            logger.warning("No data returned for %s — skipping.", ticker)
            failed.append(ticker)
            continue

        sub = raw[ticker].copy()
        # Keep only the OHLCV fields we care about (ignore Adj Close etc.).
        keep = [c for c in _FIELD_MAP if c in sub.columns]
        sub = sub[keep].rename(columns=_FIELD_MAP)
        # Rows that are entirely NaN are dates where this ticker didn't trade.
        sub = sub.dropna(how="all")

        if sub.empty or sub["close"].dropna().empty:
            logger.warning("Empty/all-NaN history for %s — skipping.", ticker)
            failed.append(ticker)
            continue

        sub = sub.reset_index()
        # The index column name varies ("Date" vs "Datetime"); normalise it.
        sub = sub.rename(columns={sub.columns[0]: "date"})
        sub["date"] = pd.to_datetime(sub["date"])
        sub.insert(0, "ticker", ticker)
        frames.append(sub[["ticker", "date", "open", "high", "low", "close", "volume"]])

    if not frames:
        return (
            pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"]),
            failed,
        )

    history_df = pd.concat(frames, ignore_index=True)
    history_df = history_df.sort_values(["ticker", "date"]).reset_index(drop=True)
    return history_df, failed


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------

def _pct_return(closes: pd.Series, periods_back: int) -> float:
    """% return from ``periods_back`` trading days ago to the latest close."""
    if len(closes) <= periods_back:
        return float("nan")
    base = closes.iloc[-1 - periods_back]
    if pd.isna(base) or base == 0:
        return float("nan")
    return (closes.iloc[-1] / base - 1.0) * 100.0


def _ytd_return(sub: pd.DataFrame, now_utc: dt.datetime) -> float:
    """% return vs the first available close of the current calendar year."""
    this_year = sub[sub["date"].dt.year == now_utc.year]
    if this_year.empty:
        return float("nan")
    base = this_year["close"].iloc[0]
    last = sub["close"].iloc[-1]
    if pd.isna(base) or base == 0 or pd.isna(last):
        return float("nan")
    return (last / base - 1.0) * 100.0


def build_snapshot(
    history_df: pd.DataFrame,
    instruments: list[dict],
    as_of_utc: dt.datetime,
) -> pd.DataFrame:
    """One row per ticker with last/prev close, daily change, and returns."""
    meta = {inst["ticker"]: inst for inst in instruments}
    rows: list[dict] = []

    for ticker, sub in history_df.groupby("ticker", sort=False):
        sub = sub.sort_values("date")
        # Use only bars with a real close for price-based fields; the raw
        # padded rows are already gone but a stray NaN close is still possible.
        priced = sub.dropna(subset=["close"])
        if priced.empty:
            logger.warning("No priced bars for %s — excluded from snapshot.", ticker)
            continue

        closes = priced["close"]
        last = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else float("nan")
        chg = last - prev_close if pd.notna(prev_close) else float("nan")
        chg_pct = (chg / prev_close * 100.0) if pd.notna(prev_close) and prev_close != 0 else float("nan")

        latest_bar = priced.iloc[-1]
        info = meta.get(ticker, {})

        # Yahoo's yield tickers (^TNX etc.) are usually the yield x10... or
        # not — the scale flips between x1 and x10 depending on the day/feed.
        # We can't silently "fix" it without risking corrupting good data,
        # so we sanity-check and WARN instead.
        if ticker in _YIELD_TICKERS:
            lo, hi = _YIELD_PLAUSIBLE_RANGE
            if not (lo <= last <= hi):
                logger.warning(
                    "%s last value %.2f is outside the plausible yield range "
                    "%s–%s%% — Yahoo may be reporting it x10 (or otherwise "
                    "mis-scaled). Verify before using downstream.",
                    ticker, last, lo, hi,
                )

        rows.append({
            "ticker": ticker,
            "name": info.get("name", ticker),
            "category": info.get("category", "Unknown"),
            "region": info.get("region", "Unknown"),
            "last": last,
            "prev_close": prev_close,
            "chg": chg,
            "chg_pct": chg_pct,
            "day_high": float(latest_bar["high"]) if pd.notna(latest_bar["high"]) else float("nan"),
            "day_low": float(latest_bar["low"]) if pd.notna(latest_bar["low"]) else float("nan"),
            "ret_1w": _pct_return(closes, _LOOKBACK_1W),
            "ret_1m": _pct_return(closes, _LOOKBACK_1M),
            "ret_ytd": _ytd_return(priced, as_of_utc),
            "currency": _CURRENCY_MAP.get(ticker, _DEFAULT_CURRENCY),
            "as_of_utc": as_of_utc,
        })

    columns = [
        "ticker", "name", "category", "region", "last", "prev_close",
        "chg", "chg_pct", "day_high", "day_low",
        "ret_1w", "ret_1m", "ret_ytd", "currency", "as_of_utc",
    ]
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_all(instruments: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Fetch everything and return (snapshot_df, history_df, failed_tickers)."""
    check_ssl_env()

    tickers = [inst["ticker"] for inst in instruments]
    as_of_utc = dt.datetime.now(dt.timezone.utc)  # single timestamp for all rows

    raw = download_history(tickers)
    history_df, failed = reshape_history(raw, tickers)

    # Merge config metadata into the history frame as well (snapshot gets it
    # directly inside build_snapshot).
    meta_df = pd.DataFrame(instruments)
    history_df = history_df.merge(meta_df, on="ticker", how="left")

    snapshot_df = build_snapshot(history_df, instruments, as_of_utc)

    logger.info(
        "Fetch complete: %d/%d tickers OK, %d failed.",
        len(tickers) - len(failed), len(tickers), len(failed),
    )
    return snapshot_df, history_df, failed
