"""Staff routes: console (agent, lead), admin, and the simulation test lab.

Everything the console shows comes from the services that own it; this module only joins
and guards. Customer-facing shaping lives in screens.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import nats
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.main import (
    BUSINESS_URL,
    INQUIRY_URL,
    NATS_URL,
    ORCHESTRATOR_URL,
    STAFF,
    Principal,
    _upstream,
    require,
)

GROUNDING_URL = os.environ.get("GROUNDING_URL", "http://grounding:8000")
RESPONSE_URL = os.environ.get("RESPONSE_URL", "http://response:8000")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")

console = APIRouter(prefix="/api/console", dependencies=[require(*STAFF)])
admin = APIRouter(prefix="/api/admin", dependencies=[require("admin")])
lab = APIRouter(prefix="/api/lab", dependencies=[require("admin", "operator")])


def _actor(p: dict[str, Any]) -> str:
    return f"{p.get('name') or p.get('email')} ({p.get('role')})"


# -- console ----------------------------------------------------------------------------------------


@console.get("/cases")
async def queue(tab: str = "needs_approval", q: str = "") -> dict[str, Any]:
    data = await _upstream("GET", f"{ORCHESTRATOR_URL}/cases", params={"tab": tab, "q": q})
    ids = ",".join({c["subscriber_id"] for c in data["cases"] if c.get("subscriber_id")})
    names = await _upstream("GET", f"{BUSINESS_URL}/subscribers/names", params={"ids": ids}) if ids else {}
    for c in data["cases"]:
        c["customer"] = names.get(c.get("subscriber_id") or "", "Unknown customer")
    return data


@console.get("/cases/{case_id}")
async def case(case_id: str) -> dict[str, Any]:
    detail = await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}")
    c = detail["case"]
    conversation, drafts, found = await asyncio.gather(
        _upstream("GET", f"{INQUIRY_URL}/conversations/{c['conversation_id']}"),
        _upstream("GET", f"{RESPONSE_URL}/drafts/{case_id}"),
        _upstream("GET", f"{GROUNDING_URL}/bundles/{case_id}/{c['revision']}/findings"),
        return_exceptions=True,
    )
    names = await _upstream("GET", f"{BUSINESS_URL}/subscribers/names", params={"ids": c.get("subscriber_id") or ""}) \
        if c.get("subscriber_id") else {}
    return {
        **detail, "customer": names.get(c.get("subscriber_id") or "", "Unknown customer"),
        "conversation": conversation if not isinstance(conversation, Exception) else None,
        "drafts": drafts["drafts"] if not isinstance(drafts, Exception) else [],
        "grounding": found if not isinstance(found, Exception) else None,
    }


class Approve(BaseModel):
    text_en: str | None = None


@console.post("/cases/{case_id}/approve")
async def approve(case_id: str, body: Approve, p: Principal) -> dict[str, Any]:
    c = (await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}"))["case"]
    result = await _upstream("POST", f"{RESPONSE_URL}/drafts/{case_id}/{c['revision']}/decide", json={
        "approved": True, "actor": _actor(p), "conversation_id": c["conversation_id"], "user_id": c["user_id"],
        "text_en": body.text_en,
    })
    if action := result.get("action"):
        result["executed"] = await _upstream("POST", f"{BUSINESS_URL}/actions/execute", json={
            "action_id": action["action_id"], "parameters": action["parameters"], "case_id": case_id,
            "actor": _actor(p)})
    return result


class SendBack(BaseModel):
    reason: str


@console.post("/cases/{case_id}/send-back")
async def send_back(case_id: str, body: SendBack, p: Principal) -> dict[str, Any]:
    c = (await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}"))["case"]
    return await _upstream("POST", f"{RESPONSE_URL}/drafts/{case_id}/{c['revision']}/decide", json={
        "approved": False, "actor": _actor(p), "conversation_id": c["conversation_id"], "user_id": c["user_id"],
        "note": body.reason})


@console.post("/cases/{case_id}/escalate")
async def escalate(case_id: str, p: Principal) -> Any:
    return await _upstream("POST", f"{ORCHESTRATOR_URL}/cases/{case_id}/escalate", params={"actor": _actor(p)})


@console.get("/cases/{case_id}/preview")
async def preview(case_id: str, lang: str) -> Any:
    c = (await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}"))["case"]
    return await _upstream("POST", f"{RESPONSE_URL}/preview",
                           params={"case_id": case_id, "revision": c["revision"], "lang": lang})


async def _nats_sse(request: Request, *subjects: str) -> StreamingResponse:
    nc = await nats.connect(NATS_URL)
    queue: asyncio.Queue = asyncio.Queue()
    for subject in subjects:
        await nc.subscribe(subject, cb=queue.put)

    async def events() -> AsyncIterator[bytes]:
        try:
            yield b": connected\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                kind = "token" if msg.subject.endswith(".stream") else msg.subject.rsplit(".", 1)[-1]
                data = msg.data.decode() if kind == "token" else json.dumps(json.loads(msg.data or b"{}"))
                yield f"event: {kind}\ndata: {json.dumps(data) if kind == 'token' else data}\n\n".encode()
        finally:
            await nc.drain()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@console.get("/cases/{case_id}/stream")
async def case_stream(case_id: str, request: Request) -> StreamingResponse:
    """Raw draft tokens, console only. Customers only ever get compliance-cleared sentences."""
    return await _nats_sse(request, f"case.{case_id}.stream", f"sim.case.{case_id}")


# -- admin ------------------------------------------------------------------------------------------


@admin.get("/overview")
async def overview() -> Any:
    return await _upstream("GET", f"{ORCHESTRATOR_URL}/stats")


@admin.get("/models")
async def models() -> Any:
    return await _upstream("GET", f"{CONTROL_URL}/bindings")


@admin.get("/models/history")
async def models_history(role: str | None = None) -> Any:
    return await _upstream("GET", f"{CONTROL_URL}/bindings-history", params={"role": role} if role else {})


class Rebind(BaseModel):
    impl: str
    model_version: str
    params: dict[str, Any] = {}
    reason: str = ""


@admin.put("/models/{role}")
async def rebind(role: str, body: Rebind, p: Principal) -> Any:
    return await _upstream("PUT", f"{CONTROL_URL}/bindings/{role}", json={**body.model_dump(), "actor": _actor(p)})


@admin.post("/models/{role}/probe")
async def probe(role: str) -> Any:
    return await _upstream("POST", f"{CONTROL_URL}/bindings/{role}/probe")


@admin.get("/autoreply")
async def autoreply() -> Any:
    return await _upstream("GET", f"{CONTROL_URL}/autoreply")


@admin.put("/autoreply/{department}")
async def set_autoreply(department: str, request: Request, p: Principal) -> Any:
    body = await request.json()
    return await _upstream("PUT", f"{CONTROL_URL}/autoreply/{department}", json={**body, "actor": _actor(p)})


@admin.get("/grounding-plan")
async def plan() -> Any:
    return await _upstream("GET", f"{CONTROL_URL}/grounding-plan")


@admin.put("/grounding-plan")
async def put_plan(request: Request, p: Principal) -> Any:
    return await _upstream("PUT", f"{CONTROL_URL}/grounding-plan",
                           json={"plan": (await request.json())["plan"], "actor": _actor(p)})


class DryRun(BaseModel):
    department: str
    fault: str | None = None
    subscriber_ref: str


@admin.post("/grounding-plan/dry-run")
async def dry_run(body: DryRun) -> dict[str, Any]:
    """Resolve the plan and run it against a real subscriber, without a case."""
    preview = await _upstream("GET", f"{GROUNDING_URL}/plan/preview",
                              params={"department": body.department, **({"fault": body.fault} if body.fault else {})})
    facts = await _upstream("POST", f"{BUSINESS_URL}/tools:batch", json={
        "subscriber_ref": body.subscriber_ref, "calls": [{"name": t, "args": {}} for t in preview["tools"]
                                                         if t != "get_device_led_semantics"]})
    return {**preview, "facts": [{"tool": t, "found": r.get("found"),
                                  "signals": sorted(k for k, v in r.items() if v is True and k != "found")}
                                 for t, r in facts["results"].items()]}


@admin.get("/traces")
async def traces(q: str = "") -> Any:
    return await _upstream("GET", f"{ORCHESTRATOR_URL}/cases", params={"tab": "all", "q": q, "limit": 50})


@admin.get("/traces/{case_id}")
async def trace(case_id: str) -> Any:
    detail = await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}")
    try:
        detail["bundle"] = await _upstream("GET", f"{GROUNDING_URL}/bundles/{case_id}/{detail['case']['revision']}")
    except HTTPException:
        detail["bundle"] = None
    return detail


# -- simulation test lab ------------------------------------------------------------------------------


def shadow(subscriber_id: str) -> str:
    """Test inquiries belong to a shadow user, so they never appear in the persona's own chat."""
    return f"sim-{subscriber_id}"


@lab.post("/inquiries")
async def test_inquiry(request: Request) -> Any:
    form = await request.form()
    sub = str(form.get("subscriber_ref") or "")
    if not sub:
        raise HTTPException(422, "Choose a customer.")
    files = [("files", (f.filename or "file", await f.read(), f.content_type or "application/octet-stream"))
             for f in form.getlist("files") if hasattr(f, "read")]
    return await _upstream("POST", f"{INQUIRY_URL}/messages", data={
        "user_id": shadow(sub), "subscriber_id": sub, "origin": "sim_test", "text": str(form.get("text") or ""),
        "language": str(form.get("language") or "") or None}, files=files or None)


@lab.get("/stream/{subscriber_id}")
async def lab_stream(subscriber_id: str, request: Request) -> StreamingResponse:
    return await _nats_sse(request, f"user.{shadow(subscriber_id)}.>")


@lab.get("/cases/{case_id}")
async def lab_case(case_id: str) -> dict[str, Any]:
    return await case(case_id)


@lab.get("/runs")
async def runs() -> Any:
    return await _upstream("GET", f"{ORCHESTRATOR_URL}/cases", params={"tab": "all", "origin": "sim_test", "limit": 30})
