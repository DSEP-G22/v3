"""Business: the mock telco's API. Tools, catalogue, coverage, orders, links, sim clock.

Internal only (no published port); the gateway is the sole caller and enforces RBAC.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import db, loader, provision
from app import formatting as fmt
from app.clock import ClockState
from app.seed import CITY_BY_EXCHANGE
from app.tools import REGISTRY, available_tools, call
from app.world import World
from lanka_common import bus

WORLD_REFRESH_S = 15.0
PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://payments:8000")


class State:
    world: World = World()
    clock: ClockState | None = None
    js: Any = None
    nc: Any = None


state = State()
http = httpx.AsyncClient(timeout=10)


async def _read_clock() -> ClockState:
    row = await db.neon.fetchrow("SELECT speed, anchor_wall, anchor_sim FROM org.sim_clock WHERE id = 1")
    if row is None:
        now = datetime.now(timezone.utc)
        return ClockState(1.0, now, now)
    return ClockState(row["speed"], row["anchor_wall"], row["anchor_sim"])


async def refresh() -> None:
    state.world, state.clock = await asyncio.gather(loader.load_world(), _read_clock())


async def _refresher() -> None:
    # ponytail: poll every 15 s; switch to a NATS business.world.changed push if staleness hurts.
    while True:
        await asyncio.sleep(WORLD_REFRESH_S)
        with contextlib.suppress(Exception):
            await refresh()


async def _on_payment(msg) -> None:
    intent = json.loads(msg.data)
    handler = {
        "subscription": provision.on_new_service,
        "plan_change": provision.on_plan_change,
    }.get(intent["purpose"])
    async with db.neon.acquire() as conn, conn.transaction():
        if handler:
            sub_id = await handler(conn, intent, state.world, now())
        else:
            sub_id = await provision.on_invoice_payment(conn, intent, now())
    if sub_id:
        loader.invalidate(sub_id)
        body = json.dumps({"user_id": intent["user_id"], "subscriber_id": sub_id, "purpose": intent["purpose"]})
        if intent["purpose"] == "subscription":
            await state.js.publish(
                "subscriber.provisioned", body.encode(), headers={"Nats-Msg-Id": f"biz-{intent['id']}"}
            )
        # Every change also reaches the customer's open tabs over SSE.
        await state.nc.publish(f"user.{intent['user_id']}.account", body.encode())
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await db.open_pools()
    await refresh()
    state.nc, state.js = await bus.connect()
    await state.js.subscribe("payment.succeeded", durable="business", cb=_on_payment, manual_ack=True)
    task = asyncio.create_task(_refresher())
    yield
    task.cancel()
    await state.nc.drain()
    await db.close_pools()


app = FastAPI(title="Lanka Link business", lifespan=lifespan, docs_url=None, redoc_url=None)


def now() -> datetime:
    return state.clock.now() if state.clock else datetime.now(timezone.utc)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "seeded": bool(state.world.plans), "sim_now": now().isoformat()}


# -- tools ----------------------------------------------------------------------------------


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Batch(BaseModel):
    subscriber_ref: str
    calls: list[ToolCall]


@app.get("/tools")
async def list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {"name": s.name, "group": s.group, "arguments": list(s.args), "description": s.description}
            for s in (REGISTRY[n] for n in available_tools())
        ]
    }


@app.post("/tools:batch")
async def tools_batch(batch: Batch) -> dict[str, Any]:
    """Many tools for one subscriber off one snapshot: one Neon round trip when cold, zero warm."""
    unknown = [c.name for c in batch.calls if c.name not in REGISTRY]
    if unknown:
        raise HTTPException(404, f"unknown tools: {', '.join(unknown)}")
    at = now()
    sid = await loader.resolve_id(batch.subscriber_ref)
    snap = await loader.load_snapshot(sid, state.world, at) if sid else None
    results = {
        c.name: call(c.name, snap, state.world, at, subscriber_ref=batch.subscriber_ref, **c.args)
        for c in batch.calls
    }
    return {"subscriber_id": sid, "sim_now": at.isoformat(), "results": results}


# -- catalogue and coverage ------------------------------------------------------------------


def _plan_view(p) -> dict[str, Any]:
    return {
        "code": p.code,
        "family": p.family,
        "name": p.display_name,
        "tier": p.tier,
        "technology": p.technology,
        "technology_display": fmt.titlecase_code(p.technology),
        "price_lkr": p.monthly_price_lkr,
        "price_display": fmt.money(p.monthly_price_lkr),
        "speed_display": fmt.speed(p.speed_down_mbps),
        "upload_display": fmt.speed(p.speed_up_mbps),
        "data_cap_display": fmt.data_volume(p.data_cap_gb),
        "contract_display": f"{p.contract_months} month minimum term" if p.contract_months else "No minimum term",
    }


@app.get("/plans")
async def plans() -> dict[str, Any]:
    rows = sorted((p for p in state.world.plans.values() if p.active and p.sellable), key=lambda p: p.sort_order)
    return {"plans": [_plan_view(p) for p in rows]}


def _areas() -> list[dict[str, Any]]:
    world = state.world
    areas = []
    for code, (city, district, _) in CITY_BY_EXCHANGE.items():
        if code not in world.exchanges:
            continue
        techs = {"gpon", "adsl"} if any(o.exchange_code == code for o in world.olts.values()) else set()
        if any(s.district == district for s in world.sites.values()):
            techs.add("lte")
        areas.append({"district": district, "city": city, "exchange_code": code, "technologies": sorted(techs)})
    return sorted(areas, key=lambda a: (a["district"], a["city"]))


@app.get("/coverage")
async def coverage() -> dict[str, Any]:
    """Serviceable areas: each city maps to an exchange (fibre, copper) and district cell sites."""
    return {"areas": _areas()}


# -- orders and payments ------------------------------------------------------------------------


class NewOrder(BaseModel):
    user_id: str
    kind: Literal["new_service", "plan_change"] = "new_service"
    plan_code: str
    full_name: str = Field(default="", max_length=120)
    # Already verified by the auth service; the gateway passes the session's own address.
    email: str = Field(min_length=3, max_length=254)
    language: Literal["en", "si", "ta"] = "en"
    city: str | None = None
    address_line: str = Field(default="", max_length=160)


@app.post("/orders", status_code=201)
async def create_order(body: NewOrder) -> dict[str, Any]:
    plan = state.world.plans.get(body.plan_code)
    if plan is None or not (plan.active and plan.sellable):
        raise HTTPException(422, "That plan is not available.")

    subscriber_id = await db.neon.fetchval("SELECT subscriber_id FROM org.customer_link WHERE user_id = $1", body.user_id)
    exchange_code = district = None
    if body.kind == "new_service":
        if subscriber_id:
            raise HTTPException(409, "You already have a service with us. Change your plan instead.")
        area = next((a for a in _areas() if a["city"] == body.city), None)
        if area is None:
            raise HTTPException(422, "We do not cover that area yet.")
        if plan.technology not in area["technologies"]:
            raise HTTPException(422, f"{plan.display_name} is not available in {body.city}.")
        exchange_code, district = area["exchange_code"], area["district"]
    elif not subscriber_id:
        raise HTTPException(409, "Set up a service before changing plan.")

    order_id = f"ORD-{secrets.token_hex(4).upper()}"
    amount = provision.first_charge(plan.monthly_price_lkr)
    await db.neon.execute(
        """INSERT INTO org."order" (id, user_id, kind, plan_code, full_name, email, language, address_line,
                                    district, city, exchange_code, subscriber_id, amount_lkr, status, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'pending_payment',$14)""",
        order_id, body.user_id, body.kind, plan.code, body.full_name, body.email, body.language,
        body.address_line, district, body.city, exchange_code, subscriber_id, amount, datetime.now(timezone.utc),
    )
    r = await http.post(f"{PAYMENTS_URL}/intents", json={
        "user_id": body.user_id,
        "purpose": "subscription" if body.kind == "new_service" else "plan_change",
        "ref": order_id,
        "amount_lkr": f"{amount:.2f}",
        "description": f"{plan.display_name}, first month including VAT",
        "idempotency_key": f"order-{order_id}",
    })
    r.raise_for_status()
    intent = r.json()
    await db.neon.execute('UPDATE org."order" SET intent_id = $2 WHERE id = $1', order_id, intent["id"])
    return {"order_id": order_id, "intent_id": intent["id"], "plan": _plan_view(plan), "amount_display": fmt.money(amount)}


@app.get("/orders/{order_id}")
async def get_order(order_id: str, user_id: str) -> dict[str, Any]:
    row = await db.neon.fetchrow('SELECT * FROM org."order" WHERE id = $1 AND user_id = $2', order_id, user_id)
    if row is None:
        raise HTTPException(404, "We could not find that order.")
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(row).items()}


class InvoiceIntent(BaseModel):
    user_id: str


@app.post("/invoices/{invoice_id}/intent", status_code=201)
async def invoice_intent(invoice_id: str, body: InvoiceIntent) -> dict[str, Any]:
    """Pay an invoice. Only the linked customer's own invoices, only what is outstanding."""
    row = await db.neon.fetchrow(
        """SELECT i.id, i.total_lkr - i.paid_lkr AS due FROM org.invoice i
           JOIN org.billing_account a ON a.id = i.account_id
           JOIN org.customer_link l ON l.subscriber_id = a.subscriber_id
           WHERE i.id = $1 AND l.user_id = $2 AND i.status IN ('unpaid', 'overdue', 'partial')""",
        invoice_id, body.user_id,
    )
    if row is None or row["due"] <= 0:
        raise HTTPException(404, "There is nothing to pay on that invoice.")
    r = await http.post(f"{PAYMENTS_URL}/intents", json={
        "user_id": body.user_id,
        "purpose": "invoice",
        "ref": invoice_id,
        "amount_lkr": f"{row['due']:.2f}",
        "description": f"Invoice {invoice_id}",
        # A fresh key per request: a later partial payment on the same invoice is a new intent.
        "idempotency_key": f"inv-{invoice_id}-{secrets.token_hex(6)}",
    })
    r.raise_for_status()
    return {"intent_id": r.json()["id"], "amount_display": fmt.money(row["due"])}


