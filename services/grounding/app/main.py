"""Grounding: /build assembles the frozen ContextBundle; the response service reads it back.

Called by the orchestrator after triage and diagnosis, with the prefetched facts. The only
I/O beyond storing the bundle is the LED lookup, and only when a photo showed a lit light.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import findings
from app.actions import load_registry, select
from app.assemble import build, led_query
from app.plan import PlanResolver, load_file
from lanka_common import bus
from lanka_common.contracts import (
    Diagnosis,
    LedState,
    Payload,
    SopPassage,
    Transcript,
    Triage,
    VisualSummary,
)
from lanka_common.db import POOLER_KWARGS, parse_neon_key

BUSINESS_URL = os.environ.get("BUSINESS_URL", "http://business:8000")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")

DDL = """
CREATE TABLE IF NOT EXISTS grounding.context_bundle (
    case_id    text NOT NULL,
    revision   integer NOT NULL,
    bundle     jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, revision)
);
CREATE TABLE IF NOT EXISTS grounding.org_fact_call (
    case_id  text NOT NULL,
    revision integer NOT NULL,
    tool     text NOT NULL,
    status   text NOT NULL CHECK (status IN ('used', 'prefetched_unused', 'fetched_extra', 'missing')),
    found    boolean NOT NULL DEFAULT false,
    PRIMARY KEY (case_id, revision, tool)
);
"""


class Runtime:
    pool: asyncpg.Pool
    resolver: PlanResolver = PlanResolver()
    registry = load_registry()
    bundles: dict[str, Any] = {}


rt = Runtime()
http = httpx.AsyncClient(timeout=5)


async def _reload_control() -> None:
    """Plan and action registry from the control service; the files are the fallback."""
    with contextlib.suppress(Exception):
        r = await http.get(f"{CONTROL_URL}/grounding-plan")
        r.raise_for_status()
        rt.resolver = PlanResolver(r.json()["plan"])
    with contextlib.suppress(Exception):
        r = await http.get(f"{CONTROL_URL}/action-registry")
        r.raise_for_status()
        rt.registry = load_registry(r.json())


async def _on_control(msg) -> None:
    if json.loads(msg.data).get("kind") in ("plan", "actions"):
        await _reload_control()
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=1, max_size=6,
                                        **POOLER_KWARGS)
    await rt.pool.execute(DDL)
    await _reload_control()
    nc, js = await bus.connect()
    await js.subscribe("control.changed", durable="grounding", cb=_on_control, manual_ack=True)
    yield
    await nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link grounding", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "departments": sorted((rt.resolver.doc.get("by_department") or {}))}


class BuildIn(BaseModel):
    case_id: str
    revision: int
    subscriber_id: str | None
    payload: dict[str, Any]
    triage: dict[str, Any]
    diagnosis: dict[str, Any] | None = None
    prefetch: dict[str, dict[str, Any]] = Field(default_factory=dict)
    visual: list[dict[str, Any] | None] = Field(default_factory=list)
    transcripts: list[dict[str, Any] | None] = Field(default_factory=list)


def _payload(body: BuildIn) -> Payload:
    p = body.payload
    visuals = [VisualSummary(attachment_id=v.get("attachment_id", ""), summary_text=v.get("summary", ""),
                             confidence=v.get("confidence", 0.0),
                             led_states=[LedState(label="", colour=led["colour"]) for led in v.get("leds", [])])
               for v in body.visual if v]
    transcripts = [Transcript(attachment_id=t.get("attachment_id", ""), text=t.get("text", ""),
                              text_en=t.get("text_en", t.get("text", "")), language=t.get("language", "und"),
                              confidence=t.get("confidence", 0.0), low_confidence=t.get("low_confidence", False))
                   for t in body.transcripts if t]
    return Payload(case_id=body.case_id, revision=body.revision, visual_summaries=visuals, transcripts=transcripts,
                   **{k: v for k, v in p.items() if k in Payload.model_fields and k not in ("visual_summaries", "transcripts")})


@app.post("/run")
async def run(body: BuildIn) -> dict[str, Any]:
    started = time.perf_counter()
    payload = _payload(body)
    diagnosis = Diagnosis(**{k: v for k, v in (body.diagnosis or {}).items() if k in Diagnosis.model_fields}) \
        if body.diagnosis else None
    sop = [SopPassage(**s) for s in (body.diagnosis or {}).get("sop_passages", [])]
    triage = Triage(**{k: v for k, v in body.triage.items() if k in Triage.model_fields})

    extra: dict[str, dict[str, Any]] = {}
    if (q := led_query(payload, body.prefetch.get("get_cpe_diagnostics"))) and body.subscriber_id:
        with contextlib.suppress(Exception):
            r = await http.post(f"{BUSINESS_URL}/tools:batch", json={
                "subscriber_ref": body.subscriber_id, "calls": [{"name": "get_device_led_semantics", "args": q}]})
            extra["get_device_led_semantics"] = r.json()["results"]["get_device_led_semantics"]

    bundle, plan, unused = build(
        case_id=body.case_id, revision=body.revision, payload=payload, triage=triage, diagnosis=diagnosis,
        sop_passages=sop, prefetch=body.prefetch, extra=extra, registry=rt.registry, resolver=rt.resolver,
        build_ms=int((time.perf_counter() - started) * 1000),
    )
    doc = bundle.model_dump(mode="json")
    rt.bundles[f"{body.case_id}:{body.revision}"] = doc  # hot copy for the response service
    asyncio.create_task(_persist(bundle, doc, unused, set(extra)))
    top = findings.summarise(bundle)
    return {
        "bundle_id": f"{body.case_id}:{body.revision}", "department": bundle.department,
        "priority_level": bundle.priority.level, "band": bundle.priority.band,
        "headline": findings.headline(bundle), "findings": top[:3],
        "sufficient": bundle.completeness.sufficient, "missing": bundle.completeness.missing,
        "recommended_action": select(bundle.permitted_actions, bundle.org_facts, body.case_id),
        "tools": list(plan.tools), "prefetched_unused": unused, "ms": int((time.perf_counter() - started) * 1000),
    }


async def _persist(bundle, doc: dict[str, Any], unused: list[str], extra: set[str]) -> None:
    rows = [(bundle.case_id, bundle.revision, f.tool, "fetched_extra" if f.tool in extra else
             "used" if f.prefetched else "missing", f.found) for f in bundle.org_facts]
    rows += [(bundle.case_id, bundle.revision, t, "prefetched_unused", False) for t in unused]
    with contextlib.suppress(Exception):
        async with rt.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO grounding.context_bundle (case_id, revision, bundle) VALUES ($1, $2, $3)
                   ON CONFLICT (case_id, revision) DO UPDATE SET bundle = EXCLUDED.bundle""",
                bundle.case_id, bundle.revision, json.dumps(doc))
            await conn.executemany(
                """INSERT INTO grounding.org_fact_call (case_id, revision, tool, status, found)
                   VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""", rows)


