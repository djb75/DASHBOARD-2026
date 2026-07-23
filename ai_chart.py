"""Natural-language -> custom chart, via Groq's free-tier hosted LLM API.

Parallel to fred_fetch.py / news_fetch.py — same .env convention. Unlike
those, this isn't a data source: it turns a user's prompt into a small
pandas/Plotly snippet (via Groq) and runs it in a restricted sandbox against
the dashboard's own data, so the result can be shown as a chart.

Docs: https://console.groq.com/docs/api-reference#chat-create
Free API key: https://console.groq.com/keys

This is a proof of concept, not a hardened multi-tenant sandbox. Two layers
of defense: a static AST check rejects dunder attribute/name access before
anything runs (closing the classic `().__class__.__bases__[0]
.__subclasses__()` trick of reaching subprocess.Popen or similar without
ever importing anything — restricted builtins/imports alone don't stop
this, since every Python object exposes its class/bases/subclasses
regardless of what names are in scope), and actual execution happens in a
separate subprocess (ai_chart_worker.py), not a thread, specifically so a
runaway or adversarial snippet can be genuinely killed on timeout (verified:
an actual infinite loop leaves no lingering process afterward) and
best-effort memory-limited via a POSIX rlimit — confirmed working in
principle but confirmed NON-functional on macOS specifically (a real
XNU/kernel limitation, not a bug here; see ai_chart_worker.py), so the
timeout is the only real backstop against a memory hog on macOS. Still not
a real security boundary the way a container/gVisor/WASM sandbox is — fine
for a single local user poking at their own dashboard, not
something to expose publicly without further hardening.
"""

from __future__ import annotations

import ast
import builtins
import datetime
import itertools
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import requests

_BASE_DIR = Path(__file__).resolve().parent

_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_ENV_FILE = ".env"
_ENV_KEY = "GROQ_API_KEY"
_MODEL_NAME = "llama-3.3-70b-versatile"
_REQUEST_TIMEOUT_S = 60
_EXEC_TIMEOUT_S = 15

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

# Builtins allow-list for the exec() sandbox — no open, exec, eval, compile,
# input, or anything else that reaches outside pandas/numpy/plotly
# manipulation of the dataframe already handed to it. __import__ is handled
# separately below (a restricted version, not a plain removal) because
# models routinely prepend "import pandas as pd" etc. to snippets despite
# being told the modules are already in scope — removing __import__ entirely
# turned that into a confusing "missing module" error instead of just
# harmlessly re-binding a name we already trust.
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "range", "reversed", "round",
    "set", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
    "print",
)
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES if hasattr(builtins, name)}

# Top-level packages the sandbox will import — gated by package, not by an
# exact finite list of dotted paths. That distinction matters: numpy/pandas
# lazily self-import private submodules the first time certain methods are
# called (e.g. ndarray.mean() imports numpy._core._methods on first use),
# and Python resolves __import__ via the CALLING frame's builtins — i.e.
# whichever exec() namespace happens to be executing when that first call
# fires, not the frame numpy's own code textually lives in. An exact-path
# allowlist rejected those as if they were something the user's code tried
# to reach, breaking ordinary methods like .mean()/.std()/.corr() outright.
# None of this is a bigger trust boundary than before: pd/np/go/px are
# handed over as the real, fully-loaded modules already, so every submodule
# here was already reachable via plain attribute access (pd.io, np.linalg,
# ...) with zero import needed — this just makes `import` syntax consistent
# with that pre-existing access rather than blocking the statement while
# the equivalent attribute access still works.
_TRUSTED_TOP_LEVEL_PACKAGES = {
    "pandas", "numpy", "plotly", "math", "datetime", "re", "statistics", "itertools",
}
_REAL_IMPORT = builtins.__import__  # captured before any sandbox ever overrides it


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    top_level = name.split(".")[0]
    if top_level not in _TRUSTED_TOP_LEVEL_PACKAGES:
        raise ImportError(
            f"'{name}' isn't available in this sandbox. Only pandas, numpy, "
            f"plotly, math, datetime, re, statistics, itertools (and their "
            f"submodules) can be imported — pd/np/go/px are already in scope "
            f"under those names without needing an import at all."
        )
    # Delegate the actual mechanics (submodules, fromlist, sys.modules
    # caching, the whole "return top-level vs. leaf module" contract) to
    # the real __import__ — we only gate WHICH top-level package is
    # trusted, not how import resolution itself works.
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


_SAFE_BUILTINS["__import__"] = _restricted_import


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
- df, pd (pandas), np (numpy), go (plotly.graph_objects), and px (plotly.express)
  are already provided in scope — do not import them, and do not redefine or reload df.
