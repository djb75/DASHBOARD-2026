import datetime as dt
import html
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from ai_chart import generate_chart_code, get_api_key as get_groq_api_key, run_chart_code
from dashboard_data import TAB_CONFIG, load_data
from news_data import load_news

BASE_DIR = Path(__file__).resolve().parent

# label -> (fetch script, [output pkl files whose mtime defines "as of"], staleness threshold)
# News gets a much longer threshold than Yahoo/FRED: Alpha Vantage's free
# tier is tightly rate-limited and macro-news topics have low genuine
# volume, so checking it every hour like the others just burns quota
# re-requesting headlines that mostly haven't changed.
DATA_SOURCES = {
    "Yahoo Finance": ("main.py", ["history.pkl", "snapshot.pkl"], dt.timedelta(hours=1)),
    "FRED": ("fred_main.py", ["fred_history.pkl", "fred_snapshot.pkl"], dt.timedelta(hours=1)),
    "News": ("news_main.py", ["news.pkl"], dt.timedelta(hours=6)),
}
_REFRESH_TIMEOUT_S = 240
_SECRET_ENV_KEYS = ("FRED_API_KEY", "ALPHAVANTAGE_API_KEY", "GROQ_API_KEY")


def _promote_secrets_to_env():
    """Hosted (e.g. Streamlit Community Cloud) API keys live in st.secrets,
    not a local .env file. Copy them into os.environ so fred_fetch.py /
    news_fetch.py / ai_chart.py — and the fetch scripts run as subprocesses
    by the Refresh button, which only inherit real env vars, never
    st.secrets — all keep working unchanged, on hosted or local alike.
    """
    try:
        for key in _SECRET_ENV_KEYS:
            if key not in os.environ and key in st.secrets:
                os.environ[key] = st.secrets[key]
    except StreamlitSecretNotFoundError:
        pass  # local dev: no secrets.toml — .env already covers this via os.environ


_promote_secrets_to_env()

st.set_page_config(page_title="Global Macro Dashboard", layout="wide")

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

st.title("Global Macro Dashboard")


def _data_as_of(filenames):
    """Latest mtime across the given files, or None if none exist yet."""
    mtimes = [(BASE_DIR / f).stat().st_mtime for f in filenames if (BASE_DIR / f).exists()]
    if not mtimes:
        return None
    return dt.datetime.fromtimestamp(max(mtimes))


def _stale_sources() -> list[str]:
    """Data sources with no fetch yet, or whose last fetch is older than their own threshold."""
    now = dt.datetime.now()
    return [
        label
        for label, (_, filenames, stale_after) in DATA_SOURCES.items()
        if (as_of := _data_as_of(filenames)) is None or (now - as_of) > stale_after
    ]


def run_refresh(labels=None):
    """Run each fetch script in turn, then clear caches and rerun the app.

    labels: which DATA_SOURCES to refresh; None (the manual button) means
    all of them. The auto-refresh-on-load path passes only the sources
    that are actually stale, so News's longer threshold isn't defeated by
    getting swept along every time Yahoo/FRED's shorter one trips.

    A failure in one source (e.g. a missing/rate-limited Alpha Vantage key)
    is reported but doesn't stop the others — each source's own "as of" stays
    at its last successful fetch either way.
    """
    targets = {label: DATA_SOURCES[label] for label in (labels if labels is not None else DATA_SOURCES)}
    with st.status("Refreshing data...", expanded=True) as status:
        any_failed = False
        for label, (script, _, _) in targets.items():
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
        _, filenames, _ = DATA_SOURCES[label]
        as_of = _data_as_of(filenames)
        with col:
            if as_of:
                st.caption(f"**{label}** as of {as_of:%Y-%m-%d %H:%M:%S}")
            else:
                st.caption(f"**{label}**: not yet fetched")

    with cols[-1]:
        if st.button("🔄 Refresh data", width="stretch"):
            run_refresh()


# Auto-refresh once per session if any source's data is older than its own
# threshold — session_state guards this so it fires on first load only, not
# on every rerun a widget interaction triggers (run_refresh() itself always
# ends in st.rerun(), so on a genuine refresh this run stops here anyway).
# Only the stale sources are refreshed, not all three, so News's longer
# threshold actually reduces its fetch frequency instead of being swept
# along whenever Yahoo/FRED's shorter threshold trips.
if "auto_refresh_done" not in st.session_state:
    st.session_state["auto_refresh_done"] = True
    stale = _stale_sources()
    if stale:
        st.info(f"Data is stale ({', '.join(stale)}) — refreshing automatically...")
        run_refresh(stale)

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


def render_correlation_heatmap(returns, labels):
    """returns: wide DataFrame indexed by date, one column of daily % returns per series_id."""
    corr = returns.corr()
    series_ids = corr.columns.tolist()
    n = len(series_ids)
    tick_labels = [labels[sid] for sid in series_ids]

    z = corr.values
    text = np.array([[f"{z[i, j]:.2f}" if pd.notna(z[i, j]) else "n/a" for j in range(n)] for i in range(n)])
    hover = np.array(
        [[f"{tick_labels[i]} vs {tick_labels[j]}<br>Correlation: {z[i, j]:.3f}"
          if pd.notna(z[i, j]) else f"{tick_labels[i]} vs {tick_labels[j]}<br>Not enough overlapping data"
          for j in range(n)] for i in range(n)]
    )

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=series_ids,
            y=series_ids,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11, "color": "white"},
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=[[0, "#E74C3C"], [0.5, "#253f59"], [1, "#2ECC71"]],
            zmid=0,
            zmin=-1,
            zmax=1,
            showscale=True,
            colorbar=dict(title="corr"),
            xgap=2,
            ygap=2,
        )
    )
    fig.update_layout(
        title="Return correlation",
        height=max(400, 60 * n),
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(showgrid=False, zeroline=False, tickangle=-45),
        yaxis=dict(showgrid=False, zeroline=False, autorange="reversed"),
    )
    st.plotly_chart(fig, width="stretch")


