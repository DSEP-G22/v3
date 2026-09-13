"""Control: model bindings, auto-reply policy, grounding plan and action registry.

The single writer of all four. Every change bumps a generation, writes history and
publishes control.changed, so services rebind on the next message instead of polling every
five seconds (v2 registry.py:142). A binding is a row: a swap takes effect without a restart.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lanka_common import bus
from lanka_common.db import POOLER_KWARGS, parse_neon_key
from lanka_common.llm import LLMUnavailable, build

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")

#: role -> (stage, summary, allowed impls, default impl, default model, default params)
ROLES: dict[str, tuple[str, str, tuple[str, ...], str, str, dict[str, Any]]] = {
    "llm_draft": ("response", "Write the reply from the assembled context bundle.",
                  ("ollama", "gemini", "stub"), "ollama", "gpt-oss:120b-cloud",
                  {"fallback": {"impl": "gemini", "model_version": "gemini-3.6-flash"}}),
    "llm_diagnose": ("reasoning", "Diagnose the fault from the message and retrieved procedures.",
                     ("ollama", "gemini", "rules", "stub"), "ollama", "gpt-oss:20b-cloud", {"think": "low"}),
    "mt_in": ("translation", "Translate what the customer wrote into English.",
              ("nllb", "google", "passthrough"), "nllb", "facebook/nllb-200-distilled-600M", {}),
    "mt_out": ("translation", "Translate the approved reply into the customer's language.",
               ("nllb", "google", "passthrough"), "nllb", "facebook/nllb-200-distilled-600M", {}),
    "speech": ("translation", "Transcribe voice notes in the language they were spoken.",
               ("whisper",), "whisper", "faster-whisper-small-int8", {}),
}
DEPARTMENTS = ("default", "network_operations", "technical_support", "billing", "field_service", "retention",
               "sales", "general")
TOOLS = {
    "get_subscriber_profile", "get_payment_status", "get_account_balance", "get_billing_history",
    "get_last_invoice_breakdown", "get_ledger_window", "get_plan_and_entitlements", "get_usage_summary",
    "get_circuit_status", "get_cpe_diagnostics", "get_line_quality", "get_active_outages_for",
    "get_planned_work_for", "get_device_led_semantics", "get_open_work_orders", "get_next_appointment_slots",
    "get_prior_tickets", "get_sla_position",
}
DEFAULT_POLICY = {"enabled": False, "min_completeness": 1.0, "max_priority_level": 3,
                  "require_clean_compliance": True, "allow_with_action": False}

DDL = """
CREATE TABLE IF NOT EXISTS control.model_binding (
    role text PRIMARY KEY, impl text NOT NULL, model_version text NOT NULL, params jsonb NOT NULL DEFAULT '{}',
    generation integer NOT NULL DEFAULT 1, updated_by text NOT NULL DEFAULT 'seed',
    updated_at timestamptz NOT NULL DEFAULT now(), probe_status text NOT NULL DEFAULT 'unknown',
    probe_detail text NOT NULL DEFAULT '', probe_ms integer, probe_at timestamptz
);
CREATE TABLE IF NOT EXISTS control.model_binding_event (
    id text PRIMARY KEY, role text NOT NULL, from_binding text, to_binding text NOT NULL, generation integer NOT NULL,
    actor text NOT NULL, reason text NOT NULL DEFAULT '', at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS control.autoreply_policy (
    department text PRIMARY KEY, enabled boolean NOT NULL, min_completeness real NOT NULL,
    max_priority_level integer NOT NULL, require_clean_compliance boolean NOT NULL,
    allow_with_action boolean NOT NULL, updated_by text NOT NULL DEFAULT 'seed',
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS control.document (
    name text PRIMARY KEY, body jsonb NOT NULL, generation integer NOT NULL DEFAULT 1,
    updated_by text NOT NULL DEFAULT 'seed', updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class Runtime:
    pool: asyncpg.Pool
    js: Any
    nc: Any


rt = Runtime()


async def _seed() -> None:
    async with rt.pool.acquire() as conn, conn.transaction():
        for role, (_, _, _, impl, model, params) in ROLES.items():
            if role.startswith("llm_") and os.environ.get("LANKA_LLM_IMPL"):
                impl = os.environ["LANKA_LLM_IMPL"]  # CI and load tests seed the offline stub
            await conn.execute("""INSERT INTO control.model_binding (role, impl, model_version, params)
                                  VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""", role, impl, model, json.dumps(params))
        for dept in DEPARTMENTS:
            await conn.execute("""INSERT INTO control.autoreply_policy (department, enabled, min_completeness,
                                  max_priority_level, require_clean_compliance, allow_with_action)
                                  VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING""",
                               dept, *DEFAULT_POLICY.values())
        for name, file in (("grounding_plan", "grounding_plan.yaml"), ("action_registry", "action_registry.yaml")):
            body = yaml.safe_load((CONFIG_DIR / file).read_text(encoding="utf-8"))
            await conn.execute("INSERT INTO control.document (name, body) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                               name, json.dumps(body))


async def _changed(**event: Any) -> None:
    await rt.js.publish("control.changed", json.dumps(event).encode())


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=1, max_size=4,
                                        **POOLER_KWARGS)
    await rt.pool.execute(DDL)
    await _seed()
    rt.nc, rt.js = await bus.connect()
    yield
    await rt.nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link control", lifespan=lifespan, docs_url=None, redoc_url=None)


def _row(r: asyncpg.Record) -> dict[str, Any]:
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    for k in ("params", "body"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# -- bindings ---------------------------------------------------------------------------------------


@app.get("/bindings")
async def bindings() -> dict[str, Any]:
    rows = {r["role"]: _row(r) for r in await rt.pool.fetch("SELECT * FROM control.model_binding")}
    return {"roles": [{**rows[role], "stage": spec[0], "summary": spec[1], "allowed": list(spec[2])}
                      for role, spec in ROLES.items() if role in rows]}


@app.get("/bindings/{role}")
async def binding(role: str) -> dict[str, Any]:
    r = await rt.pool.fetchrow("SELECT * FROM control.model_binding WHERE role = $1", role)
    if r is None:
        raise HTTPException(404, "Unknown role.")
    return _row(r)


class Rebind(BaseModel):
    impl: str
    model_version: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    actor: str


@app.put("/bindings/{role}")
async def rebind(role: str, b: Rebind) -> dict[str, Any]:
    if role not in ROLES:
        raise HTTPException(404, "Unknown role.")
    if b.impl not in ROLES[role][2]:
        raise HTTPException(422, f"{role} accepts {', '.join(ROLES[role][2])}.")
    async with rt.pool.acquire() as conn, conn.transaction():
        before = await conn.fetchrow("SELECT impl, model_version FROM control.model_binding WHERE role = $1", role)
        row = await conn.fetchrow(
            """UPDATE control.model_binding SET impl = $2, model_version = $3, params = $4, generation = generation + 1,
                   updated_by = $5, updated_at = now(), probe_status = 'unknown', probe_detail = 'not probed since the change'
               WHERE role = $1 RETURNING *""", role, b.impl, b.model_version, json.dumps(b.params), b.actor)
        await conn.execute(
            """INSERT INTO control.model_binding_event (id, role, from_binding, to_binding, generation, actor, reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""", f"MBE-{secrets.token_hex(6)}", role,
            f"{before['impl']}:{before['model_version']}", f"{b.impl}:{b.model_version}", row["generation"], b.actor, b.reason)
    await _changed(kind="binding", role=role, generation=row["generation"])
    return _row(row)


@app.post("/bindings/{role}/probe")
async def probe(role: str, deep: bool = False) -> dict[str, Any]:
    """ping() checks the endpoint knows the model; deep=true makes it actually generate."""
    import asyncio

    b = await binding(role)
    started = time.perf_counter()
    if not role.startswith("llm_") or b["impl"] == "rules":
        status, detail = "unknown", "Probed through the service health check."
    else:
        try:
            llm = build(b["impl"], b["model_version"], b["params"], dict(os.environ))
            status, detail = await llm.ping()
            if deep and status != "down":
                t = time.perf_counter()
                reply = (await asyncio.wait_for(llm.generate("Reply with the single word OK."), timeout=45)).strip()
                status, detail = (("reachable", f"generated a reply in {int((time.perf_counter() - t) * 1000)} ms: "
                                   f"{reply[:40]!r}") if reply else ("degraded", "the model returned an empty reply"))
        except (LLMUnavailable, TimeoutError) as exc:
            status, detail = "down", str(exc) or "the model did not answer within 45 seconds"
    ms = int((time.perf_counter() - started) * 1000)
    await rt.pool.execute("""UPDATE control.model_binding SET probe_status = $2, probe_detail = $3, probe_ms = $4,
                             probe_at = now() WHERE role = $1""", role, status, detail[:480], ms)
    return {"role": role, "status": status, "detail": detail, "ms": ms}


@app.get("/bindings-history")
async def history(role: str | None = None, limit: int = 50) -> dict[str, Any]:
    rows = await rt.pool.fetch("""SELECT * FROM control.model_binding_event WHERE $1::text IS NULL OR role = $1
                                  ORDER BY at DESC LIMIT $2""", role, max(1, min(limit, 500)))
    return {"events": [_row(r) for r in rows]}


# -- auto-reply policy -----------------------------------------------------------------------------


@app.get("/autoreply")
async def policies() -> dict[str, Any]:
    return {"policies": [_row(r) for r in await rt.pool.fetch("SELECT * FROM control.autoreply_policy ORDER BY department")]}


@app.get("/autoreply/{department}")
async def policy(department: str) -> dict[str, Any]:
    r = await rt.pool.fetchrow("""SELECT * FROM control.autoreply_policy WHERE department = $1
                                  UNION ALL SELECT * FROM control.autoreply_policy WHERE department = 'default' LIMIT 1""",
                               department)
    return _row(r) if r else {"department": department, **DEFAULT_POLICY}


class PolicyChange(BaseModel):
    enabled: bool | None = None
    min_completeness: float | None = Field(default=None, ge=0, le=1)
    max_priority_level: int | None = Field(default=None, ge=1, le=10)
    require_clean_compliance: bool | None = None
    allow_with_action: bool | None = None
    actor: str


@app.put("/autoreply/{department}")
async def set_policy(department: str, c: PolicyChange) -> dict[str, Any]:
    if department not in DEPARTMENTS:
        raise HTTPException(404, "Unknown department.")
    changes = c.model_dump(exclude_none=True, exclude={"actor"})
    if not changes:
        raise HTTPException(422, "Nothing to change.")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(changes, start=3))
    row = await rt.pool.fetchrow(f"""UPDATE control.autoreply_policy SET {sets}, updated_by = $2, updated_at = now()
                                     WHERE department = $1 RETURNING *""", department, c.actor, *changes.values())
    await _changed(kind="policy", department=department)
    return _row(row)


# -- documents: grounding plan, action registry ----------------------------------------------------


@app.get("/grounding-plan")
async def get_plan() -> dict[str, Any]:
    r = await rt.pool.fetchrow("SELECT * FROM control.document WHERE name = 'grounding_plan'")
    return {"plan": _row(r)["body"], "generation": r["generation"], "tools": sorted(TOOLS)}


class PlanPut(BaseModel):
    plan: dict[str, Any]
    actor: str


@app.put("/grounding-plan")
async def put_plan(p: PlanPut) -> dict[str, Any]:
    named = {t for block in ("by_department", "by_fault") for e in (p.plan.get(block) or {}).values()
             for t in e.get("tools") or []}
    if unknown := named - TOOLS:
        raise HTTPException(422, f"Unknown tools: {', '.join(sorted(unknown))}")
    row = await rt.pool.fetchrow("""UPDATE control.document SET body = $1, generation = generation + 1, updated_by = $2,
                                    updated_at = now() WHERE name = 'grounding_plan' RETURNING generation""",
                                 json.dumps(p.plan), p.actor)
    await _changed(kind="plan", generation=row["generation"])
    return {"generation": row["generation"]}


@app.get("/action-registry")
async def get_registry() -> dict[str, Any]:
    r = await rt.pool.fetchrow("SELECT body FROM control.document WHERE name = 'action_registry'")
    return json.loads(r["body"]) if isinstance(r["body"], str) else r["body"]


class RegistryPut(BaseModel):
    actions: list[dict[str, Any]]
    actor: str


@app.put("/action-registry")
async def put_registry(b: RegistryPut) -> dict[str, Any]:
    row = await rt.pool.fetchrow("""UPDATE control.document SET body = $1, generation = generation + 1, updated_by = $2,
                                    updated_at = now() WHERE name = 'action_registry' RETURNING generation""",
                                 json.dumps({"actions": b.actions}), b.actor)
    await _changed(kind="actions", generation=row["generation"])
    return {"generation": row["generation"]}