@app.get("/bundles/{case_id}/{revision}")
async def get_bundle(case_id: str, revision: int) -> dict[str, Any]:
    if doc := rt.bundles.get(f"{case_id}:{revision}"):
        return doc
    raw = await rt.pool.fetchval(
        "SELECT bundle FROM grounding.context_bundle WHERE case_id = $1 AND revision = $2", case_id, revision)
    if raw is None:
        raise HTTPException(404, "No bundle for that case revision.")
    return json.loads(raw)


@app.get("/bundles/{case_id}/{revision}/findings")
async def bundle_findings(case_id: str, revision: int) -> dict[str, Any]:
    from lanka_common.contracts import ContextBundle

    bundle = ContextBundle.model_validate(await get_bundle(case_id, revision))
    return {"headline": findings.headline(bundle), "findings": findings.summarise(bundle),
            "recommended_action": select(bundle.permitted_actions, bundle.org_facts, case_id),
            "priority": bundle.priority.model_dump(), "sla_display": bundle.sla.display,
            "completeness": bundle.completeness.model_dump()}


@app.get("/plan/preview")
async def preview(department: str, fault: str | None = None) -> dict[str, Any]:
    plan = rt.resolver.resolve(department, fault)
    return {"tools": list(plan.tools), "required_sections": list(plan.required_sections),
            "file_fallback": rt.resolver.doc == load_file()}
