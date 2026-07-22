import datetime as dt
import html
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_chart import generate_chart_code, get_api_key as get_groq_api_key, run_chart_code
from dashboard_data import TAB_CONFIG, load_data
from news_data import load_news

BASE_DIR = Path(__file__).resolve().parent

# label -> (fetch script, [output pkl files whose mtime defines "as of"])
DATA_SOURCES = {
    "Yahoo Finance": ("main.py", ["history.pkl", "snapshot.pkl"]),
    "FRED": ("fred_main.py", ["fred_history.pkl", "fred_snapshot.pkl"]),
    "News": ("news_main.py", ["news.pkl"]),
}
_REFRESH_TIMEOUT_S = 240

st.set_page_config(page_title="Macro Dashboard", layout="wide")

# Leave room at the bottom of the page so the fixed news ticker (added at
# the end of the script) never covers the last row of charts.
st.markdown(
    "<style>.block-container { padding-bottom: 4.5rem; }</style>",
    unsafe_allow_html=True,
)

df = load_data()

st.sidebar.header("Filters")
min_date = df["date"].min().date()
max_date = df["date"].max().date()
date_range = st.sidebar.slider(
    "Date range",
    min_value=min_date,
    max_value=max_date,
    value=(min_date, max_date),
    format="YYYY-MM-DD",
)

filtered = df[(df["date"].dt.date >= date_range[0]) & (df["date"].dt.date <= date_range[1])]

st.title("Macro Dashboard")


def _data_as_of(filenames):
    """Latest mtime across the given files, or None if none exist yet."""
    mtimes = [(BASE_DIR / f).stat().st_mtime for f in filenames if (BASE_DIR / f).exists()]
    if not mtimes:
        return None
    return dt.datetime.fromtimestamp(max(mtimes))


def run_refresh():
    """Run each fetch script in turn, then clear caches and rerun the app.

    A failure in one source (e.g. a missing/rate-limited Alpha Vantage key)
    is reported but doesn't stop the others — each source's own "as of" stays
    at its last successful fetch either way.
    """
    with st.status("Refreshing data...", expanded=True) as status:
        any_failed = False
        for label, (script, _) in DATA_SOURCES.items():
            st.write(f"Fetching {label}...")
            try:
                result = subprocess.run(
                    [sys.executable, str(BASE_DIR / script)],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=_REFRESH_TIMEOUT_S,
                )
                if result.returncode == 0:
                    st.write(f"✅ {label} refreshed.")
                else:
                    any_failed = True
                    st.warning(f"{label} refresh failed (exit code {result.returncode}).")
                    with st.expander(f"{script} output"):
                        st.code((result.stdout + "\n" + result.stderr)[-4000:] or "(no output)")
            except subprocess.TimeoutExpired:
                any_failed = True
                st.warning(f"{label} refresh timed out after {_REFRESH_TIMEOUT_S}s.")
            except OSError as exc:
                any_failed = True
                st.warning(f"{label} refresh could not start: {exc}")

        status.update(
            label="Refresh finished with some errors — see details above." if any_failed else "Refresh complete.",
            state="error" if any_failed else "complete",
        )

    load_data.clear()
    load_news.clear()
    st.rerun()


def render_as_of_bar():
    cols = st.columns([2, 2, 2, 1.3])
    for col, label in zip(cols, DATA_SOURCES):
        _, filenames = DATA_SOURCES[label]
        as_of = _data_as_of(filenames)
        with col:
            if as_of:
                st.caption(f"**{label}** as of {as_of:%Y-%m-%d %H:%M:%S}")
            else:
                st.caption(f"**{label}**: not yet fetched")

    with cols[-1]:
        if st.button("🔄 Refresh data", width="stretch"):
            run_refresh()


render_as_of_bar()


def _drag_selection_hint(fig):
    """Invisible marker overlay + dragmode so box-drag selection works.

    Candlestick traces don't support box/lasso selection events in Plotly.js,
    so every chart (line or candlestick) gets this transparent scatter of
    its own close/value points purely as the thing the user's drag hits.
    """
    fig.update_layout(dragmode="select")


