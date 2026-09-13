"""Diagnosis: retrieval, then the llm_diagnose binding, with citations verified.

Ported from v1 orchestrator_svc (_DiagnosisOut, _verify_citations) and its diagnosis prompt.
The model is given a 2.5 s budget; past it (or unbound, or failing) the rules fault_hint
answers, so diagnosis never holds up a case. A citation to a chunk the model was not shown
is dropped and the diagnosis is marked for a human.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field

from app.index import Graph, Index

BUDGET_S = 2.5
MIN_CONFIDENCE = 0.55

PROMPT = """You are a telecom customer-support fault-diagnosis assistant. You are given a customer ticket
and a set of retrieved knowledge-base excerpts, each tagged with a short chunk id like [c1].

Only use facts present in the ticket text or the retrieved excerpts. Never invent a fault, LED
colour, or error code that is not mentioned. If the evidence is ambiguous, say so in `rationale`
and lower `confidence` rather than guessing.

Known fault ids: {faults}

Ticket (fused, multimodal):
{fused_text}

Retrieved context:
{context}

Every chunk_id in "citations" MUST be one of the chunk ids shown in the retrieved context above.
"""


class CitationOut(BaseModel):
    chunk_id: str
    relevance: float = 0.5


class DiagnosisOut(BaseModel):
    intent: str = "report_fault"
    fault: str | None = None
    confidence: float = 0.0
    alternatives: list[str] = Field(default_factory=list)
    rationale: str = ""
    citations: list[CitationOut] = Field(default_factory=list)


#: Rules fallback: first match wins. Ordered so a light the customer names beats a generic phrase.
FAULT_HINTS: tuple[tuple[str, str], ...] = (
    # A photo (or the customer) naming the power lead beats a generic "cable": it is the power
    # supply, not the WAN line, and the procedures retrieved for it are the power ones.
    (r"power (cable|connector|plug|adapter|socket|lead)|round power plug", "fault_power_supply"),
    (r"red.{0,30}(power|light)|(power|light).{0,30}\bred\b|won.?t (turn|power) on|no power", "fault_power_supply"),
    (r"(blinking|flashing) red|keeps? (restarting|rebooting)|reboot", "fault_firmware_crashloop"),
    (r"amber|orange", "fault_service_suspended"),
    (r"(pon|fibre|fiber|dsl).{0,20}(off|out)|cable|unplugged|wire", "fault_cabling"),
    (r"(charged|bill|invoice|fee).{0,40}(twice|wrong|higher|extra|double)|refund|dispute", "fault_billing_dispute"),
    (r"(slow|drops?|dropping|cuts?).{0,40}(evening|night|sometimes|intermittent)|intermittent|keeps dropping",
     "fault_intermittent_connection"),
    (r"no (signal|coverage)|mobile data", "fault_no_coverage"),
    (r"dial tone|landline", "fault_no_dial_tone"),
    (r"no internet|not working|internet.{0,20}(down|dead)|cannot connect|can.?t connect|line.{0,10}down",
     "fault_line_sync"),
)


def rules(text: str) -> DiagnosisOut:
    low = text.lower()
    for pattern, fault in FAULT_HINTS:
        if re.search(pattern, low):
            return DiagnosisOut(fault=fault, confidence=0.6, rationale="Matched the description against known fault patterns.")
    intent = "billing_question" if re.search(r"bill|pay|charge|invoice", low) else "general_question"
    return DiagnosisOut(intent=intent, fault=None, confidence=0.3, rationale="No known fault pattern in the description.")


def verify(citations: list[CitationOut], known: set[str]) -> tuple[list[dict[str, Any]], bool]:
    kept = [{"chunk_id": c.chunk_id, "source": c.chunk_id.split("#")[0], "quote": ""} for c in citations
            if c.chunk_id in known]
    return kept, len(kept) != len(citations)


async def diagnose(index: Index, graph: Graph, text: str, department: str | None, llm) -> dict[str, Any]:
    hits = index.search(text, k=8)
    expanded = graph.expand(graph.seeds(text))
    faults = sorted(n for n in graph.nodes if graph.nodes[n]["label"] == "Fault")
    context = "\n".join(f"[{c.chunk_id}] {c.text}" for c, _ in hits)[:2500]

    via, out = "rules", rules(text)
    if llm is not None:
        try:
            out = await asyncio.wait_for(llm.generate_json(
                PROMPT.format(faults=", ".join(faults), fused_text=text, context=context or "(none)"),
                DiagnosisOut), timeout=BUDGET_S)
            via = llm.name
        except Exception:  # noqa: BLE001 - timeout, unavailable, bad JSON: the rules answer stands
            out, via = rules(text), "rules (model timed out or failed)"

    graph_fault = next(iter(expanded.get("Fault", [])), None)
    if out.fault is None and graph_fault:
        out = out.model_copy(update={"fault": graph_fault, "confidence": max(out.confidence, 0.55),
                                     "rationale": out.rationale + " The indicator described maps to this fault."})
    if out.fault and out.fault not in faults and not out.fault.startswith("fault_"):
        out = out.model_copy(update={"fault": None})
    kept, dropped = verify(out.citations, {c.chunk_id for c, _ in hits})
    top = [{"chunk_id": c.chunk_id, "text": c.text, "relevance": round(score, 4), "source": c.source}
           for c, score in hits[:3]]
    return {
        "intent": out.intent, "fault": out.fault, "confidence": round(out.confidence, 3), "rationale": out.rationale,
        "citations": kept, "needs_human_diagnosis": out.confidence < MIN_CONFIDENCE or dropped, "via": via,
        "sop_passages": top, "procedures": expanded.get("Procedure", []),
    }


if __name__ == "__main__":
    assert rules("The power light on my router is red").fault == "fault_power_supply"
    assert rules("cable disconnect wela [image a1] The photo shows the router's power cable.").fault == "fault_power_supply"
    assert rules("the cable came out of the router").fault == "fault_cabling"
    assert rules("I was charged twice on this bill").fault == "fault_billing_dispute"
    assert rules("My internet is not working").fault == "fault_line_sync"
    assert rules("internet slows down every evening").fault == "fault_intermittent_connection"
    assert verify([CitationOut(chunk_id="a#0"), CitationOut(chunk_id="made-up")], {"a#0"})[1] is True
    print("diagnose ok")