@app.post("/accounts/balance/intent", status_code=201)
async def balance_intent(body: InvoiceIntent) -> dict[str, Any]:
    """Pay everything owed in one go: what a paused customer needs to get their service back."""
    row = await db.neon.fetchrow(
        """SELECT a.id, a.outstanding_balance AS due FROM org.billing_account a
           JOIN org.customer_link l ON l.subscriber_id = a.subscriber_id WHERE l.user_id = $1""", body.user_id)
    if row is None or row["due"] <= 0.005:
        raise HTTPException(404, "Nothing is owed on your account.")
    r = await http.post(f"{PAYMENTS_URL}/intents", json={
        "user_id": body.user_id, "purpose": "invoice", "ref": row["id"], "amount_lkr": f"{row['due']:.2f}",
        "description": "Account balance", "idempotency_key": f"bal-{row['id']}-{secrets.token_hex(6)}",
    })
    r.raise_for_status()
    return {"intent_id": r.json()["id"], "amount_display": fmt.money(row["due"])}


# -- staff: names for the queue, approved actions --------------------------------------------------


@app.get("/subscribers/names")
async def names(ids: str) -> dict[str, str]:
    wanted = [i for i in ids.split(",") if i][:200]
    rows = await db.neon.fetch("SELECT id, full_name FROM org.subscriber WHERE id = ANY($1::text[])", wanted)
    return {r["id"]: r["full_name"] for r in rows}


