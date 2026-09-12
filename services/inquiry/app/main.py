"""Inquiry: conversations, messages and attachments for the chat.

Validates and normalises a message, stores it (attachments to MinIO), answers greetings and
thanks with a template (no case), and hands everything else to the orchestrator on
JetStream inquiry.received. The customer sees their message acked immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from minio import Minio
from pydantic import BaseModel

from app import text as rules
from lanka_common import bus
from lanka_common.db import POOLER_KWARGS, parse_neon_key

BUCKET = "attachments"
DUPLICATE_WINDOW_S = 600

DDL = """
CREATE TABLE IF NOT EXISTS inquiry.conversation (
    id            text PRIMARY KEY,
    user_id       text NOT NULL,
    subscriber_id text,
    origin        text NOT NULL DEFAULT 'customer' CHECK (origin IN ('customer', 'sim_test')),
    open_case_id  text,
    language      text NOT NULL DEFAULT 'en',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_conversation_customer ON inquiry.conversation (user_id) WHERE origin = 'customer';
CREATE TABLE IF NOT EXISTS inquiry.message (
    id              text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES inquiry.conversation (id),
    author_kind     text NOT NULL CHECK (author_kind IN ('customer', 'assistant', 'agent', 'system')),
    body            text NOT NULL DEFAULT '',
    body_en         text,
    lang            text,
    case_id         text,
    revision        integer,
    status          text NOT NULL DEFAULT 'sent',
    flags           text[] NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_message_conversation ON inquiry.message (conversation_id, created_at);
CREATE TABLE IF NOT EXISTS inquiry.attachment (
    id              text PRIMARY KEY,
    message_id      text REFERENCES inquiry.message (id),
    conversation_id text NOT NULL REFERENCES inquiry.conversation (id),
    kind            text NOT NULL CHECK (kind IN ('image', 'audio')),
    object_key      text NOT NULL,
    mime            text NOT NULL,
    bytes           integer NOT NULL,
    duration_s      real,
    sha256          text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS inquiry.validation_log (
    id         bigserial PRIMARY KEY,
    user_id    text,
    code       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS inquiry.notification (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    title      text NOT NULL,
    body       text NOT NULL DEFAULT '',
    link       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at    timestamptz
);
"""


class Runtime:
    pool: asyncpg.Pool
    nc: Any
    js: Any
    minio: Minio
    cache: redis.Redis


rt = Runtime()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _row(r: asyncpg.Record) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(r).items()}


async def _push(user_id: str, kind: str, payload: dict[str, Any]) -> None:
    await rt.nc.publish(f"user.{user_id}.{kind}", json.dumps(payload, default=str).encode())


async def _on_case_event(msg) -> None:
    """Case dividers: the orchestrator tells us when a case opens, revises or closes."""
    e = json.loads(msg.data)
    if e["kind"] in ("opened", "revised"):
        await rt.pool.execute("UPDATE inquiry.conversation SET open_case_id = $2 WHERE id = $1",
                              e["conversation_id"], e["case_id"])
        await rt.pool.execute("UPDATE inquiry.message SET case_id = $2, revision = $3 WHERE id = $1",
                              e["message_id"], e["case_id"], e["revision"])
    elif e["kind"] == "closed":
        await rt.pool.execute(
            "UPDATE inquiry.conversation SET open_case_id = NULL WHERE id = $1 AND open_case_id = $2",
            e["conversation_id"], e["case_id"],
        )
    elif e["kind"] == "released":
        # The response service never talks to inquiry; the released reply arrives as an event.
        row = await rt.pool.fetchrow(
            """INSERT INTO inquiry.message (id, conversation_id, author_kind, body, body_en, lang, case_id, revision)
               VALUES ($1, $2, 'assistant', $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING RETURNING *""",
            f"rel_{e['case_id']}_{e['revision']}", e["conversation_id"], rules.normalise(e["text"]), e.get("text_en"),
            e.get("language", "en"), e["case_id"], e["revision"],
        )
        if row:
            await _push(e["user_id"], "message", {"message": {**_row(row), "attachments": []}})
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=2, max_size=10,
                                        **POOLER_KWARGS)
    await rt.pool.execute(DDL)
    rt.cache = redis.from_url(os.environ.get("VALKEY_URL", "redis://valkey:6379/0"))
    rt.minio = Minio(os.environ.get("MINIO_ENDPOINT", "minio:9000"), access_key=os.environ["MINIO_ROOT_USER"],
                     secret_key=os.environ["MINIO_ROOT_PASSWORD"], secure=False)
    if not await asyncio.to_thread(rt.minio.bucket_exists, BUCKET):
        await asyncio.to_thread(rt.minio.make_bucket, BUCKET)
    rt.nc, rt.js = await bus.connect()
    await rt.js.subscribe("case.events.>", durable="inquiry", cb=_on_case_event, manual_ack=True)
    yield
    await rt.nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link inquiry", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _conversation(user_id: str, subscriber_id: str | None, origin: str) -> asyncpg.Record:
    if origin == "customer":
        row = await rt.pool.fetchrow(
            """INSERT INTO inquiry.conversation (id, user_id, subscriber_id, origin) VALUES ($1, $2, $3, 'customer')
               ON CONFLICT (user_id) WHERE origin = 'customer'
               DO UPDATE SET subscriber_id = coalesce(EXCLUDED.subscriber_id, inquiry.conversation.subscriber_id)
               RETURNING *""",
            _id("conv"), user_id, subscriber_id,
        )
    else:  # each test inquiry gets its own conversation, invisible to customers
        row = await rt.pool.fetchrow(
            "INSERT INTO inquiry.conversation (id, user_id, subscriber_id, origin) VALUES ($1, $2, $3, 'sim_test') RETURNING *",
            _id("conv"), user_id, subscriber_id,
        )
    return row


@app.post("/messages", status_code=201)
async def send(
    user_id: str = Form(...),
    subscriber_id: str | None = Form(None),
    origin: Literal["customer", "sim_test"] = Form("customer"),
    text: str = Form(""),
    language: str | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
) -> dict[str, Any]:
    body = rules.normalise(text)
    blobs = [(f.filename or "file", await f.read()) for f in files]
    if rejection := rules.validate(body, blobs):
        await rt.pool.execute("INSERT INTO inquiry.validation_log (user_id, code) VALUES ($1, $2)", user_id, rejection.code)
        raise HTTPException(422, rejection.message)

    conv = await _conversation(user_id, subscriber_id, origin)
    digest = hashlib.sha1(f"{body}|{len(blobs)}".encode()).hexdigest()
    if not await rt.cache.set(f"dup:{conv['id']}:{digest}", "1", nx=True, ex=DUPLICATE_WINDOW_S):
        raise HTTPException(409, "You just sent us this, and we are already on it.")

    lang = language or rules.script_language(body)
    flags = rules.pii_flags(body)
    msg_id = _id("msg")
    now = datetime.now(timezone.utc)
    attachments = []
    for name, data in blobs:
        mime, kind = rules.sniff(data)  # validated above
        key = f"{conv['id']}/{msg_id}/{secrets.token_hex(4)}"
        await asyncio.to_thread(rt.minio.put_object, BUCKET, key, io.BytesIO(data), len(data), content_type=mime)
        attachments.append({"id": _id("att"), "kind": kind, "object_key": key, "mime": mime, "bytes": len(data),
                            "duration_s": rules.wav_seconds(data), "sha256": hashlib.sha256(data).hexdigest(),
                            "name": name})

    talk = rules.small_talk(body) if not attachments else None
    async with rt.pool.acquire() as conn, conn.transaction():
        msg = await conn.fetchrow(
            """INSERT INTO inquiry.message (id, conversation_id, author_kind, body, lang, status, flags, created_at)
               VALUES ($1, $2, 'customer', $3, $4, $5, $6, $7) RETURNING *""",
            msg_id, conv["id"], body, lang, "sent" if talk else "received", flags, now,
        )
        await conn.executemany(
            """INSERT INTO inquiry.attachment (id, message_id, conversation_id, kind, object_key, mime, bytes, duration_s, sha256)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            [(a["id"], msg_id, conv["id"], a["kind"], a["object_key"], a["mime"], a["bytes"], a["duration_s"], a["sha256"])
             for a in attachments],
        )
        if talk:
            reply_lang = lang if lang in ("si", "ta") else "en"
            reply = await conn.fetchrow(
                """INSERT INTO inquiry.message (id, conversation_id, author_kind, body, lang, status)
                   VALUES ($1, $2, 'assistant', $3, $4, 'sent') RETURNING *""",
                _id("msg"), conv["id"], rules.TEMPLATES[talk][reply_lang], reply_lang,
            )

    if talk:
        await _push(user_id, "message", {"message": _row(reply)})
        return {"message": _row(msg), "reply": _row(reply)}

    event = {
        "conversation_id": conv["id"], "message_id": msg_id, "user_id": user_id, "subscriber_id": conv["subscriber_id"],
        "origin": origin, "open_case_id": conv["open_case_id"], "text": body, "language_hint": lang, "flags": flags,
        "attachments": [{k: a[k] for k in ("id", "kind", "object_key", "mime", "duration_s")} for a in attachments],
        "received_at": now.isoformat(),
    }
    await rt.js.publish("inquiry.received", json.dumps(event).encode(), headers={"Nats-Msg-Id": msg_id})
    return {"message": {**_row(msg), "attachments": [{"id": a["id"], "kind": a["kind"]} for a in attachments]}}


@app.get("/conversations/mine")
async def mine(user_id: str) -> dict[str, Any]:
    conv = await rt.pool.fetchrow(
        "SELECT * FROM inquiry.conversation WHERE user_id = $1 AND origin = 'customer'", user_id
    )
    if conv is None:
        return {"conversation": None, "messages": []}
    return {"conversation": _row(conv), "messages": await _messages(conv["id"])}


@app.get("/cases/{case_id}/messages")
async def case_messages(case_id: str) -> dict[str, Any]:
    """Customer messages on a case, oldest first: what the orchestrator fuses on a revision."""
    rows = await rt.pool.fetch(
        """SELECT id, body FROM inquiry.message WHERE case_id = $1 AND author_kind = 'customer'
           ORDER BY created_at""", case_id)
    return {"messages": [dict(r) for r in rows]}


@app.get("/conversations/{conversation_id}")
async def conversation(conversation_id: str) -> dict[str, Any]:
    """Staff and simulation view (the gateway restricts who may call this)."""
    conv = await rt.pool.fetchrow("SELECT * FROM inquiry.conversation WHERE id = $1", conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation.")
    return {"conversation": _row(conv), "messages": await _messages(conversation_id)}


async def _messages(conversation_id: str) -> list[dict[str, Any]]:
    rows = await rt.pool.fetch(
        """SELECT m.*, coalesce(json_agg(json_build_object('id', a.id, 'kind', a.kind, 'mime', a.mime,
                                                            'duration_s', a.duration_s))
                                FILTER (WHERE a.id IS NOT NULL), '[]') AS attachments
           FROM inquiry.message m LEFT JOIN inquiry.attachment a ON a.message_id = m.id
           WHERE m.conversation_id = $1 GROUP BY m.id ORDER BY m.created_at DESC LIMIT 200""",
        conversation_id,
    )
    out = [_row(r) for r in reversed(rows)]
    for m in out:
        m["attachments"] = json.loads(m["attachments"]) if isinstance(m["attachments"], str) else m["attachments"]
    return out


class Reply(BaseModel):
    conversation_id: str
    author_kind: Literal["assistant", "agent", "system"] = "assistant"
    body: str
    body_en: str | None = None
    lang: str = "en"
    case_id: str | None = None
    status: str = "sent"


@app.post("/internal/messages", status_code=201)
async def internal_reply(r: Reply) -> dict[str, Any]:
    """Released replies and system notes (response service, agent approval)."""
    conv = await rt.pool.fetchrow("SELECT user_id FROM inquiry.conversation WHERE id = $1", r.conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation.")
    row = await rt.pool.fetchrow(
        """INSERT INTO inquiry.message (id, conversation_id, author_kind, body, body_en, lang, case_id, status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        _id("msg"), r.conversation_id, r.author_kind, rules.normalise(r.body), r.body_en, r.lang, r.case_id, r.status,
    )
    await _push(conv["user_id"], "message", {"message": _row(row)})
    return _row(row)


@app.get("/attachments/{attachment_id}")
async def attachment(attachment_id: str, user_id: str | None = None) -> StreamingResponse:
    """Stream an attachment. With user_id, only the owner's own files are served."""
    row = await rt.pool.fetchrow(
        """SELECT a.* FROM inquiry.attachment a JOIN inquiry.conversation c ON c.id = a.conversation_id
           WHERE a.id = $1 AND ($2::text IS NULL OR c.user_id = $2)""",
        attachment_id, user_id,
    )
    if row is None:
        raise HTTPException(404, "Not found.")
    obj = await asyncio.to_thread(rt.minio.get_object, BUCKET, row["object_key"])
    data = await asyncio.to_thread(obj.read)
    obj.close()
    return StreamingResponse(io.BytesIO(data), media_type=row["mime"],
                             headers={"Cache-Control": "private, max-age=3600"})


@app.get("/internal/attachments/{attachment_id}/bytes")
async def attachment_bytes(attachment_id: str) -> StreamingResponse:
    """For audio and image services on the internal network only."""
    return await attachment(attachment_id)
