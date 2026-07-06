"""Fetching and reshaping of macro economic data from the FRED API.

Parallel to fetch.py (Yahoo Finance prices). Public entry point is
:func:`fetch_all_fred`, which:

1. Downloads each series' observations from the FRED REST API. Unlike
   Yahoo, FRED serves ONE series per request (``fred/series/observations``),
   so this loops with a small throttle delay — the official limit is 120
   requests/minute, so ~50 series stays far inside it.
2. Requests history at each series' NATIVE frequency (no aggregation
   parameter), with a lookback window scaled to that frequency: daily
   series need less calendar history than quarterly ones to give the
   same amount of trend context.
3. Stacks everything into a tidy long ``history_df`` and builds a
   one-row-per-series ``snapshot_df`` with the latest value, previous
   value, change, and year-over-year change.

The API key is read from the FRED_API_KEY environment variable, or from
a local ``.env`` file (KEY=VALUE lines) if the variable is not set.

Macro series get REVISED, so every run re-fetches the full lookback
window rather than appending — the pickles are always a clean rebuild.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = "https://api.stlouisfed.org/fred/series/observations"
_ENV_FILE = ".env"
_ENV_KEY = "FRED_API_KEY"

_RETRY_DELAYS_S = (2, 4, 8)   # exponential backoff, same policy as fetch.py
_THROTTLE_S = 0.5             # delay between series requests (120 req/min cap)
_REQUEST_TIMEOUT_S = 30

# Calendar-years of history requested per native frequency. Scaled so each
# frequency yields a comparable number of observations for trend context
# (5y daily ~ 1250 obs, 30y quarterly ~ 120 obs).
_LOOKBACK_YEARS = {"d": 5, "w": 10, "m": 15, "q": 30}

# Periods in one year at each native frequency — used for the previous-
# period comparison; YoY itself is computed by calendar date, not offset.
_FREQ_LABEL = {"d": "daily", "w": "weekly", "m": "monthly", "q": "quarterly"}


# ---------------------------------------------------------------------------
# API key handling (.env)
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
    """Return the FRED API key from the environment or .env, or raise."""
    _load_dotenv()
    key = os.environ.get(_ENV_KEY, "").strip()
    if not key:
        raise RuntimeError(
            f"No FRED API key found. Set {_ENV_KEY} in the environment or "
            f"in a local {_ENV_FILE} file ({_ENV_KEY}=<your key>)."
        )
    return key


# ---------------------------------------------------------------------------
# Per-series download with retry
# ---------------------------------------------------------------------------

def _observation_start(frequency: str, as_of: dt.date) -> str:
    """ISO start date for the lookback window of the given frequency."""
    years = _LOOKBACK_YEARS.get(frequency, 10)
    return (pd.Timestamp(as_of) - pd.DateOffset(years=years)).date().isoformat()


def fetch_series(series_id: str, api_key: str, observation_start: str) -> pd.DataFrame:
    """Fetch one series' observations, with retry/backoff.

    Returns a frame with columns (date, value); FRED's "." placeholder for
    missing observations is dropped. Raises RuntimeError only after all
    retries are exhausted — the caller decides whether that aborts the run.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
    }
    last_exc: Exception | None = None
    attempts = len(_RETRY_DELAYS_S) + 1

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(_API_URL, params=params, timeout=_REQUEST_TIMEOUT_S)
            if resp.status_code == 429:
                raise RuntimeError("FRED rate limit hit (HTTP 429)")
            resp.raise_for_status()
            observations = resp.json().get("observations", [])

            df = pd.DataFrame(observations, columns=["date", "value"])
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "." -> NaN
            df = df.dropna(subset=["value"]).reset_index(drop=True)
            return df
        except Exception as exc:  # noqa: BLE001 - deliberate broad net around I/O
            last_exc = exc
            if attempt <= len(_RETRY_DELAYS_S):
                delay = _RETRY_DELAYS_S[attempt - 1]
                logger.warning(
                    "%s: request failed (%s: %s). Retrying in %ds...",
                    series_id, type(exc).__name__, exc, delay,
                )
                time.sleep(delay)

    raise RuntimeError(
        f"{series_id}: download failed after {attempts} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------

def _yoy(sub: pd.DataFrame) -> tuple[float, float]:
    """(yoy_chg, yoy_pct) vs the last observation at least one year back.

    Computed by calendar date rather than a fixed period offset so it works
    identically for daily, weekly, monthly, and quarterly series.
    yoy_pct is NaN when the base is <= 0 (percent change is meaningless for
    series that cross zero, e.g. curve spreads or the trade balance).
    """
    last_date = sub["date"].iloc[-1]
    last = sub["value"].iloc[-1]
    base_rows = sub[sub["date"] <= last_date - pd.DateOffset(years=1)]
    if base_rows.empty:
        return float("nan"), float("nan")
    base = base_rows["value"].iloc[-1]
    yoy_chg = last - base
    yoy_pct = (last / base - 1.0) * 100.0 if base > 0 else float("nan")
    return float(yoy_chg), float(yoy_pct)


def build_fred_snapshot(
    history_df: pd.DataFrame,
    series_list: list[dict],
    as_of_utc: dt.datetime,
) -> pd.DataFrame:
    """One row per series: latest value, previous value, change, YoY.

    ``chg`` is in the series' native units (percentage POINTS for series
    already quoted in %). ``chg_pct``/``yoy_pct`` are NaN when the base
    value is <= 0, for the same reason as in :func:`_yoy`.
    """
    meta = {s["series_id"]: s for s in series_list}
    rows: list[dict] = []

    for series_id, sub in history_df.groupby("series_id", sort=False):
        sub = sub.sort_values("date").reset_index(drop=True)
        if sub.empty:
            continue

        last = float(sub["value"].iloc[-1])
        prev = float(sub["value"].iloc[-2]) if len(sub) >= 2 else float("nan")
        chg = last - prev if pd.notna(prev) else float("nan")
        chg_pct = (chg / prev * 100.0) if pd.notna(prev) and prev > 0 else float("nan")
        yoy_chg, yoy_pct = _yoy(sub)

        info = meta.get(series_id, {})
        rows.append({
            "series_id": series_id,
            "name": info.get("name", series_id),
            "category": info.get("category", "Unknown"),
            "region": info.get("region", "Unknown"),
            "frequency": _FREQ_LABEL.get(info.get("frequency", ""), "unknown"),
            "units": info.get("units", ""),
            "last": last,
            "prev": prev,
            "chg": chg,
            "chg_pct": chg_pct,
            "yoy_chg": yoy_chg,
            "yoy_pct": yoy_pct,
            "last_date": sub["date"].iloc[-1],
            "as_of_utc": as_of_utc,
        })

    columns = [
        "series_id", "name", "category", "region", "frequency", "units",
        "last", "prev", "chg", "chg_pct", "yoy_chg", "yoy_pct",
        "last_date", "as_of_utc",
    ]
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_all_fred(series_list: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Fetch every configured series; return (snapshot_df, history_df, failed).

    Individual series failures (bad id, discontinued, API hiccup after all
    retries) are logged as WARNING and collected into ``failed`` — they
    never abort the run. Raises only if the API key is missing.
    """
    api_key = get_api_key()
    as_of_utc = dt.datetime.now(dt.timezone.utc)  # single timestamp for all rows

    frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for i, spec in enumerate(series_list):
        series_id = spec["series_id"]
        start = _observation_start(spec["frequency"], as_of_utc.date())
        logger.info(
            "Fetching %s (%d/%d, %s from %s)...",
            series_id, i + 1, len(series_list),
            _FREQ_LABEL.get(spec["frequency"], "?"), start,
        )
        try:
            df = fetch_series(series_id, api_key, start)
        except RuntimeError as exc:
            logger.warning("%s — skipping.", exc)
            failed.append(series_id)
            continue

        if df.empty:
            logger.warning("%s: no observations in window — skipping.", series_id)
            failed.append(series_id)
            continue

        df.insert(0, "series_id", series_id)
        frames.append(df)

        if i < len(series_list) - 1:
            time.sleep(_THROTTLE_S)

    if frames:
        history_df = pd.concat(frames, ignore_index=True)
        history_df = history_df.sort_values(["series_id", "date"]).reset_index(drop=True)
    else:
        history_df = pd.DataFrame(columns=["series_id", "date", "value"])

    # Merge config metadata into the history frame as well (snapshot gets it
    # directly inside build_fred_snapshot) — same pattern as fetch.fetch_all.
    meta_df = pd.DataFrame(series_list)
    history_df = history_df.merge(meta_df, on="series_id", how="left")

    snapshot_df = build_fred_snapshot(history_df, series_list, as_of_utc)

    logger.info(
        "FRED fetch complete: %d/%d series OK, %d failed.",
        len(series_list) - len(failed), len(series_list), len(failed),
    )
    return snapshot_df, history_df, failed