def _render_drag_selection(event, name):
    """Below a chart: % change between the first/last date the user dragged over."""
    points = []
    if event:
        points = (event.get("selection") or {}).get("points") or []

    if len(points) < 2:
        st.caption("Drag across the chart (left to right) to select a date range and see the % change.")
        return

    ordered = sorted(points, key=lambda p: p["x"])
    start_pt, end_pt = ordered[0], ordered[-1]
    start_val, end_val = start_pt.get("y"), end_pt.get("y")

    if start_val in (None, 0) or end_val is None or pd.isna(start_val) or pd.isna(end_val):
        st.caption("Selected range has no valid price data.")
        return

    start_date = pd.Timestamp(start_pt["x"]).strftime("%Y-%m-%d")
    end_date = pd.Timestamp(end_pt["x"]).strftime("%Y-%m-%d")
    pct = (end_val / start_val - 1.0) * 100.0

    st.metric(
        label=f"{name}: {start_date} → {end_date}",
        value=f"{end_val:,.4f}",
        delta=f"{pct:+.2f}%",
    )


def render_candlestick_chart(data, name, key):
    data = data.dropna(subset=["value", "open", "high", "low"]).sort_values("date")
    if data.empty:
        st.info(f"No data for {name} in the selected date range.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=data["date"],
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["value"],
            name=name,
            increasing_line_color="#2ECC71",
            increasing_fillcolor="#2ECC71",
            decreasing_line_color="#E74C3C",
            decreasing_fillcolor="#E74C3C",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["value"],
            mode="markers",
            marker=dict(opacity=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        title=name,
        margin=dict(l=10, r=10, t=40, b=10),
        height=300,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )
    _drag_selection_hint(fig)
    event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode=("box",), key=key)
    _render_drag_selection(event, name)


def render_line_chart(data, name, units, key):
    data = data.dropna(subset=["value"]).sort_values("date")
    if data.empty:
        st.info(f"No data for {name} in the selected date range.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["value"],
            mode="lines",
            name=name,
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}" + (f" {units}" if units else "") + "<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["value"],
            mode="markers",
            marker=dict(opacity=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        title=name,
        margin=dict(l=10, r=10, t=40, b=10),
        height=300,
        hovermode="x unified",
        yaxis_title=units if units else None,
    )
    _drag_selection_hint(fig)
    event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode=("box",), key=key)
    _render_drag_selection(event, name)


def render_tab(data, categories):
    sub = data[data["category"].isin(categories)]
    if sub.empty:
        st.info("No data in this category for the selected date range.")
        return

    series_list = sub[["series_id", "name", "units", "source"]].drop_duplicates().sort_values("name")
    cols = st.columns(2)
    for i, (_, row) in enumerate(series_list.iterrows()):
        series_data = sub[sub["series_id"] == row["series_id"]]
        key = f"chart_{row['series_id']}"
        with cols[i % 2]:
            # Candlesticks need a real OHLC trading range, which only the
            # Yahoo Finance series have — FRED only publishes single values.
            if row["source"] == "Yahoo Finance":
                render_candlestick_chart(series_data, row["name"], key)
            else:
                render_line_chart(series_data, row["name"], row["units"], key)


def render_heatmap_grid(rows, trade_date):
    n = len(rows)
    n_cols = max(1, math.ceil(math.sqrt(n)))
    n_rows = math.ceil(n / n_cols)

    z = np.full((n_rows, n_cols), np.nan)
    text = np.full((n_rows, n_cols), "", dtype=object)
    hover = np.full((n_rows, n_cols), "", dtype=object)

    for i, row in enumerate(rows):
        r, c = divmod(i, n_cols)
        pct = row["pct"]
        z[r, c] = pct if pd.notna(pct) else 0.0  # neutral color when no prior close to compare
        pct_str = f"{pct:+.2f}%" if pd.notna(pct) else "n/a"
        text[r, c] = f"{row['series_id']}<br>{pct_str}"
        hover[r, c] = (
            f"{row['name']}<br>{trade_date:%Y-%m-%d}"
            f"<br>Close: {row['value']:.4f}<br>Change: {pct_str}"
        )

    max_abs = max(float(np.nanmax(np.abs(z))) if n else 0.0, 0.5)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 12, "color": "white"},
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=[[0, "#E74C3C"], [0.5, "#2A2E37"], [1, "#2ECC71"]],
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            showscale=True,
            colorbar=dict(title="% chg"),
            xgap=4,
            ygap=4,
        )
    )
    fig.update_layout(
        title=f"Daily change — {trade_date:%Y-%m-%d}",
        height=120 * n_rows + 80,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, autorange="reversed"),
    )
    st.plotly_chart(fig, width="stretch")


