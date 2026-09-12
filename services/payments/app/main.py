"""Stub payments. An intent succeeds about 1.5 s after the customer clicks Pay.

No card data is ever collected or stored: the method is a label ("Card ending 4242",
"LankaQR"). payment.succeeded leaves through a transactional outbox, so a crash between
settling and publishing never loses a payment, and the outbox id doubles as the JetStream
dedupe id so a relay retry never double-credits.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, Literal

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lanka_common import bus
from lanka_common.db import POOLER_KWARGS, parse_neon_key

SETTLE_AFTER_S = 1.5
METHODS = {"card_4242": "Card ending 4242", "lankaqr": "LankaQR"}

DDL = """
CREATE TABLE IF NOT EXISTS payments.payment_intent (
    id              text PRIMARY KEY,
    user_id         text NOT NULL,
    purpose         text NOT NULL CHECK (purpose IN ('subscription', 'invoice', 'plan_change')),
    ref             text NOT NULL,
    amount_lkr      numeric(12, 2) NOT NULL CHECK (amount_lkr > 0),
    description     text NOT NULL DEFAULT '',
    method          text,
    status          text NOT NULL DEFAULT 'requires_payment'
                    CHECK (status IN ('requires_payment', 'processing', 'succeeded', 'cancelled')),
    idempotency_key text NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_intent_user ON payments.payment_intent (user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS payments.outbox (
    id           bigserial PRIMARY KEY,
    subject      text NOT NULL,
    payload      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
"""


class Runtime:
    pool: asyncpg.Pool
    js: Any
    nc: Any
    wake = asyncio.Event()


rt = Runtime()


def _intent(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["amount_lkr"] = float(d["amount_lkr"])
    d["method_display"] = METHODS.get(d["method"] or "", None)
    d["amount_display"] = f"LKR {d['amount_lkr']:,.2f}"
    for key in ("created_at", "updated_at"):
        d[key] = d[key].isoformat()
    return d


async def _settle(intent_id: str) -> None:
    await asyncio.sleep(SETTLE_AFTER_S)
    async with rt.pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """UPDATE payments.payment_intent SET status = 'succeeded', updated_at = now()
               WHERE id = $1 AND status = 'processing' RETURNING *""",
            intent_id,
        )
        if row is None:
            return
        payload = {k: v for k, v in _intent(row).items() if k != "method_display"}
        await conn.execute(
            "INSERT INTO payments.outbox (subject, payload) VALUES ('payment.succeeded', $1)",
            json.dumps(payload),
        )
    rt.wake.set()


async def _relay() -> None:
    while True:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(rt.wake.wait(), timeout=5)
        rt.wake.clear()
        with contextlib.suppress(Exception):
            async with rt.pool.acquire() as conn, conn.transaction():
                rows = await conn.fetch(
                    """SELECT id, subject, payload FROM payments.outbox WHERE published_at IS NULL
                       ORDER BY id LIMIT 50 FOR UPDATE SKIP LOCKED"""
                )
                for r in rows:
                    await rt.js.publish(
                        r["subject"], r["payload"].encode(), headers={"Nats-Msg-Id": f"pay-outbox-{r['id']}"}
                    )
                    await conn.execute("UPDATE payments.outbox SET published_at = now() WHERE id = $1", r["id"])


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(
        parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=2, max_size=8, **POOLER_KWARGS
    )
    await rt.pool.execute(DDL)
    rt.nc, rt.js = await bus.connect()
    # Anything left mid-flight by a restart settles now.
    for r in await rt.pool.fetch("SELECT id FROM payments.payment_intent WHERE status = 'processing'"):
        asyncio.create_task(_settle(r["id"]))
    relay = asyncio.create_task(_relay())
    rt.wake.set()
    yield
    relay.cancel()
    await rt.nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link payments", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class NewIntent(BaseModel):
    user_id: str = Field(min_length=1)
    purpose: Literal["subscription", "invoice", "plan_change"]
    ref: str = Field(min_length=1)
    amount_lkr: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = ""
    idempotency_key: str = Field(min_length=8)


@app.post("/intents", status_code=201)
async def create_intent(body: NewIntent) -> dict[str, Any]:
    row = await rt.pool.fetchrow(
        """INSERT INTO payments.payment_intent (id, user_id, purpose, ref, amount_lkr, description, idempotency_key)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = payments.payment_intent.updated_at
           RETURNING *""",
        f"pi_{secrets.token_hex(10)}", body.user_id, body.purpose, body.ref, body.amount_lkr,
        body.description, body.idempotency_key,
    )
    return _intent(row)


async def _owned(intent_id: str, user_id: str) -> asyncpg.Record:
    row = await rt.pool.fetchrow(
        "SELECT * FROM payments.payment_intent WHERE id = $1 AND user_id = $2", intent_id, user_id
    )
    if row is None:
        raise HTTPException(404, "We could not find that payment.")
    return row


@app.get("/intents/{intent_id}")
async def get_intent(intent_id: str, user_id: str) -> dict[str, Any]:
    return _intent(await _owned(intent_id, user_id))


class Pay(BaseModel):
    user_id: str
    method: Literal["card_4242", "lankaqr"]


@app.post("/intents/{intent_id}/pay")
async def pay(intent_id: str, body: Pay) -> dict[str, Any]:
    await _owned(intent_id, body.user_id)
    row = await rt.pool.fetchrow(
        """UPDATE payments.payment_intent SET status = 'processing', method = $2, updated_at = now()
           WHERE id = $1 AND status = 'requires_payment' RETURNING *""",
        intent_id, body.method,
    )
    if row is None:  # already paying or paid: idempotent, return the current state
        return _intent(await _owned(intent_id, body.user_id))
    asyncio.create_task(_settle(intent_id))
    return _intent(row)
