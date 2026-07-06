"""Entry point: fetch the macro universe, save pickles, print a summary.

Usage:
    pip install yfinance pandas
    python main.py

Outputs (native pandas pickles, no CSV/JSON/parquet):
    snapshot.pkl  — one row per ticker, dashboard-ready snapshot
    history.pkl   — tidy long 1y daily OHLCV history
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from config import INSTRUMENTS
from fetch import fetch_all

SNAPSHOT_PATH = "snapshot.pkl"
HISTORY_PATH = "history.pkl"


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
    print("=" * 100)
    print("MACRO MARKET DATA — FETCH SUMMARY")
    print("=" * 100)
    print(f"Tickers requested : {total}")
    print(f"Succeeded         : {succeeded}")
    print(f"Failed            : {len(failed)}"
          + (f"  ({', '.join(failed)})" if failed else ""))
    print(f"Saved             : {SNAPSHOT_PATH} ({len(snapshot_df)} rows), "
          f"{HISTORY_PATH}")
    print("-" * 100)

    if snapshot_df.empty:
        print("Snapshot is empty — nothing to display.")
        return

    # Full snapshot table, sorted by category (then ticker for stable order).
    table = snapshot_df.sort_values(["category", "ticker"]).reset_index(drop=True)
    with pd.option_context(
        "display.max_rows", None,
        "display.max_columns", None,
        "display.width", None,
        "display.float_format", lambda v: f"{v:,.2f}",
    ):
        print(table.to_string(index=False))
    print("=" * 100)


def main() -> int:
    _configure_logging()
    log = logging.getLogger("main")

    try:
        snapshot_df, history_df, failed = fetch_all(INSTRUMENTS)
    except Exception:
        # A total batch failure (all retries exhausted) is the only thing
        # that should land here — individual bad tickers are handled inside.
        log.exception("Fatal: could not fetch any data.")
        return 1

    snapshot_df.to_pickle(SNAPSHOT_PATH)
    history_df.to_pickle(HISTORY_PATH)
    log.info("Wrote %s and %s.", SNAPSHOT_PATH, HISTORY_PATH)

    _print_summary(snapshot_df, failed, total=len(INSTRUMENTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