- The ONLY modules available at all, if you import anything, are: {", ".join(sorted(_TRUSTED_TOP_LEVEL_PACKAGES))}.
  Nothing else is installed in this environment — no matplotlib, seaborn, scipy, sklearn,
  statsmodels, requests, os, sys, or anything not in that list. Using px.scatter's
  `trendline="ols"` will fail here since it needs statsmodels, which isn't available.
- If the request genuinely cannot be done with only those modules, do not guess, invent
  an import, or silently produce a wrong/empty chart. Instead set `fig = None` and set
  `error_message = "<one short sentence explaining why not>"`.
- Filter/reshape df as needed (e.g. pivot by series_id) to answer the request.
- Assign the final chart to a variable named `fig` (a plotly Figure).
- Only use series_id values from the catalog above — never invent one. If the user asks
  for a ticker/series that isn't in the catalog, do not silently filter down to an empty
  chart — set `fig = None` and `error_message = "<name> isn't in the available dataset"`.
- Do not read or write files, or use the network.
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

def build_sandbox_namespace(df: pd.DataFrame) -> dict:
    """The restricted exec() namespace: builtins/imports allow-list + df/pd/np/go/px.

    Used as BOTH globals and locals when executing generated code (by
    ai_chart_worker.py, in its own subprocess) — exec() with two separate
    dicts is a classic trap: any def/lambda the generated code writes (e.g.
    df["value"].apply(lambda v: np.log(v)), extremely common in pandas
    code) gets its __globals__ fixed to the globals dict only, so names
    that exist solely in a separate locals dict (np, pd, go, px, df)
    vanish inside it with a NameError. One shared dict avoids that split.
    """
    return {
        "__builtins__": _SAFE_BUILTINS,
        "df": df.copy(),
        "pd": pd,
        "np": np,
        "go": go,
        "px": px,
    }


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def check_code_safety(code: str) -> None:
    """Static pre-check, run before the code ever executes (in-process, so
    it can reject bad code without even paying for a subprocess spawn).

    Blocks the classic sandbox-escape trick of reaching dangerous objects
    via dunder introspection — e.g. `().__class__.__bases__[0]
    .__subclasses__()` to find subprocess.Popen and get arbitrary process
    execution, without ever calling `import` at all. Restricted builtins
    and a restricted `__import__` don't stop this: every Python object
    exposes its class/bases/subclasses via dunder attributes regardless of
    what names happen to be in scope, so this has to be caught by
    inspecting the code itself, not by restricting the runtime namespace.

    Raises RuntimeError with a clear message if the code looks unsafe.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise RuntimeError(f"SyntaxError: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
            raise RuntimeError(
                f"Generated code accesses `.{node.attr}`, which looks like sandbox-escape "
                f"introspection (e.g. reaching __class__/__subclasses__) rather than normal "
                f"pandas/plotly usage, so it's blocked."
            )
        if isinstance(node, ast.Name) and _is_dunder(node.id):
            raise RuntimeError(f"Generated code references `{node.id}` directly, which isn't allowed.")


def run_chart_code(code: str, df: pd.DataFrame) -> tuple[go.Figure | None, str | None]:
    """Run generated code in a separate, resource-limited subprocess.

    A subprocess (not a thread) is used specifically because it can be
    forcibly killed on timeout — Python threads cannot be killed once
    started, so a thread-based approach would leave a runaway/adversarial
    snippet burning CPU in the background indefinitely even after "giving
    up" on it from the UI's perspective. The subprocess also gets its own
    POSIX memory rlimit (see ai_chart_worker.py) so a huge-allocation
    attempt can't take down the main Streamlit process — that's only safe
    to apply because it's a fully separate process, not a limit shared
    with the app itself.

    Returns (fig, None) on success or (None, error_message) on failure.
    """
    try:
        check_code_safety(code)
    except RuntimeError as exc:
        return None, str(exc)

    worker_path = _BASE_DIR / "ai_chart_worker.py"

    with tempfile.TemporaryDirectory() as tmp_dir:
        df_path = os.path.join(tmp_dir, "df.pkl")
        code_path = os.path.join(tmp_dir, "code.py")
        output_path = os.path.join(tmp_dir, "fig.json")

        df.to_pickle(df_path)
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write(code)

        try:
            result = subprocess.run(
                [sys.executable, str(worker_path), df_path, code_path, output_path],
                capture_output=True,
                text=True,
                timeout=_EXEC_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return None, f"Generated code took longer than {_EXEC_TIMEOUT_S}s and was killed."
        except OSError as exc:
            return None, f"Could not start the sandboxed worker process: {exc}"

        if result.returncode != 0:
            message = result.stderr.strip() or f"Worker process exited with code {result.returncode}."
            return None, message

        if not os.path.exists(output_path):
            return None, "The generated code didn't produce a `fig` variable that's a Plotly figure."

        with open(output_path, encoding="utf-8") as fh:
            fig = pio.from_json(fh.read())
        return fig, None
