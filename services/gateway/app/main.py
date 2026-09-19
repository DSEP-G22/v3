"""Gateway BFF: JWT verification, RBAC, screen routes, SSE fan-out.

Customer routes resolve the subscriber from the session, never from a parameter, so no
customer can reach an account that is not theirs.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any, Literal

import httpx
import nats
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import screens
from app.jwks import InvalidToken, JwksVerifier

AUTH_URL = os.environ.get("AUTH_INTERNAL_URL", "http://auth:3000")
BUSINESS_URL = os.environ.get("BUSINESS_URL", "http://business:8000")
PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://payments:8000")
INQUIRY_URL = os.environ.get("INQUIRY_URL", "http://inquiry:8000")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://orchestrator:8000")
ISSUER = os.environ.get("BETTER_AUTH_URL", "http://localhost:8080")
NATS_URL = os.environ.get("NATS_URL", "nats://nats:4222")
LINK_TTL_S = 60

STAFF = ("agent", "lead", "admin", "operator")

http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0),
                         limits=httpx.Limits(max_keepalive_connections=50, keepalive_expiry=20.0))
cache = redis.from_url(os.environ.get("VALKEY_URL", "redis://valkey:6379/0"), decode_responses=True)


async def _fetch_jwks() -> dict[str, Any]:
    r = await http.get(f"{AUTH_URL}/api/auth/jwks")
    r.raise_for_status()
    return r.json()


verifier = JwksVerifier(_fetch_jwks, ISSUER)
app = FastAPI(title="Lanka Link gateway", docs_url=None, redoc_url=None)


async def principal(authorization: str = Header(default="")) -> dict[str, Any]:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in to continue.")
    try:
        return await verifier.verify(token.strip())
    except InvalidToken:
        raise HTTPException(401, "Your session has expired. Sign in again.") from None


Principal = Annotated[dict[str, Any], Depends(principal)]


def require(*roles: str):
    async def guard(p: Principal) -> dict[str, Any]:
        if p.get("role") not in roles:
            raise HTTPException(403, "You do not have access to this area.")
        return p

    return Depends(guard)


async def _upstream(method: str, url: str, **kw: Any) -> Any:
    try:
        r = await http.request(method, url, **kw)
    except httpx.HTTPError:
        raise HTTPException(502, "That part of the service is not answering. Try again shortly.") from None
    if r.status_code >= 400:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        raise HTTPException(r.status_code, detail or "Something went wrong.")
    return r.json()


async def subscriber_of(p: dict[str, Any]) -> str | None:
    """The session's subscriber, via Valkey. subscriber_id is deliberately not in the JWT."""
    key = f"link:{p['sub']}"
    if (cached := await cache.get(key)) is not None:
        return cached or None
    r = await http.get(f"{BUSINESS_URL}/links/{p['sub']}")
    sid = r.json()["subscriber_id"] if r.status_code == 200 else ""
    # A miss is cached briefly too, so onboarding polls do not hammer business.
    await cache.set(key, sid, ex=LINK_TTL_S if sid else 5)
    return sid or None


async def linked(p: Principal) -> tuple[dict[str, Any], str]:
    if p.get("role") != "customer":
        raise HTTPException(403, "This is the customer area.")
    sid = await subscriber_of(p)
    if sid is None:
        raise HTTPException(409, "You do not have a service with us yet.")
    return p, sid


Customer = Annotated[tuple[dict[str, Any], str], Depends(linked)]


async def batch(sid: str, names: list[str], **args: dict[str, Any]) -> dict[str, Any]:
    body = {"subscriber_ref": sid, "calls": [{"name": n, "args": args.get(n, {})} for n in names]}
    return (await _upstream("POST", f"{BUSINESS_URL}/tools:batch", json=body))["results"]


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
async def me(p: Principal) -> dict[str, Any]:
    sid = await subscriber_of(p) if p.get("role") == "customer" else None
    return {"id": p["sub"], "email": p.get("email"), "name": p.get("name"), "role": p.get("role"),
            "has_service": sid is not None}


