"""NATS connection and the JetStream subject registry.

JetStream carries durable events only. Hot-path token streams (case.<id>.stream) and per-user
SSE fan-out (user.<id>.<kind>) stay on core NATS and must never match a stream subject.
"""

from __future__ import annotations

import os

import nats
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError

STREAMS: dict[str, list[str]] = {
    "INQUIRY": ["inquiry.received"],
    "CASES": ["case.events.>"],
    "PAYMENTS": ["payment.succeeded"],
    "SUBSCRIBERS": ["subscriber.provisioned", "user.created"],
    "CONTROL": ["control.changed"],
}


async def ensure_streams(js: JetStreamContext) -> None:
    for name, subjects in STREAMS.items():
        try:
            await js.stream_info(name)
        except NotFoundError:
            await js.add_stream(name=name, subjects=subjects)


async def connect(url: str | None = None) -> tuple[nats.NATS, JetStreamContext]:
    nc = await nats.connect(url or os.environ.get("NATS_URL", "nats://nats:4222"))
    js = nc.jetstream()
    await ensure_streams(js)
    return nc, js
