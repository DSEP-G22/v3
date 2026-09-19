"""Staff routes: console (agent, lead), admin, and the simulation test lab.

Everything the console shows comes from the services that own it; this module only joins
and guards. Customer-facing shaping lives in screens.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
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
    http,
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
    conversation, drafts, found, bundle, names = await asyncio.gather(
        _upstream("GET", f"{INQUIRY_URL}/conversations/{c['conversation_id']}"),
        _upstream("GET", f"{RESPONSE_URL}/drafts/{case_id}"),
        _upstream("GET", f"{GROUNDING_URL}/bundles/{case_id}/{c['revision']}/findings"),
        _upstream("GET", f"{GROUNDING_URL}/bundles/{case_id}/{c['revision']}"),
        _upstream("GET", f"{BUSINESS_URL}/subscribers/names", params={"ids": c.get("subscriber_id") or ""}),
        return_exceptions=True,
    )
    names = names if isinstance(names, dict) else {}
    return {
        **detail, "customer": names.get(c.get("subscriber_id") or "", "Unknown customer"),
        "conversation": conversation if not isinstance(conversation, Exception) else None,
        "drafts": drafts["drafts"] if not isinstance(drafts, Exception) else [],
        "grounding": found if not isinstance(found, Exception) else None,
        # The unified ticket as the writer saw it: request, evidence, signals, triage, diagnosis.
        "bundle": bundle if not isinstance(bundle, Exception) else None,
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


class Language(BaseModel):
    language: str


@console.post("/cases/{case_id}/language")
async def set_language(case_id: str, body: Language, p: Principal) -> Any:
    """Staff correct the detected language; the whole pipeline re-runs with it as a new revision."""
    return await _upstream("POST", f"{ORCHESTRATOR_URL}/cases/{case_id}/rerun",
                           json={"language": body.language, "actor": _actor(p)})


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


@admin.get("/feedback")
async def feedback(days: int = 30) -> Any:
    return await _upstream("GET", f"{INQUIRY_URL}/feedback/summary", params={"days": days})


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
async def probe(role: str, deep: bool = False) -> Any:
    return await _upstream("POST", f"{CONTROL_URL}/bindings/{role}/probe", params={"deep": str(deep).lower()},
                           timeout=60)


# -- the model map: every stage of the pipeline, its service and the model it runs ------------------

SERVICES = ("inquiry", "translation", "audio", "image", "business", "orchestrator", "triage", "knowledge",
            "grounding", "response")
SERVICE_URL = {s: os.environ.get(f"{s.upper()}_URL", f"http://{s}:8000") for s in SERVICES}
#: node -> (service, the control stage whose LLM binding it runs, or None). The web map draws the
#: same ids. LLM roles are looked up from control by stage rather than named here: control owns
#: the bindings and only knowledge may resolve the diagnosis one (tests/architecture).
NODES: dict[str, tuple[str, str | None]] = {
    "intake": ("inquiry", None), "translate": ("translation", None), "speech": ("audio", None),
    "vision": ("image", None), "prefetch": ("business", None), "fusion": ("orchestrator", None),
    "triage": ("triage", None), "diagnose": ("knowledge", "reasoning"), "grounding": ("grounding", None),
    "draft": ("response", "response"), "translate_out": ("translation", None),
}
TRIAGE_SAMPLE = "router eke cable ek disconnect wela, internet wada na"


async def _resolve(service: str) -> str | None:
    """The service's URL with its host resolved, or None when it is not running.

    Resolved in Python's thread pool with a short timeout: a container that is not in this
    profile makes Docker's DNS hang, and letting several of those hang in uvloop's small
    resolver pool starves every other check on the map.
    """
    base = SERVICE_URL[service]
    host = base.split("//", 1)[1].split(":", 1)[0].split("/", 1)[0]
    cached = _RESOLVED.get(service)
    if cached and cached[1] > time.monotonic():
        return base.replace(host, cached[0], 1) if cached[0] else None
    try:
        ip = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, socket.gethostbyname, host), 1.5)
    except (OSError, TimeoutError):
        _RESOLVED[service] = ("", time.monotonic() + 30)  # absent: ask Docker again in 30 s
        return None
    _RESOLVED[service] = (ip, time.monotonic() + 60)
    return base.replace(host, ip, 1)


#: service -> (ip or "" when absent, valid until). Keeps a lookup that hangs off every later map load.
_RESOLVED: dict[str, tuple[str, float]] = {}


async def _health(service: str) -> dict[str, Any]:
    started = time.perf_counter()
    if (url := await _resolve(service)) is None:
        return {"status": "off", "ms": None, "detail": {"note": "Not running in this profile."}}
    try:
        r = await http.get(f"{url}/health", timeout=3)
        ms = int((time.perf_counter() - started) * 1000)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return {"status": "up" if r.status_code == 200 else "down", "ms": ms, "detail": body}
    except httpx.HTTPError:
        return {"status": "off", "ms": None, "detail": {"note": "Not running in this profile."}}


@admin.get("/models/map")
async def model_map() -> dict[str, Any]:
    services = await asyncio.gather(*(_health(s) for s in SERVICES))
    bindings = await _upstream("GET", f"{CONTROL_URL}/bindings")
    return {"services": dict(zip(SERVICES, services)), "roles": bindings["roles"]}


@admin.post("/models/verify/{node}")
async def verify(node: str) -> dict[str, Any]:
    """Prove a stage is live: its service answers, and its model actually produces output."""
    if node not in NODES:
        raise HTTPException(404, "No such stage.")
    service, stage = NODES[node]
    role = None
    if stage:
        roles = (await _upstream("GET", f"{CONTROL_URL}/bindings"))["roles"]
        role = next((r["role"] for r in roles if r["stage"] == stage and r["role"].startswith("llm_")), None)
    checks = [{"check": f"{service} service", **(h := await _health(service))}]
    if node == "triage" and h["status"] == "up":
        started = time.perf_counter()
        try:
            r = await http.post(f"{SERVICE_URL['triage']}/run", json={"fused_text": TRIAGE_SAMPLE}, timeout=10)
            cp = r.json().get("customer_priority", {})
            checks.append({"check": "TriageModel prediction", "status": "up" if cp.get("source") == "model" else "down",
                           "ms": int((time.perf_counter() - started) * 1000),
                           "detail": {k: cp.get(k) for k in ("band", "level", "score", "confidence", "model_version")}})
        except httpx.HTTPError as exc:
            checks.append({"check": "TriageModel prediction", "status": "down", "ms": None, "detail": {"error": str(exc)}})
    if node in ("translate", "translate_out") and h["status"] == "up":
        # A real sentence through the bound backend, both directions named by the admin's binding.
        path, body = (("/run", {"text": "මගේ අන්තර්ජාලය වැඩ කරන්නේ නැහැ"}) if node == "translate"
                      else ("/run_out", {"text": "Please restart your router.", "target": "si"}))
        started = time.perf_counter()
        try:
            r = (await http.post(f"{SERVICE_URL['translation']}{path}", json=body, timeout=20)).json()
            out = r.get("text_en") or r.get("text") or ""
            checks.append({"check": "Translation", "status": "up" if out and out != body["text"] else "down",
                           "ms": int((time.perf_counter() - started) * 1000),
                           "detail": {"backend": r.get("backend"), "output": out[:80]}})
        except httpx.HTTPError as exc:
            checks.append({"check": "Translation", "status": "down", "ms": None, "detail": {"error": str(exc)}})
    if role and role.startswith("llm_"):
        p = await _upstream("POST", f"{CONTROL_URL}/bindings/{role}/probe", params={"deep": "true"}, timeout=60)
        checks.append({"check": f"{role} generation", "status": "up" if p["status"] == "reachable" else "down",
                       "ms": p["ms"], "detail": {"result": p["detail"]}})
    statuses = {c["status"] for c in checks}
    overall = "active" if statuses == {"up"} else "off" if "off" in statuses else "inactive"
    return {"node": node, "status": overall, "checks": checks}


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


@lab.get("/requests")
async def lab_requests(q: str = "") -> Any:
    return await traces(q)


@lab.get("/requests/{case_id}")
async def lab_request(case_id: str) -> Any:
    return await trace(case_id)


@lab.get("/runs")
async def runs() -> Any:
    return await _upstream("GET", f"{ORCHESTRATOR_URL}/cases", params={"tab": "all", "origin": "sim_test", "limit": 30})
