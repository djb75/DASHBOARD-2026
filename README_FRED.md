# FRED Macro Data Scraper

Parallel pipeline to the Yahoo Finance price scraper (`main.py`) — pulls
~51 economic data series (GDP, CPI, NFP, rates, credit, housing, …) from
the FRED API into two pandas pickles for the same downstream dashboard.
Completely independent of the price code: run either one on its own.

## Output

- **`fred_snapshot.pkl`** — one row per series, dashboard-ready:
  `series_id, name, category, region, frequency, units, last, prev, chg,
  chg_pct, yoy_chg, yoy_pct, last_date, as_of_utc`
- **`fred_history.pkl`** — tidy long history at each series' native
  frequency: `series_id, date, value` (+ merged metadata)

## Universe

51 series defined in `fred_config.py`: growth/activity, labor, inflation,
monetary policy, rates, liquidity, credit, housing, consumer, fiscal,
external, and international (Euro Area / UK / Japan / Germany).
Edit `fred_config.py` to add or remove series.

## Install & run

```bash
pip install requests pandas
python fred_main.py
```

Needs a FRED API key (free: https://fred.stlouisfed.org/docs/api/api_key.html)
in the `FRED_API_KEY` environment variable or a local `.env` file:

```
FRED_API_KEY=<your key>
```

`.env` is gitignored — never commit the key.

## Design notes

**One request per series, throttled.** Unlike Yahoo, FRED serves one
series per `series/observations` call. The official limit is 120
requests/minute, so the loop sleeps 0.5s between calls (~30s total).
Each call retries up to 3 times with backoff (2s/4s/8s); one dead series
never aborts the run.

**Native frequency, frequency-scaled lookback.** Series are fetched at
their release frequency (no aggregation), with lookback windows chosen to
give comparable trend context: daily 5y, weekly 10y, monthly 15y,
quarterly 30y.

**Full re-fetch every run.** Macro series get revised (GDP, payrolls
especially), so the pickles are always a clean rebuild — never an append.

**Change semantics.** `chg` is in native units (percentage *points* for
series quoted in %). `chg_pct` / `yoy_pct` are NaN when the base is ≤ 0
(meaningless for spread/balance series that cross zero). `yoy_chg` /
`yoy_pct` compare against the last observation at least one calendar year
back, so they work identically across frequencies.

**Staleness surfaced, not hidden.** The summary flags series whose latest
observation is old for its frequency. Three international series are
knowingly stale: FRED's OECD-sourced mirrors (Japan CPI, UK CPI, Euro
Area unemployment) stopped updating after OECD's 2024 licensing change,
and FRED has no fresh monthly replacement (verified via the FRED search
API). They're kept for their history; current values need a non-FRED
source eventually (Eurostat, ONS, e-Stat, or DBnomics). The
Eurostat/central-bank-sourced series (EA HICP, EA GDP, ECB rate) are live.

## Files

- **`fred_config.py`** — series universe (id + name/category/region/frequency/units).
- **`fred_fetch.py`** — API client: .env key loading, per-series download
  with retry + throttle, tidy reshape, snapshot construction.
- **`fred_main.py`** — entry point: logging, fetch, save pickles, print
  summary + staleness report.
