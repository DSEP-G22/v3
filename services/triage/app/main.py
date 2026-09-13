"""Triage: department from rules, and two readings of urgency.

- Routing and the rules level come from app/rules.py (v2 cst2/triage/rules.py unchanged).
- customer_priority comes from the distilled TriageModel (app/model.py): how urgent the
  request itself is. The provider side is scored later by grounding, from our records.

The segment, SLA age and repeat-contact inputs come from the prefetched account facts so the
words and the record both count. /run is a sync handler: FastAPI runs it in its threadpool,
so the ~10 ms of embedding and matrix work never blocks the event loop.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from app import model as triage_model
from app.rules import DEPARTMENTS, triage

app = FastAPI(title="Lanka Link triage", docs_url=None, redoc_url=None)
_lock = threading.Lock()
state: dict[str, Any] = {"model": triage_model.load()}


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


@app.post("/run")
def run(body: TriageIn) -> dict[str, Any]:
    out = triage(body.fused_text, customer_segment=body.segment, sla_age_score=body.sla_age_score,
                 repeat_contact=body.repeat_contact)
    m = state["model"]
    try:
        customer = m.predict(body.fused_text, segment=body.segment, sla_age_score=body.sla_age_score,
                             repeat_contact=body.repeat_contact) if m else _rules_priority(out.level)
    except Exception:  # noqa: BLE001 - a model fault degrades to the rules level, never fails the stage
        customer = _rules_priority(out.level)
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