# -- public -------------------------------------------------------------------------------------


@app.get("/api/public/plans")
async def public_plans() -> Any:
    return await _upstream("GET", f"{BUSINESS_URL}/plans")


@app.get("/api/public/coverage")
async def public_coverage() -> Any:
    return await _upstream("GET", f"{BUSINESS_URL}/coverage")


# -- customer app -------------------------------------------------------------------------------


@app.get("/api/app/overview")
async def overview(c: Customer) -> dict[str, Any]:
    _, sid = c
    r = await batch(sid, screens.OVERVIEW_TOOLS)
    profile = r["get_subscriber_profile"]
    return {
        "first_name": profile.get("preferred_name"),
        "service": screens.service_summary(r["get_circuit_status"], r["get_active_outages_for"]),
        "billing": screens.billing_summary(r["get_payment_status"]),
        "plan": screens.plan_summary(r["get_plan_and_entitlements"], r["get_usage_summary"]),
    }


@app.get("/api/app/billing")
async def billing(c: Customer) -> dict[str, Any]:
    _, sid = c
    r = await batch(sid, screens.BILLING_TOOLS, get_billing_history={"months": 12})
    history = r["get_billing_history"]
    ledger = r.get("get_ledger_window") or {}
    return {
        "summary": screens.billing_summary(r["get_payment_status"]),
        "invoices": [{k: i.get(k) for k in ("invoice_no", "period_display", "issued_display", "due_display",
                                            "total", "total_display", "status", "status_display")}
                     for i in history.get("invoices", [])],
        "latest": r["get_last_invoice_breakdown"],
        "activity": [{k: e.get(k) for k in ("posted_display", "description", "kind", "debit_display", "credit_display",
                                            "balance_after_display")} for e in (ledger.get("entries") or [])[:12]],
        "change_display": history.get("change_display"),
    }


@app.get("/api/app/usage")
async def usage(c: Customer) -> dict[str, Any]:
    _, sid = c
    r, series = await asyncio.gather(
        batch(sid, screens.USAGE_TOOLS),
        _upstream("GET", f"{BUSINESS_URL}/customers/{sid}/series"),
    )
    u = r["get_usage_summary"]
    return {
        "used_display": u.get("data_used_display"), "allowance_display": u.get("allowance_display"),
        "cycle_ends_display": u.get("cycle_ends_display"), "daily": series["usage"],
        "health": screens.health_sentence(r["get_line_quality"]),
    }


@app.get("/api/app/plan")
async def plan(c: Customer) -> dict[str, Any]:
    _, sid = c
    r, catalogue = await asyncio.gather(
        batch(sid, ["get_plan_and_entitlements", "get_usage_summary"]),
        _upstream("GET", f"{BUSINESS_URL}/plans"),
    )
    return {"current": screens.plan_summary(r["get_plan_and_entitlements"], r["get_usage_summary"]),
            "in_contract": r["get_plan_and_entitlements"].get("in_contract"),
            "plans": catalogue["plans"]}


class OrderIn(BaseModel):
    kind: Literal["new_service", "plan_change"] = "new_service"
    plan_code: str
    city: str | None = None
    address_line: str = Field(default="", max_length=160)
    language: Literal["en", "si", "ta"] = "en"
    # Where and when to install, for a new service.
    landmark: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=20, pattern=r"^[0-9+ ]*$")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    install_date: date | None = None
    install_slot: Literal["", "morning", "afternoon", "evening"] = ""


@app.post("/api/app/orders", status_code=201)
async def create_order(body: OrderIn, p: Principal) -> Any:
    if p.get("role") != "customer":
        raise HTTPException(403, "Only customers can place orders.")
    order = await _upstream("POST", f"{BUSINESS_URL}/orders", json={
        **body.model_dump(mode="json"), "user_id": p["sub"], "email": p.get("email") or "", "full_name": p.get("name") or "",
    })
    return order


@app.get("/api/app/orders/{order_id}")
async def get_order(order_id: str, p: Principal) -> Any:
    return await _upstream("GET", f"{BUSINESS_URL}/orders/{order_id}", params={"user_id": p["sub"]})


