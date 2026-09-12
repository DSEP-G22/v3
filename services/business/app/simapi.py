"""Operator surface for the simulation: clock, scenarios, faults, events, network, browse.

Mounted by app.main. The gateway restricts every /sim route to operator and admin.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, loader, scenarios
from app import formatting as fmt
from app.clock import ClockState
from app.world import COLOMBO

router = APIRouter(prefix="/sim")


def _state():
    from app.main import state  # late import: main imports this module

    return state


async def _save_clock(c: ClockState) -> None:
    await db.neon.execute(
        "UPDATE org.sim_clock SET speed = $1, anchor_wall = $2, anchor_sim = $3 WHERE id = 1",
        c.speed, c.anchor_wall, c.anchor_sim,
    )
    _state().clock = c
    loader.invalidate()


def _clock_view(c: ClockState) -> dict[str, Any]:
    at = c.now()
    return {"sim_now": at.isoformat(), "sim_now_display": fmt.moment(at.astimezone(COLOMBO)),
            "speed": c.speed, "paused": c.speed == 0}


@router.get("/clock")
async def get_clock() -> dict[str, Any]:
    return _clock_view(_state().clock)


class ClockChange(BaseModel):
    action: Literal["pause", "resume", "speed"]
    speed: float = Field(default=1.0, ge=0, le=3600)


@router.post("/clock")
async def set_clock(body: ClockChange) -> dict[str, Any]:
    c = _state().clock
    speed = {"pause": 0.0, "resume": c.speed or 1.0, "speed": body.speed}[body.action]
    if body.action == "resume" and c.speed == 0:
        speed = 1.0
    new = c.reanchor(speed=speed)
    await _save_clock(new)
    return _clock_view(new)


class Advance(BaseModel):
    hours: float = Field(default=0, ge=0, le=24 * 60)
    to: Literal["next_bill_run"] | None = None


@router.post("/advance")
async def advance(body: Advance) -> dict[str, Any]:
    c = _state().clock
    step = timedelta(hours=body.hours)
    if body.to == "next_bill_run":
        nxt = await db.neon.fetchval(
            "SELECT min(renewal_date) FROM org.subscription WHERE status IN ('active', 'suspended')"
        )
        if nxt is None:
            raise HTTPException(409, "No subscription renews.")
        target = datetime.combine(nxt, datetime.min.time(), tzinfo=COLOMBO) + timedelta(minutes=5)
        step = max(target - c.now(), timedelta(0))
    new = c.reanchor(advance=step)
    await _save_clock(new)
    await scenarios.log(db.neon, "clock_advance", "clock", {"hours": step.total_seconds() / 3600},
                        new.now(), "operator", "Advanced the sim clock.")
    return _clock_view(new)


@router.get("/scenarios")
async def list_scenarios() -> dict[str, Any]:
    return {"scenarios": [{"name": k, "description": v, "needs_subscriber": k not in scenarios.GLOBAL}
                          for k, v in scenarios.SCENARIOS.items()]}


class Inject(BaseModel):
    subscriber_ref: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/scenarios/{name}")
async def inject(name: str, body: Inject) -> dict[str, Any]:
    sid = await loader.resolve_id(body.subscriber_ref) if body.subscriber_ref else None
    if name not in scenarios.GLOBAL and sid is None:
        raise HTTPException(404, "No subscriber matches that reference.")
    try:
        async with db.neon.acquire() as conn, db.ts.acquire() as ts, conn.transaction():
            result = await scenarios.apply(conn, ts, name, sid, _state().clock.now(), **body.params)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from exc
    loader.invalidate()
    return result


@router.get("/faults")
async def faults() -> dict[str, Any]:
    rows = await db.neon.fetch("SELECT * FROM org.active_fault ORDER BY started_at DESC")
    now = _state().clock.now()
    return {"faults": [{
        "id": r["id"], "kind": r["kind"], "label": scenarios.SCENARIOS.get(r["kind"], r["kind"]),
        "target_kind": r["target_kind"], "target_ref": r["target_ref"], "source": r["source"],
        "started_display": fmt.relative(r["started_at"], now),
        "eta_display": fmt.moment(r["eta_at"].astimezone(COLOMBO)) if r["eta_at"] else None,
    } for r in rows]}


@router.delete("/faults/{fault_id}")
async def clear_fault(fault_id: str) -> dict[str, Any]:
    try:
        async with db.neon.acquire() as conn, db.ts.acquire() as ts, conn.transaction():
            result = await scenarios.clear(conn, ts, fault_id, _state().clock.now())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    loader.invalidate()
    return result


@router.get("/events")
async def events(limit: int = 100) -> dict[str, Any]:
    rows = await db.neon.fetch(
        "SELECT * FROM org.sim_event_log ORDER BY occurred_at DESC LIMIT $1", max(1, min(limit, 500))
    )
    now = _state().clock.now()
    return {"events": [{
        "id": r["id"], "kind": r["kind"], "target": r["target"], "note": r["note"], "actor": r["actor"],
        "occurred_display": fmt.relative(r["occurred_at"], now),
        "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
    } for r in rows]}


@router.get("/network")
async def network() -> dict[str, Any]:
    world = _state().world
    since = _state().clock.now() - timedelta(hours=24)
    spark = await db.ts.fetch(
        """SELECT olt_id, time_bucket(INTERVAL '1 hour', time) AS h, avg(utilisation_pct) AS u
           FROM olt_metric WHERE time > $1 GROUP BY olt_id, h ORDER BY h""",
        since,
    )
    series: dict[str, list[float]] = {}
    for r in spark:
        series.setdefault(r["olt_id"], []).append(round(r["u"], 1))
    counts = {r["olt_id"]: r for r in await db.neon.fetch(
        """SELECT olt_id, count(*) AS lines, count(*) FILTER (WHERE line_state = 'down') AS down
           FROM org.circuit WHERE olt_id IS NOT NULL GROUP BY olt_id"""
    )}
    exchanges = []
    for ex in sorted(world.exchanges.values(), key=lambda e: e.code):
        olts = []
        for o in sorted((o for o in world.olts.values() if o.exchange_code == ex.code), key=lambda o: o.id):
            c = counts.get(o.id)
            open_incident = any(i.scope == "olt" and i.scope_ref == o.id and i.status != "resolved"
                                for i in world.outages)
            health = "down" if open_incident else ("busy" if o.uplink_utilisation_pct >= 85 else "healthy")
            olts.append({"olt_id": o.id, "vendor": o.vendor, "model": o.model, "health": health,
                         "utilisation_pct": o.uplink_utilisation_pct, "sparkline": series.get(o.id, []),
                         "lines": c["lines"] if c else 0, "lines_down": c["down"] if c else 0})
        exchanges.append({"code": ex.code, "name": ex.name, "district": ex.district, "olts": olts})
    return {"exchanges": exchanges}


@router.get("/subscribers")
async def subscribers(q: str = "", olt: str | None = None, limit: int = 50) -> dict[str, Any]:
    like = f"%{q.strip()}%"
    rows = await db.neon.fetch(
        """SELECT s.id, s.full_name, s.segment, s.simulated, sv.plan_code, a.status AS account_status,
                  a.outstanding_balance, c.line_state, c.olt_id
           FROM org.subscriber s
           JOIN org.billing_account a ON a.subscriber_id = s.id
           JOIN org.subscription sv ON sv.subscriber_id = s.id
           LEFT JOIN org.circuit c ON c.subscriber_id = s.id
           WHERE ($1 = '%%' OR s.id ILIKE $1 OR s.full_name ILIKE $1 OR s.email ILIKE $1)
             AND ($2::text IS NULL OR c.olt_id = $2)
           ORDER BY s.id LIMIT $3""",
        like, olt, max(1, min(limit, 200)),
    )
    return {"subscribers": [{
        "subscriber_id": r["id"], "name": r["full_name"], "segment": r["segment"], "real_customer": not r["simulated"],
        "plan_code": r["plan_code"], "account_status": r["account_status"],
        "balance_display": fmt.money(r["outstanding_balance"]), "line_state": r["line_state"], "olt_id": r["olt_id"],
    } for r in rows]}


# -- series for charts (customer usage page and the sim customer sheet) ------------------------


async def usage_series(subscription_id: str, days: int = 30) -> list[dict[str, Any]]:
    now = _state().clock.now()
    rows = await db.ts.fetch(
        """SELECT (bucket AT TIME ZONE 'Asia/Colombo')::date AS day, down_gb + up_gb AS gb
           FROM usage_1d WHERE subscription_id = $1 AND bucket > $2 AND bucket <= $3 ORDER BY bucket""",
        subscription_id, now - timedelta(days=days), now,
    )
    return [{"date": r["day"].isoformat(), "gb": round(r["gb"], 2)} for r in rows]


async def line_series(circuit_id: str, hours: int = 48) -> list[dict[str, Any]]:
    now = _state().clock.now()
    rows = await db.ts.fetch(
        """SELECT bucket, sync_down_mbps, latency_ms, packet_loss_pct FROM line_metric_1h
           WHERE circuit_id = $1 AND bucket > $2 AND bucket <= $3 ORDER BY bucket""",
        circuit_id, now - timedelta(hours=hours), now,
    )
    return [{"time": r["bucket"].astimezone(timezone.utc).isoformat(), "sync_mbps": round(r["sync_down_mbps"] or 0, 1),
             "latency_ms": round(r["latency_ms"] or 0), "loss_pct": round(r["packet_loss_pct"] or 0, 2)} for r in rows]


@router.get("/subscribers/{ref}/series")
async def subscriber_series(ref: str) -> dict[str, Any]:
    sid = await loader.resolve_id(ref)
    row = await db.neon.fetchrow(
        """SELECT sv.id AS sub, c.id AS cir FROM org.subscription sv
           LEFT JOIN org.circuit c ON c.subscription_id = sv.id WHERE sv.subscriber_id = $1""",
        sid,
    )
    if row is None:
        raise HTTPException(404, "No subscriber matches that reference.")
    return {"usage": await usage_series(row["sub"]), "line": await line_series(row["cir"]) if row["cir"] else []}