class Execute(BaseModel):
    action_id: str
    parameters: dict[str, Any]
    case_id: str
    actor: str


@app.post("/actions/execute")
async def execute_action(body: Execute) -> dict[str, Any]:
    from app import actions

    try:
        async with db.neon.acquire() as conn, conn.transaction():
            result = await actions.execute(conn, body.action_id, body.parameters, body.case_id, body.actor, now())
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.get("subscriber_id"):
        loader.invalidate(result["subscriber_id"])
    return result


# -- customer links ---------------------------------------------------------------------------


@app.get("/links/{user_id}")
async def get_link(user_id: str) -> dict[str, Any]:
    sid = await db.neon.fetchval("SELECT subscriber_id FROM org.customer_link WHERE user_id = $1", user_id)
    if sid is None:
        raise HTTPException(404, "not linked")
    return {"user_id": user_id, "subscriber_id": sid}


class Link(BaseModel):
    user_id: str
    subscriber_ref: str
    linked_by: str = "admin"


@app.post("/links")
async def put_link(link: Link) -> dict[str, Any]:
    sid = await loader.resolve_id(link.subscriber_ref)
    if sid is None:
        raise HTTPException(404, "no subscriber matches that reference")
    await db.neon.execute(
        """INSERT INTO org.customer_link (user_id, subscriber_id, linked_at, linked_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id) DO UPDATE SET subscriber_id = $2, linked_at = $3, linked_by = $4""",
        link.user_id, sid, datetime.now(timezone.utc), link.linked_by,
    )
    return {"user_id": link.user_id, "subscriber_id": sid}


# -- customer series and sim control ---------------------------------------------------------

from app import simapi  # noqa: E402  (router module reads `state` from here lazily)

app.include_router(simapi.router)


@app.get("/customers/{subscriber_id}/series")
async def customer_series(subscriber_id: str) -> dict[str, Any]:
    """Chart data for the customer's own usage page. The gateway passes the linked id only."""
    return await simapi.subscriber_series(subscriber_id)