@app.get("/api/app/intents/{intent_id}")
async def get_intent(intent_id: str, p: Principal) -> Any:
    return await _upstream("GET", f"{PAYMENTS_URL}/intents/{intent_id}", params={"user_id": p["sub"]})


class PayIn(BaseModel):
    method: Literal["card_4242", "lankaqr"]


@app.post("/api/app/intents/{intent_id}/pay")
async def pay_intent(intent_id: str, body: PayIn, p: Principal) -> Any:
    result = await _upstream("POST", f"{PAYMENTS_URL}/intents/{intent_id}/pay",
                             json={"user_id": p["sub"], "method": body.method})
    await cache.delete(f"link:{p['sub']}")  # provisioning may link this user in a moment
    return result


@app.post("/api/app/balance/pay", status_code=201)
async def pay_balance(c: Customer) -> Any:
    p, _ = c
    return await _upstream("POST", f"{BUSINESS_URL}/accounts/balance/intent", json={"user_id": p["sub"]})


@app.post("/api/app/invoices/{invoice_id}/pay", status_code=201)
async def pay_invoice(invoice_id: str, c: Customer) -> Any:
    p, _ = c
    return await _upstream("POST", f"{BUSINESS_URL}/invoices/{invoice_id}/intent", json={"user_id": p["sub"]})


# -- chat ---------------------------------------------------------------------------------------


@app.post("/api/app/messages", status_code=201)
async def send_message(request: Request, c: Customer) -> Any:
    """Multipart passthrough; identity always comes from the session, never the form."""
    p, sid = c
    form = await request.form()
    files = [("files", (f.filename or "file", await f.read(), f.content_type or "application/octet-stream"))
             for f in form.getlist("files") if hasattr(f, "read")]
    data = {"user_id": p["sub"], "subscriber_id": sid, "origin": "customer", "text": str(form.get("text") or "")}
    # No ticket id opens a new ticket; with one, the message is a reply on that ticket.
    for key in ("conversation_id", "subject", "category"):
        if value := str(form.get(key) or "").strip():
            data[key] = value
    return await _upstream("POST", f"{INQUIRY_URL}/messages", data=data, files=files or None)


# -- tickets ------------------------------------------------------------------------------------

#: What a case state means to the customer. Never the state name itself.
TICKET_STAGE = {"RECEIVED": "Received", "PROCESSING": "Reading your message", "AGGREGATED": "Reading your message",
                "TRIAGED": "Checking your account", "DIAGNOSED": "Writing a reply", "AWAITING_APPROVAL": "With our team",
                "IN_REVIEW": "With our team", "RESOLVED": "Answered", "CLOSED": "Closed"}


@app.get("/api/app/tickets")
async def my_tickets(c: Customer) -> Any:
    p, _ = c
    return await _upstream("GET", f"{INQUIRY_URL}/tickets", params={"user_id": p["sub"]})


@app.get("/api/app/tickets/{ticket_id}")
async def my_ticket(ticket_id: str, c: Customer) -> Any:
    p, _ = c
    data = await _upstream("GET", f"{INQUIRY_URL}/tickets/{ticket_id}", params={"user_id": p["sub"]})
    stage = None
    if case_id := data["ticket"].get("open_case_id"):
        try:
            state = (await _upstream("GET", f"{ORCHESTRATOR_URL}/cases/{case_id}"))["case"]["state"]
            stage = TICKET_STAGE.get(state)
        except HTTPException:
            stage = None
    return {**data, "stage": stage}


class TicketFeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


@app.post("/api/app/tickets/{ticket_id}/feedback")
async def ticket_feedback(ticket_id: str, body: TicketFeedbackIn, c: Customer) -> Any:
    p, _ = c
    return await _upstream("POST", f"{INQUIRY_URL}/tickets/{ticket_id}/feedback",
                           json={**body.model_dump(), "user_id": p["sub"]})


