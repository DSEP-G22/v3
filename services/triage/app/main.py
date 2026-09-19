"""Triage: department from rules, and two readings of urgency.

- Routing and the rules level come from app/rules.py (v2 cst2/triage/rules.py unchanged).
- customer_priority comes from the llm_triage binding: an LLM (Groq by default) or the distilled
  TriageModel (app/model.py). An LLM that fails or runs past LLM_TIMEOUT_S falls back to the
  model, so the stage never waits on a cloud endpoint. The provider side is scored later by
  grounding, from our records.

The segment, SLA age and repeat-contact inputs come from the prefetched account facts so the
words and the record both count. The ~10 ms of embedding and matrix work runs in a thread, so
it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app import model as triage_model
from app.rules import DEPARTMENTS, triage
from lanka_common.contracts import band_for
from lanka_common.llm import LLMUnavailable, build

CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")
LLM_TIMEOUT_S = float(os.environ.get("TRIAGE_LLM_TIMEOUT_S", "2.0"))
SYSTEM = (
    "You triage messages sent to a Sri Lankan internet provider's support desk. Rate how urgent the "
    "customer's request is on a 1 to 10 scale: 9 or 10 critical (a business or whole area offline, safety, "
    "a long outage), 7 or 8 high (their service is down), 4 to 6 normal (degraded service, a billing "
    "question), 1 to 3 low (general questions, plan enquiries). Judge only the message, not our records. "
    f"Name the department that should own it, one of: {', '.join(DEPARTMENTS)}. Give the reason in one "
    "short sentence an agent can read."
)

app = FastAPI(title="Lanka Link triage", docs_url=None, redoc_url=None)
_lock = threading.Lock()
state: dict[str, Any] = {"model": triage_model.load(), "binding": None, "llm": None, "bound_at": 0.0}
http = httpx.AsyncClient(timeout=2.0)


class Reading(BaseModel):
    level: int = Field(ge=1, le=10)
    department: str = "general"
    reason: str


async def _llm() -> Any:
    """The llm_triage binding, re-read at most every five seconds. None means the TriageModel."""
    if time.monotonic() - state["bound_at"] > 5:
        state["bound_at"] = time.monotonic()
        try:
            r = await http.get(f"{CONTROL_URL}/bindings/llm_triage")
            r.raise_for_status()
            b = r.json()
            if (b["impl"], b["model_version"]) != (state["binding"] or {}).get("key"):
                state["llm"] = None if b["impl"] == "model" else build(b["impl"], b["model_version"], b.get("params"),
                                                                        dict(os.environ))
                state["binding"] = {"key": (b["impl"], b["model_version"])}
        except (httpx.HTTPError, LLMUnavailable, KeyError, ValueError):
            pass  # control unreachable: keep the last known choice
    return state["llm"]


async def _llm_priority(llm: Any, text: str) -> dict[str, Any]:
    started = time.perf_counter()
    r = await asyncio.wait_for(llm.generate_json(text, Reading, SYSTEM), timeout=LLM_TIMEOUT_S)
    return {"level": r.level, "band": band_for(r.level), "score": r.level * 10, "confidence": None,
            "department_hint": r.department if r.department in DEPARTMENTS else None,
            "source": llm.name, "model_version": llm.model, "ms": int((time.perf_counter() - started) * 1000),
            "reasons": [{"signal": "llm", "move": 0, "detail": r.reason}]}


@app.on_event("startup")
def _warm() -> None:
    """Load the embedder before the first ticket so it does not pay the start up cost."""
    if (m := state["model"]) is not None:
        threading.Thread(target=lambda: m.embed("warm up"), daemon=True).start()


class TriageIn(BaseModel):
    fused_text: str
    segment: str = "consumer"
    sla_age_score: float = 0.0
    repeat_contact: bool = False


@app.get("/health")
def health() -> dict[str, Any]:
    m = state["model"]
    return {"status": "ok", "departments": list(DEPARTMENTS), "model": m.version if m else None}


def _rules_priority(level: int) -> dict[str, Any]:
    band = "critical" if level >= 9 else "high" if level >= 7 else "normal" if level >= 4 else "low"
    return {"level": level, "band": band, "score": None, "confidence": None, "source": "rules",
            "reasons": [{"signal": "rules", "move": 0, "detail": "The triage model is not loaded, so the rules level stands."}]}


def _model_priority(body: TriageIn, level: int) -> dict[str, Any]:
    m = state["model"]
    try:
        return m.predict(body.fused_text, segment=body.segment, sla_age_score=body.sla_age_score,
                         repeat_contact=body.repeat_contact) if m else _rules_priority(level)
    except Exception:  # noqa: BLE001 - a model fault degrades to the rules level, never fails the stage
        return _rules_priority(level)


@app.post("/run")
async def run(body: TriageIn) -> dict[str, Any]:
    out = triage(body.fused_text, customer_segment=body.segment, sla_age_score=body.sla_age_score,
                 repeat_contact=body.repeat_contact)
    customer = None
    if llm := await _llm():
        try:
            customer = await _llm_priority(llm, body.fused_text)
        except Exception as exc:  # noqa: BLE001 - any LLM fault (timeout, bad JSON, no key) falls back
            fallback = f"{llm.name} {llm.model} did not answer ({type(exc).__name__}), so the triage model scored it."
    if customer is None:
        customer = await asyncio.to_thread(_model_priority, body, out.level)
        if llm:
            customer["reasons"] = [*customer.get("reasons", []), {"signal": "fallback", "move": 0, "detail": fallback}]
    return {"department": out.department, "base_level": out.level, "routed_by": out.routed_by,
            "signals": out.signals.as_dict(), "reasons": out.reasons, "customer_priority": customer}


@app.post("/reload")
def reload() -> dict[str, Any]:
    """Pick up a model the retrain DAG promoted into TRIAGE_LIVE_DIR."""
    fresh = triage_model.load()
    with _lock:
        state["model"] = fresh
    if fresh is not None:
        fresh.embed("warm up")
    return {"model": fresh.version if fresh else None, "directory": str(fresh.directory) if fresh else None}
