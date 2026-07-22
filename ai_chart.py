"""Natural-language -> custom chart, via Groq's free-tier hosted LLM API.

Parallel to fred_fetch.py / news_fetch.py — same .env convention. Unlike
those, this isn't a data source: it turns a user's prompt into a small
pandas/Plotly snippet (via Groq) and runs it in a restricted sandbox against
the dashboard's own data, so the result can be shown as a chart.

Docs: https://console.groq.com/docs/api-reference#chat-create
Free API key: https://console.groq.com/keys

This is a proof of concept, not a hardened multi-tenant sandbox: the
restricted builtins + thread timeout stop obviously bad code (file access,
network, infinite loops that raise) but a determined adversarial prompt
could still burn CPU in a background thread that outlives the timeout,
since Python can't forcibly kill a thread. Fine for a single local user
poking at their own dashboard; not something to expose publicly as-is.
"""

from __future__ import annotations

import builtins
import concurrent.futures
import os
import re

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests

_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_ENV_FILE = ".env"
_ENV_KEY = "GROQ_API_KEY"
_MODEL_NAME = "llama-3.3-70b-versatile"
_REQUEST_TIMEOUT_S = 60
_EXEC_TIMEOUT_S = 15

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

# Builtins allow-list for the exec() sandbox — no __import__, open, exec,
# eval, compile, input, or anything else that reaches outside pandas/numpy/
# plotly manipulation of the dataframe already handed to it.
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "range", "reversed", "round",
    "set", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
    "print",
)
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES if hasattr(builtins, name)}


# ---------------------------------------------------------------------------
# API key handling (.env) — identical convention to fred_fetch.py / news_fetch.py
# ---------------------------------------------------------------------------

def _load_dotenv(path: str = _ENV_FILE) -> None:
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
    """Return the Groq API key from the environment or .env, or raise."""
    _load_dotenv()
    key = os.environ.get(_ENV_KEY, "").strip()
    if not key:
        raise RuntimeError(
            f"No Groq API key found. Get a free one at https://console.groq.com/keys "
            f"and set {_ENV_KEY} in the environment or in a local {_ENV_FILE} file "
            f"({_ENV_KEY}=<your key>)."
        )
    return key


# ---------------------------------------------------------------------------
# Schema-aware prompt
# ---------------------------------------------------------------------------

def build_system_prompt(df: pd.DataFrame) -> str:
    """Describe the dataframe schema and every available series to the model.

    Listing every series_id/name/category up front (there are only ~150)
    keeps the model from hallucinating tickers that don't exist.
    """
    catalog = (
        df[["series_id", "name", "category", "source"]]
        .drop_duplicates()
        .sort_values(["source", "category", "name"])
    )
    lines = [f"{r.series_id} | {r.name} | {r.category} | {r.source}" for r in catalog.itertuples()]
    catalog_text = "\n".join(lines)

    return f"""You write Python code that builds ONE Plotly chart from a pandas DataFrame called `df`.

df is in long format with columns:
- series_id (str): ticker (Yahoo Finance) or FRED series id
- date (datetime64)
- value (float): the price/close (Yahoo) or observation value (FRED)
- open, high, low (float): only populated for source == "Yahoo Finance"; NaN for FRED
- name (str): human-readable label
- category (str): e.g. "Rates", "Inflation", "Equity Index", "FX", ...
- source (str): "Yahoo Finance" or "FRED"
- frequency, units (str): native units/frequency, mostly relevant for FRED

Every available series_id (id | name | category | source):
{catalog_text}

Rules:
- Output ONLY raw Python code. No explanations, no markdown, no code fences.
- Use pandas as pd, numpy as np, plotly.graph_objects as go, plotly.express as px.
- df is already provided in scope — do not redefine or reload it.
- Filter/reshape df as needed (e.g. pivot by series_id) to answer the request.
- Assign the final chart to a variable named `fig` (a plotly Figure).
- Only use series_id values from the catalog above — never invent one.
- Do not read/write files, use the network, or import anything.
"""


def _extract_code(text: str) -> str:
    match = _CODE_FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def generate_chart_code(user_prompt: str, df: pd.DataFrame, api_key: str) -> str:
    """Ask Groq for a plotting snippet; return the extracted Python code.

    Raises RuntimeError on any API-level failure (bad key, rate limit, etc).
    """
    payload = {
        "model": _MODEL_NAME,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": build_system_prompt(df)},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(_API_URL, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Groq: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Groq API error (HTTP {resp.status_code}): {resp.text[:500]}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Groq response shape: {data}") from exc

    return _extract_code(content)


# ---------------------------------------------------------------------------
# Sandboxed execution
# ---------------------------------------------------------------------------

def _exec_code(code: str, df: pd.DataFrame) -> go.Figure:
    sandbox_globals = {"__builtins__": _SAFE_BUILTINS}
    sandbox_locals = {"df": df.copy(), "pd": pd, "np": np, "go": go, "px": px}
    exec(compile(code, "<ai_chart>", "exec"), sandbox_globals, sandbox_locals)  # noqa: S102

    fig = sandbox_locals.get("fig")
    if not isinstance(fig, go.Figure):
        raise RuntimeError("The generated code didn't produce a `fig` variable that's a Plotly figure.")
    return fig


def run_chart_code(code: str, df: pd.DataFrame) -> tuple[go.Figure | None, str | None]:
    """Run generated code in a restricted namespace with a wall-clock timeout.

    Returns (fig, None) on success or (None, error_message) on failure.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_exec_code, code, df)
        try:
            fig = future.result(timeout=_EXEC_TIMEOUT_S)
            return fig, None
        except concurrent.futures.TimeoutError:
            return None, f"Generated code took longer than {_EXEC_TIMEOUT_S}s and was abandoned."
        except Exception as exc:  # noqa: BLE001 - surface any generated-code error to the user
            return None, f"{type(exc).__name__}: {exc}"