@app.post("/api/app/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: str, c: Customer) -> Any:
    p, _ = c
    out = await _upstream("POST", f"{INQUIRY_URL}/tickets/{ticket_id}/close", params={"user_id": p["sub"]})
    if case_id := out.get("open_case_id"):
        try:
            await _upstream("POST", f"{ORCHESTRATOR_URL}/cases/{case_id}/close",
                            params={"user_id": p["sub"], "reason": "solved"})
        except HTTPException:
            pass  # the case already closed; the ticket state is what the customer sees
    return {"id": out["id"], "status": out["status"]}


@app.get("/api/app/notices")
async def notices(c: Customer) -> dict[str, Any]:
    """Known issues on our side, as ready made templates the ticket screens can show."""
    _, sid = c
    return {"notices": screens.notices(await batch(sid, screens.NOTICE_TOOLS))}


@app.get("/api/app/conversation")
async def my_conversation(c: Customer) -> Any:
    p, _ = c
    return await _upstream("GET", f"{INQUIRY_URL}/conversations/mine", params={"user_id": p["sub"]})


@app.get("/api/app/attachments/{attachment_id}")
async def my_attachment(attachment_id: str, p: Principal) -> Response:
    params = {} if p.get("role") in STAFF else {"user_id": p["sub"]}
    r = await http.get(f"{INQUIRY_URL}/attachments/{attachment_id}", params=params)
    if r.status_code != 200:
        raise HTTPException(404, "Not found.")
    return Response(r.content, media_type=r.headers.get("content-type"),
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/app/cases/{case_id}/solved")
async def solved(case_id: str, c: Customer) -> Any:
    p, _ = c
    return await _upstream("POST", f"{ORCHESTRATOR_URL}/cases/{case_id}/close",
                           params={"user_id": p["sub"], "reason": "solved"})


# -- staff ----------------------------------------------------------------------------------------


@app.get("/api/console/ping", dependencies=[require(*STAFF)])
async def console_ping() -> dict[str, bool]:
    return {"ok": True}


def _mount_staff() -> None:
    from app import staff  # late: staff.py imports helpers from this module

    for router in (staff.console, staff.admin, staff.lab):
        app.include_router(router)


class LinkIn(BaseModel):
    user_id: str
    subscriber_ref: str


@app.post("/api/admin/links", dependencies=[require("admin")])
async def admin_link(body: LinkIn) -> Any:
    result = await _upstream("POST", f"{BUSINESS_URL}/links", json={**body.model_dump(), "linked_by": "admin"})
    await cache.delete(f"link:{body.user_id}")
    return result


@app.api_route("/api/sim/{path:path}", methods=["GET", "POST", "DELETE"],
               dependencies=[require("admin", "operator")])
async def sim_proxy(path: str, request: Request) -> Response:
    """Operator simulation controls, passed through to business unchanged."""
    try:
        r = await http.request(request.method, f"{BUSINESS_URL}/sim/{path}", params=dict(request.query_params),
                               content=await request.body() or None,
                               headers={"content-type": request.headers.get("content-type", "application/json")})
    except httpx.HTTPError:
        raise HTTPException(502, "The simulation is not answering.") from None
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


# -- SSE --------------------------------------------------------------------------------------------


@app.get("/api/stream")
async def stream(p: Principal, request: Request) -> StreamingResponse:
    """Per-user SSE: every NATS message on user.<sub>.<kind> becomes one event."""
    nc = await nats.connect(NATS_URL)
    sub = await nc.subscribe(f"user.{p['sub']}.>")
    if p.get("role") == "customer":
        await cache.delete(f"link:{p['sub']}")

    async def events() -> AsyncIterator[bytes]:
        try:
            yield b": connected\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(sub.next_msg(timeout=None), timeout=15)
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                kind = msg.subject.rsplit(".", 1)[-1]
                if kind == "account":
                    await cache.delete(f"link:{p['sub']}")
                yield f"event: {kind}\ndata: {json.dumps(json.loads(msg.data or b'{}'))}\n\n".encode()
        finally:
            await nc.drain()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


_mount_staff()