def render_heatmap_tab(data):
    # Scoped to Yahoo Finance instruments only — FRED series are economic
    # releases on their own irregular calendars, not daily-traded prices,
    # so a return correlation isn't a like-for-like comparison there.
    yahoo_df = data[data["source"] == "Yahoo Finance"]

    instruments = yahoo_df[["series_id", "name"]].drop_duplicates().sort_values("name")
    labels = {row.series_id: f"{row.name} ({row.series_id})" for row in instruments.itertuples()}

    selected = st.multiselect(
        "Select tickers",
        options=instruments["series_id"].tolist(),
        format_func=lambda sid: labels.get(sid, sid),
    )

    available_dates = sorted(yahoo_df["date"].dt.date.unique())
    date_range = st.date_input(
        "Date range for correlation",
        value=(available_dates[0], available_dates[-1]),
        min_value=available_dates[0],
        max_value=available_dates[-1],
    )

    if not selected:
        st.info("Select two or more tickers above to see their return correlation.")
        return

    if len(selected) < 2:
        st.info("Select at least one more ticker — correlation needs two or more series.")
        return

    if not isinstance(date_range, tuple) or len(date_range) != 2:
        st.info("Pick a start and end date to define the correlation window.")
        return

    start_date, end_date = date_range
    if start_date > end_date:
        st.warning("Start date is after end date — pick a valid range.")
        return

    window = yahoo_df[
        yahoo_df["series_id"].isin(selected)
        & (yahoo_df["date"].dt.date >= start_date)
        & (yahoo_df["date"].dt.date <= end_date)
    ]

    if window.empty:
        st.warning(
            f"No trading data available for the selected tickers between "
            f"{start_date:%Y-%m-%d} and {end_date:%Y-%m-%d}."
        )
        return

    wide = window.pivot_table(index="date", columns="series_id", values="value")

    missing = [sid for sid in selected if sid not in wide.columns]
    present = [sid for sid in selected if sid in wide.columns]
    if missing:
        missing_names = ", ".join(labels[m] for m in missing)
        st.caption(f"No data in this range for: {missing_names} — excluded from the correlation.")

    wide = wide[present]
    if wide.shape[1] < 2:
        st.warning("Not enough tickers with data in this range to compute a correlation.")
        return

    returns = wide.pct_change().dropna(how="all")
    if returns.shape[0] < 2:
        st.warning(
            f"Not enough overlapping trading days between {start_date:%Y-%m-%d} and "
            f"{end_date:%Y-%m-%d} to compute a correlation — pick a wider date range."
        )
        return

    render_correlation_heatmap(returns, labels)


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
        st.error("⚠️ The AI couldn't generate this chart. Try rephrasing your request.")
        with st.expander("Show error details"):
            st.code(error)
    if fig is not None:
        st.plotly_chart(fig, width="stretch")
    if code:
        with st.expander("Generated code"):
            st.code(code, language="python")


@st.dialog("Correlation Heatmap", width="large", icon="🔥")
def heatmap_dialog():
    # Uses its own date-range picker rather than the sidebar range —
    # correlation is computed over whatever window the user picks here.
    render_heatmap_tab(df)


@st.dialog("Ask AI", width="large", icon="🤖")
def ai_chart_dialog():
    # Uses the full unfiltered dataset — the AI picks its own range
    # from the prompt rather than being constrained by the sidebar.
    render_ai_chart_tab(df)


# Pulled out of the tab bar — with 10 category tabs already, these two were
# easy to miss scrolled off to the right. Popups keep them one click away
# and impossible not to notice.
launch_col1, launch_col2, _ = st.columns([1, 1, 3])
with launch_col1:
    if st.button("🔥 Correlation Heatmap", width="stretch"):
        heatmap_dialog()
with launch_col2:
    if st.button("✨ Ask AI", width="stretch"):
        ai_chart_dialog()

tab_labels = list(TAB_CONFIG.keys())
tabs = st.tabs(tab_labels)
for tab, label in zip(tabs, tab_labels):
    with tab:
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
            background: #082741;
            border-top: 1px solid #457b9d;
            padding: 8px 0;
            overflow: hidden;
            white-space: nowrap;
            z-index: 999;
        }}
        .news-ticker-track {{
            display: inline-block;
            white-space: nowrap;
            animation: news-ticker-scroll 240s linear infinite;
        }}
        .news-ticker-bar:hover .news-ticker-track {{
            animation-play-state: paused;
        }}
        .ticker-item {{
            display: inline-block;
            color: #FFFFFF;
            font-size: 14px;
            margin-right: 48px;
        }}
        .ticker-item a {{
            color: #FFFFFF;
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
            color: #9fb8cc;
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
