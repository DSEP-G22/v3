"""LangSmith tracing. Off unless LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set.

One case is one trace: the orchestrator opens the root run and forwards its headers on every
stage call (headers()), and each service nests its own span under them (parent=...). With
tracing off every helper is a no-op, so no service depends on LangSmith being reachable.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Mapping
from typing import Any

PROJECT = os.environ.get("LANGSMITH_PROJECT") or "lanka-link-v3"
ENABLED = os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))

if ENABLED:
    try:
        from langsmith import trace as _trace
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:  # pragma: no cover - the dependency ships with lanka_common
        ENABLED = False

TRACE_HEADERS = ("langsmith-trace", "baggage")


@contextlib.contextmanager
def span(name: str, *, run_type: str = "chain", inputs: dict[str, Any] | None = None,
         parent: Mapping[str, str] | None = None, **metadata: Any) -> Iterator[Any]:
    """A LangSmith run around the block. Yields the run, or None when tracing is off."""
    if not ENABLED:
        yield None
        return
    try:
        cm = _trace(name, run_type=run_type, inputs=inputs or {}, metadata=metadata, project_name=PROJECT,
                    parent=dict(parent) if parent else None)
        run = cm.__enter__()
    except Exception:  # noqa: BLE001 - tracing must never break a case
        yield None
        return
    exc_info: tuple[Any, Any, Any] = (None, None, None)
    try:
        yield run
    except BaseException as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
        raise
    finally:
        with contextlib.suppress(Exception):
            cm.__exit__(*exc_info)


def finish(run: Any, outputs: dict[str, Any]) -> None:
    """Attach outputs to a run from span(); harmless when run is None."""
    if run is None:
        return
    with contextlib.suppress(Exception):
        if hasattr(run, "add_outputs"):
            run.add_outputs(outputs)
        else:
            run.outputs = outputs


def headers() -> dict[str, str]:
    """Headers that let the next service nest its span under the current run."""
    if not ENABLED:
        return {}
    with contextlib.suppress(Exception):
        if (current := get_current_run_tree()) is not None:
            return current.to_headers()
    return {}


def parent_from(request_headers: Mapping[str, str]) -> dict[str, str] | None:
    """The parent a service should nest under, from an incoming request's headers."""
    found = {k: v for k in TRACE_HEADERS if (v := request_headers.get(k))}
    return found or None
