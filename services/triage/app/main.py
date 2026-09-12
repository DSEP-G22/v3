"""Triage: department and a 1 to 10 base level from the fused text. Rules, no model (~2 ms).

app/rules.py is v2 cst2/triage/rules.py unchanged. The segment, SLA age and repeat-contact
inputs come from the prefetched account facts so the words and the record both count.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from app.rules import DEPARTMENTS, triage

app = FastAPI(title="Lanka Link triage", docs_url=None, redoc_url=None)


class TriageIn(BaseModel):
    fused_text: str
    segment: str = "consumer"
    sla_age_score: float = 0.0
    repeat_contact: bool = False


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "departments": list(DEPARTMENTS)}


@app.post("/run")
async def run(body: TriageIn) -> dict[str, Any]:
    out = triage(body.fused_text, customer_segment=body.segment, sla_age_score=body.sla_age_score,
                 repeat_contact=body.repeat_contact)
    return {"department": out.department, "base_level": out.level, "routed_by": out.routed_by,
            "signals": out.signals.as_dict(), "reasons": out.reasons}