def render_heatmap_tab(data):
    # Scoped to Yahoo Finance instruments only — FRED series are economic
    # releases, not traded tickers, so "trade date" doesn't apply to them.
    yahoo_df = data[data["source"] == "Yahoo Finance"]

    instruments = yahoo_df[["series_id", "name"]].drop_duplicates().sort_values("name")
    labels = {row.series_id: f"{row.name} ({row.series_id})" for row in instruments.itertuples()}

    selected = st.multiselect(
        "Select tickers",
        options=instruments["series_id"].tolist(),
        format_func=lambda sid: labels.get(sid, sid),
    )

    available_dates = sorted(yahoo_df["date"].dt.date.unique())
    trade_date = st.date_input(
        "Trade date",
        value=available_dates[-1],
        min_value=available_dates[0],
        max_value=available_dates[-1],
    )

    if not selected:
        st.info("Select one or more tickers above to see the heatmap.")
        return

    if trade_date not in available_dates:
        nearest = min(available_dates, key=lambda d: abs((d - trade_date).days))
        st.warning(
            f"No trading data available for {trade_date:%Y-%m-%d} — markets were "
            f"likely closed that day (weekend or holiday). Nearest available "
            f"trade date: {nearest:%Y-%m-%d}."
        )
        return

    rows = []
    missing = []
    for sid in selected:
        series = yahoo_df[yahoo_df["series_id"] == sid].sort_values("date").reset_index(drop=True)
        day_idx = series.index[series["date"].dt.date == trade_date]
        if len(day_idx) == 0:
            missing.append(sid)
            continue
        pos = day_idx[0]
        curr_value = series.loc[pos, "value"]
        pct = float("nan")
        if pos > 0:
            prev_value = series.loc[pos - 1, "value"]
            if pd.notna(prev_value) and prev_value != 0:
                pct = (curr_value / prev_value - 1.0) * 100.0
        rows.append(
            {"series_id": sid, "name": labels[sid], "pct": pct, "value": curr_value}
        )

    if missing:
        missing_names = ", ".join(labels[m] for m in missing)
        st.caption(
            f"No data on {trade_date:%Y-%m-%d} for: {missing_names} "
            f"(that market was likely closed on this date)."
        )

    if not rows:
        st.warning(f"None of the selected tickers had data on {trade_date:%Y-%m-%d}.")
        return

    render_heatmap_grid(rows, trade_date)


def render_ai_chart_tab(data):
    try:
        api_key = get_groq_api_key()
    except RuntimeError as exc:
        st.info(str(exc))
        return

    st.caption(
        "Proof of concept: describe a chart in plain English and a free hosted LLM "
        "(Groq) writes the Plotly code and runs it here. Double-check anything it produces."
    )
    prompt = st.text_area(
        "What do you want to see?",
        placeholder="e.g. Plot the 10Y-2Y yield spread against VIX since the start of 2026",
        key="ai_chart_prompt",
    )

    if st.button("Generate chart", key="ai_chart_generate"):
        if not prompt.strip():
            st.warning("Enter a description first.")
        else:
            with st.spinner("Asking Groq..."):
                try:
                    code = generate_chart_code(prompt, data, api_key)
                except RuntimeError as exc:
                    st.session_state["ai_chart_code"] = None
                    st.session_state["ai_chart_fig"] = None
                    st.session_state["ai_chart_error"] = str(exc)
                else:
                    fig, error = run_chart_code(code, data)
                    st.session_state["ai_chart_code"] = code
                    st.session_state["ai_chart_fig"] = fig
                    st.session_state["ai_chart_error"] = error

    error = st.session_state.get("ai_chart_error")
    fig = st.session_state.get("ai_chart_fig")
    code = st.session_state.get("ai_chart_code")

    if error:
        st.error(error)
    if fig is not None:
        st.plotly_chart(fig, width="stretch")
    if code:
        with st.expander("Generated code"):
            st.code(code, language="python")


