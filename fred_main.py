"""Entry point: fetch the FRED macro universe, save pickles, print a summary.

Parallel to main.py (Yahoo Finance prices) — run either independently.

Usage:
    pip install requests pandas
    python fred_main.py

Requires a FRED API key in the FRED_API_KEY environment variable or in a
local .env file (FRED_API_KEY=<key>). Get one free at
https://fred.stlouisfed.org/docs/api/api_key.html

Outputs (native pandas pickles, no CSV/JSON/parquet):
    fred_snapshot.pkl  — one row per series, dashboard-ready snapshot
    fred_history.pkl   — tidy long history at each series' native frequency
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from fred_config import SERIES
from fred_fetch import fetch_all_fred

SNAPSHOT_PATH = "fred_snapshot.pkl"
HISTORY_PATH = "fred_history.pkl"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_summary(snapshot_df: pd.DataFrame, failed: list[str], total: int) -> None:
    """Human-readable summary — the only place we use print()."""
    succeeded = total - len(failed)

    print()
    print("=" * 120)
    print("FRED MACRO DATA — FETCH SUMMARY")
    print("=" * 120)
    print(f"Series requested : {total}")
    print(f"Succeeded        : {succeeded}")
    print(f"Failed           : {len(failed)}"
          + (f"  ({', '.join(failed)})" if failed else ""))
    print(f"Saved            : {SNAPSHOT_PATH} ({len(snapshot_df)} rows), "
          f"{HISTORY_PATH}")
    print("-" * 120)

    if snapshot_df.empty:
        print("Snapshot is empty — nothing to display.")
        return

    # Full snapshot table, sorted by category (then series for stable order).
    table = snapshot_df.sort_values(["category", "series_id"]).reset_index(drop=True)
    table = table.assign(last_date=table["last_date"].dt.strftime("%Y-%m-%d"))
    display_cols = [
        "series_id", "name", "category", "region", "frequency",
        "last", "prev", "chg", "yoy_chg", "yoy_pct", "last_date", "units",
    ]
    with pd.option_context(
        "display.max_rows", None,
        "display.max_columns", None,
        "display.width", None,
        "display.float_format", lambda v: f"{v:,.2f}",
    ):
        print(table[display_cols].to_string(index=False))
    print("=" * 120)

    # Staleness check: flag series whose latest observation is suspiciously
    # old for its frequency (e.g. discontinued OECD mirrors). Informational
    # only — the data is kept, the reader decides.
    stale_days = {"daily": 14, "weekly": 30, "monthly": 75, "quarterly": 200}
    now = snapshot_df["as_of_utc"].iloc[0].replace(tzinfo=None)
    age = (now - snapshot_df["last_date"]).dt.days
    limits = snapshot_df["frequency"].map(stale_days)
    stale = snapshot_df[age > limits]
    if not stale.empty:
        print("NOTE — series with unusually old latest observations "
              "(possibly discontinued or heavily lagged):")
        for _, row in stale.iterrows():
            print(f"  {row['series_id']:<22} {row['name']:<42} "
                  f"last obs {row['last_date'].date()} ({row['frequency']})")
        print("=" * 120)


def main() -> int:
    _configure_logging()
    log = logging.getLogger("fred_main")

    try:
        snapshot_df, history_df, failed = fetch_all_fred(SERIES)
    except Exception:
        # Missing API key or another setup-level failure — individual bad
        # series are handled inside fetch_all_fred and never land here.
        log.exception("Fatal: could not fetch FRED data.")
        return 1

    snapshot_df.to_pickle(SNAPSHOT_PATH)
    history_df.to_pickle(HISTORY_PATH)
    log.info("Wrote %s and %s.", SNAPSHOT_PATH, HISTORY_PATH)

    _print_summary(snapshot_df, failed, total=len(SERIES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
