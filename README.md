# Macro Market Data Scraper

Small, production-quality scraper that pulls a fixed universe of macro
instruments from Yahoo Finance (via `yfinance`) and produces two clean
pandas DataFrames for a downstream dashboard.

## Output

Two native pandas pickles written to the working directory:

- **`snapshot.pkl`** — one row per ticker, dashboard-ready:
  `ticker, name, category, region, last, prev_close, chg, chg_pct,
  day_high, day_low, ret_1w, ret_1m, ret_ytd, currency, as_of_utc`
- **`history.pkl`** — tidy long 1y daily OHLCV:
  `ticker, date, open, high, low, close, volume` (+ merged metadata)

## Universe

~54 instruments defined in `config.py`, covering:

- Equity index futures (ES, NQ, YM, RTY)
- Cash indices — US, Europe, Asia, EM
- Volatility (VIX)
- FX — DXY + G10 + EM crosses
- US Treasury yields (2/5/10/30Y equivalents) and bond/credit ETFs
- Commodity futures (energy, metals, softs, grains) + broad commodity ETF
- Crypto (BTC, ETH)

Edit `config.py` to add or remove tickers.

## Install & run

```bash
pip install yfinance pandas
python main.py
```

Prints a category-sorted summary to stdout and writes the two pickles.

## Files

- **`config.py`** — instrument universe (ticker + name/category/region).
- **`fetch.py`** — batched download, retry/backoff, MultiIndex → tidy
  long reshape, snapshot construction.
- **`main.py`** — entry point: logging setup, fetch, save pickles, print
  summary.

## Design notes

**Batched, not per-ticker.** All tickers are pulled in a single
`yf.download(..., group_by="ticker")` call. Looping one call per ticker
trips Yahoo's rate limiter (429 / `YFRateLimitError`) fast.

**Retry with exponential backoff.** The batch call is retried up to 3
times (2s, 4s, 8s) on failure or empty response. Individual bad tickers
inside a successful batch are logged as `WARNING` and skipped — one
dead symbol never aborts the run.

**Yield scale sanity check.** Yahoo reports `^TNX / ^TYX / ^FVX / ^IRX`
inconsistently (sometimes as the yield in %, sometimes ×10). If a value
falls outside a plausible 0–20% range, a `WARNING` is logged. The value
is **not** silently rescaled — flagging is safer than corrupting good
data.

**Currency column.** `yf.download` returns no currency metadata, and
per-ticker `fast_info` lookups would defeat the whole point of batching.
Since the universe is fixed, currencies are mapped statically in
`fetch.py` (non-USD indices, FX quote currencies, `"PTS"` for VIX/DXY,
`"%"` for yields; everything else defaults to USD).

## SSL / corporate proxy

The code **does not touch SSL configuration**. Current `yfinance` uses
`curl_cffi` (libcurl) under the hood, which honours these environment
variables:

```bash
export CURL_CA_BUNDLE=/path/to/your/corporate-ca.pem
export SSL_CERT_FILE=/path/to/your/corporate-ca.pem
```

If neither is set, `main.py` logs a `WARNING` at startup — behind an
HTTPS-intercepting proxy the run will almost certainly fail with a
cert-verification error until one of them points at your company CA.

No `verify=False`, no custom session, no `truststore` — CA handling is
the caller's job.

## Requirements

- `yfinance`, `pandas`
