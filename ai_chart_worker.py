"""Subprocess entry point for ai_chart.py's sandboxed code execution.

Runs as a genuinely separate OS process (not a thread) specifically so a
runaway or adversarial snippet can be forcibly killed on timeout — Python
threads cannot be killed once started, so a thread-based sandbox can only
ever "give up and stop waiting," not actually stop the code. Confirmed by
actually running an infinite loop through it: the process is genuinely
gone afterward, not left spinning in the background.

Being a separate process also lets us ATTEMPT a memory cap via a POSIX
rlimit without risking the main Streamlit process. Tested empirically
rather than assumed: on Linux this is expected to work normally, but on
macOS specifically, `resource.setrlimit(RLIMIT_AS, ...)` (and RLIMIT_DATA)
reliably fail outright with "current limit exceeds maximum limit" and
provide ZERO protection — a confirmed macOS/XNU kernel limitation, not a
bug here. On macOS the timeout is the only real backstop against a memory
hog; a huge-but-finite allocation attempt still gets killed within
_EXEC_TIMEOUT_S seconds regardless, just without a memory cap tightening
that window further.

Usage:
    python ai_chart_worker.py <df_pickle_path> <code_path> <output_json_path>

Writes the resulting Plotly figure as JSON to <output_json_path> and exits 0
on success. On failure, prints a one-line "ExceptionType: message" to
stderr and exits nonzero — the parent (ai_chart.run_chart_code) reads that
back as the user-facing error.
"""

from __future__ import annotations

import sys

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from ai_chart import build_sandbox_namespace

try:
    import resource  # POSIX only — not available on Windows
except ImportError:
    resource = None

# Generous for building a chart off this dashboard's data (tens of
# thousands of rows, a few MB) but well short of what an actual memory-bomb
# allocation attempt would need. Only actually enforced on platforms where
# RLIMIT_AS works (see module docstring — confirmed non-functional on macOS).
_MAX_MEMORY_BYTES = 2_000_000_000


def _apply_memory_limit() -> None:
    if resource is None:
        return  # Windows: no rlimit support at all — timeout-based kill is still in effect
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_MAX_MEMORY_BYTES, _MAX_MEMORY_BYTES))
    except (ValueError, OSError):
        pass  # e.g. macOS — confirmed unenforceable there; timeout-based kill still applies


def main() -> int:
    _apply_memory_limit()

    df_path, code_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
    df = pd.read_pickle(df_path)
    with open(code_path, encoding="utf-8") as fh:
        code = fh.read()

    namespace = build_sandbox_namespace(df)
    exec(compile(code, "<ai_chart>", "exec"), namespace)  # noqa: S102

    fig = namespace.get("fig")
    if not isinstance(fig, go.Figure):
        error_message = namespace.get("error_message")
        if error_message:
            print(f"The AI couldn't build this chart: {error_message}", file=sys.stderr)
        else:
            print("The generated code didn't produce a `fig` variable that's a Plotly figure.", file=sys.stderr)
        return 1

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(pio.to_json(fig))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - report any generated-code error back to the parent
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