tab_labels = list(TAB_CONFIG.keys()) + ["Heatmap", "Ask AI"]
tabs = st.tabs(tab_labels)
for tab, label in zip(tabs, tab_labels):
    with tab:
        if label == "Heatmap":
            # Uses its own trade-date picker rather than the sidebar range —
            # a heatmap is inherently a single-day snapshot, not a time series.
            render_heatmap_tab(df)
        elif label == "Ask AI":
            # Uses the full unfiltered dataset — the AI picks its own range
            # from the prompt rather than being constrained by the sidebar.
            render_ai_chart_tab(df)
        else:
            render_tab(filtered, TAB_CONFIG[label])


_SENTIMENT_COLORS = {
    "Bullish": "#2ECC71",
    "Somewhat-Bullish": "#2ECC71",
    "Neutral": "#95A5A6",
    "Somewhat-Bearish": "#E74C3C",
    "Bearish": "#E74C3C",
}


def render_news_ticker(news_df):
    if news_df.empty:
        items_html = (
            '<span class="ticker-item">No headlines yet — run '
            '<code>python news_main.py</code> to fetch the latest macro news.</span>'
        )
    else:
        items = []
        for _, row in news_df.iterrows():
            color = _SENTIMENT_COLORS.get(row.get("overall_sentiment_label"), "#95A5A6")
            ts = row["time_published"]
            ts_str = ts.strftime("%b %d %H:%M") if hasattr(ts, "strftime") else ""
            title = html.escape(str(row["title"]))
            source = html.escape(str(row.get("source", "")))
            url = html.escape(str(row.get("url", "")), quote=True)
            items.append(
                f'<span class="ticker-item">'
                f'<span class="ticker-dot" style="background:{color}"></span>'
                f'<b>{source}</b> &mdash; '
                f'<a href="{url}" target="_blank">{title}</a> '
                f'<span class="ticker-time">({ts_str})</span>'
                f"</span>"
            )
        items_html = "".join(items)

    # The track is duplicated so the marquee loop (translateX 0 -> -50%)
    # is seamless instead of jumping when it restarts.
    st.markdown(
        f"""
        <style>
        .news-ticker-bar {{
            position: fixed;
            bottom: 0;
            left: 0;
            width: 100%;
            background: #0E1117;
            border-top: 1px solid #333;
            padding: 8px 0;
            overflow: hidden;
            white-space: nowrap;
            z-index: 999;
        }}
        .news-ticker-track {{
            display: inline-block;
            white-space: nowrap;
            animation: news-ticker-scroll 120s linear infinite;
        }}
        .news-ticker-bar:hover .news-ticker-track {{
            animation-play-state: paused;
        }}
        .ticker-item {{
            display: inline-block;
            color: #EEE;
            font-size: 14px;
            margin-right: 48px;
        }}
        .ticker-item a {{
            color: #EEE;
            text-decoration: none;
        }}
        .ticker-item a:hover {{
            text-decoration: underline;
        }}
        .ticker-dot {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
        }}
        .ticker-time {{
            color: #888;
            font-size: 12px;
        }}
        @keyframes news-ticker-scroll {{
            0%   {{ transform: translateX(0); }}
            100% {{ transform: translateX(-50%); }}
        }}
        </style>
        <div class="news-ticker-bar">
            <div class="news-ticker-track">{items_html}{items_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


render_news_ticker(load_news())
