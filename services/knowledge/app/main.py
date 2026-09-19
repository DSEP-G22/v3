"""Knowledge: retrieval and diagnosis. The only service that resolves the llm_diagnose role."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from app.diagnose import diagnose
from app.index import Graph, Index, embedder
from lanka_common import bus
from lanka_common.llm import LLMUnavailable, build

CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")
http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=20.0))
state: dict[str, Any] = {"llm": None, "binding": None}


async def _bind() -> None:
    """(Re)resolve llm_diagnose from the control service. Unbound or unreachable: rules only."""
    try:
        r = await http.get(f"{CONTROL_URL}/bindings/llm_diagnose")
        r.raise_for_status()
        b = r.json()
        state["binding"] = b
        state["llm"] = None if b["impl"] == "rules" else build(b["impl"], b["model_version"], b.get("params"),
                                                                dict(os.environ))
    except (httpx.HTTPError, LLMUnavailable, KeyError):
        state["llm"] = None


async def _on_control(msg) -> None:
    if json.loads(msg.data).get("role") in ("llm_diagnose", None):
        await _bind()
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    state["index"] = await asyncio.to_thread(lambda: Index(embedder()).load())
    state["graph"] = Graph()
    await _bind()
    nc, js = await bus.connect()
    await js.subscribe("control.changed", durable="knowledge", cb=_on_control, manual_ack=True)
    yield
    await nc.drain()


app = FastAPI(title="Lanka Link knowledge", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, Any]:
    idx = state.get("index")
    return {"status": "ok" if idx else "loading", "chunks": len(idx.chunks) if idx else 0,
            "embedder": idx.emb.model if idx else None, "llm_diagnose": state.get("binding")}


class In(BaseModel):
    fused_text: str
    department: str | None = None


@app.post("/run")
async def run(body: In) -> dict[str, Any]:
    started = time.perf_counter()
    out = await diagnose(state["index"], state["graph"], body.fused_text, body.department, state["llm"])
    out["ms"] = int((time.perf_counter() - started) * 1000)
    return out


@app.get("/search")
async def search(q: str, k: int = 5) -> dict[str, Any]:
    return {"hits": [{"chunk_id": c.chunk_id, "source": c.source, "score": round(s, 4), "text": c.text}
                     for c, s in state["index"].search(q, k)]}
