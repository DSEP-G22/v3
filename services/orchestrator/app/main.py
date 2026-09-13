"""Orchestrator: case state and the pipeline DAG. Same stages as v2, reordered for latency.

    T0  inquiry.received (JetStream) opens a case or a revision
        parallel: translate-in, ASR per voice note, vision per photo, account prefetch
    T1  join (each branch has a budget; a late branch marks the payload partial) -> fuse
    T2  triage -> diagnose           T3 grounding/build            T4 response

Each stage is an HTTP call to its service when <STAGE>_URL is set, otherwise a deterministic
stub, so the pipeline runs end to end from Phase 3 and services replace stubs one at a time.
The customer only ever sees friendly chips; stage names and timings go to the console.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException

from app.fusion import Part, fuse
from lanka_common import bus, tracing
from lanka_common.contracts import band_for
from lanka_common.db import POOLER_KWARGS, parse_neon_key

BUSINESS_URL = os.environ.get("BUSINESS_URL", "http://business:8000")
INQUIRY_URL = os.environ.get("INQUIRY_URL", "http://inquiry:8000")
PREFETCH_TOOLS = [
    "get_subscriber_profile", "get_payment_status", "get_account_balance", "get_billing_history",
    "get_last_invoice_breakdown", "get_ledger_window", "get_plan_and_entitlements", "get_usage_summary",
    "get_circuit_status", "get_cpe_diagnostics", "get_line_quality", "get_active_outages_for",
    "get_planned_work_for", "get_open_work_orders", "get_next_appointment_slots", "get_prior_tickets",
    "get_sla_position",
]
BUDGET_S = {"translate": 3.0, "asr": 6.0, "vision": 4.0, "prefetch": 4.0, "triage": 1.0, "diagnose": 3.0,
            "grounding": 2.0, "response": 60.0}
#: What the customer sees for each stage. Never the stage name itself.
CHIP = {"translate": "reading", "asr": "reading", "vision": "reading", "prefetch": "checking",
        "triage": "checking", "diagnose": "checking", "grounding": "checking", "response": "writing"}

DDL = """
CREATE SEQUENCE IF NOT EXISTS cases.case_ref_seq START 10001;
CREATE TABLE IF NOT EXISTS cases."case" (
    id              text PRIMARY KEY,
    conversation_id text NOT NULL,
    user_id         text NOT NULL,
    subscriber_id   text,
    origin          text NOT NULL DEFAULT 'customer',
    state           text NOT NULL DEFAULT 'RECEIVED',
    revision        integer NOT NULL DEFAULT 1,
    language        text,
    department      text,
    priority_level  integer,
    band            text,
    approval_status text,
    summary         text,
    opened_at       timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    replied_at      timestamptz,
    closed_at       timestamptz
);
ALTER TABLE cases."case" ADD COLUMN IF NOT EXISTS replied_at timestamptz;
-- The two separate priorities: the request (TriageModel) and our side (grounding rules).
ALTER TABLE cases."case" ADD COLUMN IF NOT EXISTS customer_priority jsonb;
ALTER TABLE cases."case" ADD COLUMN IF NOT EXISTS provider_priority jsonb;
CREATE INDEX IF NOT EXISTS ix_case_open ON cases."case" (state, priority_level DESC, opened_at) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS cases.stage_event (
    id         bigserial PRIMARY KEY,
    case_id    text NOT NULL,
    revision   integer NOT NULL,
    stage      text NOT NULL,
    status     text NOT NULL,
    ms         integer,
    detail     jsonb NOT NULL DEFAULT '{}',
    at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_stage_event_case ON cases.stage_event (case_id, revision, id);
CREATE TABLE IF NOT EXISTS cases.payload (
    case_id    text NOT NULL,
    revision   integer NOT NULL,
    fused_text text NOT NULL,
    provenance jsonb NOT NULL,
    flags      text[] NOT NULL DEFAULT '{}',
    partial    boolean NOT NULL DEFAULT false,
    stages     jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, revision)
);
"""


class Runtime:
    pool: asyncpg.Pool
    nc: Any
    js: Any
    events: asyncio.Queue
    runs: dict[str, tuple[int, asyncio.Task, set[str]]] = {}


rt = Runtime()
http = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_keepalive_connections=50))


# -- plumbing -----------------------------------------------------------------------------------


def _record(case_id: str, rev: int, stage: str, status: str, ms: int | None = None, **detail: Any) -> None:
    """Write-behind: stage events are batched off the hot path."""
    rt.events.put_nowait((case_id, rev, stage, status, ms, json.dumps(detail, default=str)))


async def _flusher() -> None:
    while True:
        batch = [await rt.events.get()]
        await asyncio.sleep(0.25)
        while not rt.events.empty():
            batch.append(rt.events.get_nowait())
        with contextlib.suppress(Exception):
            await rt.pool.executemany(
                "INSERT INTO cases.stage_event (case_id, revision, stage, status, ms, detail) VALUES ($1,$2,$3,$4,$5,$6)",
                batch,
            )


async def _notify(ev: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    """Customer tabs get user.<id>.<kind>; the sim test lab listens on sim.case.<id>."""
    body = json.dumps(payload, default=str).encode()
    await rt.nc.publish(f"user.{ev['user_id']}.{kind}", body)
    await rt.nc.publish(f"sim.case.{payload.get('case_id')}", json.dumps({"kind": kind, **payload}, default=str).encode())


async def stage(name: str, ev: dict[str, Any], case_id: str, rev: int, body: dict[str, Any],
                stub: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any] | None:
    """Run one stage within its budget. None means it missed the budget or failed."""
    rt.runs.get(case_id, (0, None, set()))[2].add(name)
    url = os.environ.get(f"{name.upper()}_URL")
    started = time.perf_counter()
    try:
        with tracing.span(name, run_type="chain" if name != "response" else "llm", inputs=body,
                          stage=name, case_id=case_id, revision=rev, via="service" if url else "stub") as run:
            async with asyncio.timeout(BUDGET_S[name]):
                if url:
                    r = await http.post(f"{url}/run", json=body, headers=tracing.headers())
                    r.raise_for_status()
                    out = r.json()
                else:
                    out = await stub()
            tracing.finish(run, out if isinstance(out, dict) else {"output": out})
        _record(case_id, rev, name, "done", int((time.perf_counter() - started) * 1000), via="service" if url else "stub")
        return out
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a failed branch degrades the case, never stops it
        _record(case_id, rev, name, "timeout" if isinstance(exc, TimeoutError) else "failed",
                int((time.perf_counter() - started) * 1000), error=type(exc).__name__)
        return None


# -- stubs (replaced by services as phases land) ------------------------------------------------


#: Romanised Sinhala and Tamil markers, for when the translation service is not running. Only
#: words that are not also common English, and two hits are needed, so English is never misread.
SINGLISH = frozenset({"mage", "mata", "eka", "eke", "ekak", "wada", "naha", "nane", "mokada", "kranna", "karanna",
                      "wela", "thiyenawa", "kiyala", "denna", "ganna", "neda", "ane", "mama", "oya", "nisa",
                      "wenawa", "karala", "hari", "wenne", "puluwan", "ona", "meka", "kohomada", "dan"})
TANGLISH = frozenset({"enakku", "illai", "illa", "romba", "irukku", "vandhu", "panna", "pannunga", "sollunga",
                      "enna", "epdi", "konjam", "seiyala", "varala", "podhum", "unga", "ennoda"})


def latin_language(text: str) -> str | None:
    words = re.findall(r"[a-z]+", text.lower())
    si, ta = sum(w in SINGLISH for w in words), sum(w in TANGLISH for w in words)
    if max(si, ta) < 2:
        return None
    return "si-Latn" if si >= ta else "ta-Latn"


async def _translate_stub(text: str, hint: str) -> dict[str, Any]:
    """No translation service: keep the text, but still say which language to reply in."""
    lang = hint or "en"
    if lang == "en":
        lang = latin_language(text) or "en"
    return {"language": lang, "reply_language": lang, "text_en": text, "translated": False, "coverage": 1.0}


async def _prefetch(subscriber_id: str | None) -> dict[str, Any]:
    if not subscriber_id:
        return {"results": {}}
    r = await http.post(f"{BUSINESS_URL}/tools:batch", json={
        "subscriber_ref": subscriber_id, "calls": [{"name": n, "args": {}} for n in PREFETCH_TOOLS],
    })
    r.raise_for_status()
    return r.json()


# -- the DAG ------------------------------------------------------------------------------------


async def run(ev: dict[str, Any], case_id: str, rev: int) -> None:
    """One LangSmith trace per case revision; every stage below nests under it."""
    with tracing.span(f"case {case_id} r{rev}", inputs={"text": ev["text"], "attachments": len(ev["attachments"]),
                                                        "language_hint": ev["language_hint"]},
                      case_id=case_id, revision=rev, subscriber_id=ev["subscriber_id"], origin=ev["origin"]) as root:
        tracing.finish(root, await _run(ev, case_id, rev))


async def _run(ev: dict[str, Any], case_id: str, rev: int) -> dict[str, Any]:
    await _set(case_id, state="PROCESSING")
    await _notify(ev, "stage", {"case_id": case_id, "revision": rev, "chip": "reading"})

    # Fusion covers every customer message on the case, so a follow up adds to the story.
    history: list[dict[str, Any]] = []
    if rev > 1:
        with contextlib.suppress(httpx.HTTPError):
            r = await http.get(f"{INQUIRY_URL}/cases/{case_id}/messages")
            history = [m for m in r.json()["messages"] if m["id"] != ev["message_id"]]
    texts = [(m["id"], m["body"]) for m in history] + [(ev["message_id"], ev["text"])]
    joined = "\n".join(t for _, t in texts if t)

    audio = [a for a in ev["attachments"] if a["kind"] == "audio"]
    images = [a for a in ev["attachments"] if a["kind"] == "image"]
    base = {"case_id": case_id, "revision": rev, "language_hint": ev["language_hint"]}

    translate_t = stage("translate", ev, case_id, rev, {**base, "text": joined},
                        lambda: _translate_stub(joined, ev["language_hint"]))
    asr_t = [stage("asr", ev, case_id, rev, {**base, "attachment": a},
                   lambda: asyncio.sleep(0, {"text": "", "confidence": 0.0, "language": ev["language_hint"]}))
             for a in audio]
    vision_t = [stage("vision", ev, case_id, rev, {**base, "attachment": a},
                      lambda: asyncio.sleep(0, {"summary": "", "confidence": 0.0}))
                for a in images]
    prefetch_t = stage("prefetch", ev, case_id, rev, {}, lambda: _prefetch(ev["subscriber_id"]))
    translated, prefetched, *media = await asyncio.gather(translate_t, prefetch_t, *asr_t, *vision_t)
    transcripts, visuals = media[: len(audio)], media[len(audio):]

    if audio:  # "We heard: ..." lets the customer correct a mis-heard voice note
        heard = " ".join((t or {}).get("text", "") for t in transcripts).strip()
        if heard:
            await _notify(ev, "heard", {"case_id": case_id, "text": heard})

    parts = [Part("text", mid, (translated or {}).get("text_en", t) if mid == ev["message_id"] else t) for mid, t in texts]
    parts += [Part("audio", a["id"], (t or {}).get("text_en") or (t or {}).get("text", ""), (t or {}).get("confidence", 0.0))
              for a, t in zip(audio, transcripts)]
    parts += [Part("image", a["id"], (v or {}).get("summary", ""), (v or {}).get("confidence", 0.0))
              for a, v in zip(images, visuals)]
    fused_text, provenance = fuse(parts)
    partial = translated is None or prefetched is None or any(m is None for m in media)
    language = (translated or {}).get("language", ev["language_hint"])
    await rt.pool.execute(
        """INSERT INTO cases.payload (case_id, revision, fused_text, provenance, flags, partial, stages)
           VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (case_id, revision) DO NOTHING""",
        case_id, rev, fused_text, json.dumps(provenance), ev["flags"], partial,
        json.dumps({"visual": visuals, "transcripts": transcripts}, default=str),
    )
    await _set(case_id, state="AGGREGATED", language=language)
    if language not in ("en", None):
        await _notify(ev, "language", {"case_id": case_id, "language": language})

    await _notify(ev, "stage", {"case_id": case_id, "revision": rev, "chip": "checking"})
    facts = (prefetched or {}).get("results", {})
    sla = facts.get("get_sla_position") or {}
    triage = await stage("triage", ev, case_id, rev, {
        "fused_text": fused_text,
        "segment": (facts.get("get_subscriber_profile") or {}).get("segment", "consumer"),
        "repeat_contact": bool((facts.get("get_prior_tickets") or {}).get("is_repeat_contact")),
        "sla_age_score": 1.0 if sla.get("sla_breached") else 0.7 if sla.get("sla_at_risk") else 0.0,
    }, lambda: asyncio.sleep(0, {"department": "technical_support", "base_level": 5, "signals": []}))
    triage = triage or {"department": "technical_support", "base_level": 5, "signals": []}
    customer = triage.get("customer_priority") or {}
    first_level = int(customer.get("level") or triage["base_level"])
    await _set(case_id, state="TRIAGED", department=triage["department"], priority_level=first_level,
               band=band_for(first_level), customer_priority=json.dumps(customer) if customer else None,
               summary=fused_text.split("] ", 1)[-1][:140])
    diagnosis = await stage("diagnose", ev, case_id, rev, {"fused_text": fused_text, "department": triage["department"]},
                            lambda: asyncio.sleep(0, {"fault": None, "confidence": 0.0, "citations": []}))
    tr = translated or {}
    grounded = await stage("grounding", ev, case_id, rev, {
        "case_id": case_id, "revision": rev, "subscriber_id": ev["subscriber_id"],
        "payload": {
            "original_text": joined, "text_en": tr.get("text_en", joined), "language": language,
            "reply_language": tr.get("reply_language", "en"), "native_text": tr.get("native_text"),
            "fused_text": fused_text, "provenance": provenance, "flags": ev["flags"], "partial": partial,
            "opened_at": ev["received_at"],
        },
        "triage": triage, "diagnosis": diagnosis, "prefetch": facts,
        "visual": [{**v, "attachment_id": a["id"]} if v else None for a, v in zip(images, visuals)],
        "transcripts": [{**t, "attachment_id": a["id"]} if t else None for a, t in zip(audio, transcripts)],
    }, lambda: asyncio.sleep(0, {"priority_level": triage["base_level"], "band": "normal", "bundle_id": None}))
    if grounded:
        await _set(case_id, state="DIAGNOSED", priority_level=grounded.get("priority_level"), band=grounded.get("band"),
                   customer_priority=json.dumps(grounded.get("customer_priority")),
                   provider_priority=json.dumps(grounded.get("provider_priority")))

    await _notify(ev, "stage", {"case_id": case_id, "revision": rev, "chip": "writing"})
    outcome = await stage("response", ev, case_id, rev, {
        "case_id": case_id, "revision": rev, "conversation_id": ev["conversation_id"], "user_id": ev["user_id"],
        "language": language, "bundle_id": (grounded or {}).get("bundle_id"),
        "recommended_action": (grounded or {}).get("recommended_action"),
    }, lambda: asyncio.sleep(0, {"decision": "held"}))
    decision = (outcome or {}).get("decision", "held")
    if decision == "released":
        await _set(case_id, state="RESOLVED", approval_status="auto_approved")
    else:
        await _set(case_id, state="AWAITING_APPROVAL", approval_status="pending")
        await _notify(ev, "stage", {"case_id": case_id, "revision": rev, "chip": "held",
                                    "expected": ((prefetched or {}).get("results", {}).get("get_sla_position") or {})
                                    .get("response_due_display")})
    return {"decision": decision, "department": triage["department"], "language": language,
            "priority_level": (grounded or {}).get("priority_level", first_level),
            "customer_priority": customer, "provider_priority": (grounded or {}).get("provider_priority")}


async def _set(case_id: str, **fields: Any) -> None:
    cols = ", ".join(f"{k} = ${i}" for i, k in enumerate(fields, start=2))
    await rt.pool.execute(f'UPDATE cases."case" SET {cols}, updated_at = now() WHERE id = $1', case_id, *fields.values())


async def _on_inquiry(msg) -> None:
    ev = json.loads(msg.data)
    open_case = await rt.pool.fetchrow(
        'SELECT id, revision FROM cases."case" WHERE id = $1 AND closed_at IS NULL', ev.get("open_case_id")
    ) if ev.get("open_case_id") else None

    if open_case:
        case_id, rev = open_case["id"], open_case["revision"] + 1
        await rt.pool.execute('UPDATE cases."case" SET revision = $2, updated_at = now() WHERE id = $1', case_id, rev)
        prev = rt.runs.get(case_id)
        if prev and "response" not in prev[2]:  # not drafting yet: restart with everything
            prev[1].cancel()
        kind = "revised"
    else:
        n = await rt.pool.fetchval("SELECT nextval('cases.case_ref_seq')")
        case_id, rev, kind = f"LL-{n}", 1, "opened"
        await rt.pool.execute(
            """INSERT INTO cases."case" (id, conversation_id, user_id, subscriber_id, origin, language)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            case_id, ev["conversation_id"], ev["user_id"], ev["subscriber_id"], ev["origin"], ev["language_hint"],
        )
    await rt.js.publish(f"case.events.{kind}", json.dumps({
        "kind": kind, "case_id": case_id, "revision": rev, "conversation_id": ev["conversation_id"],
        "message_id": ev["message_id"],
    }).encode(), headers={"Nats-Msg-Id": f"{case_id}-{rev}-{kind}"})
    _record(case_id, rev, "intake", "done", detail_kind=kind)

    task = asyncio.create_task(run(ev, case_id, rev))
    rt.runs[case_id] = (rev, task, set())
    task.add_done_callback(lambda t, c=case_id, r=rev: rt.runs.pop(c, None) if rt.runs.get(c, (None,))[0] == r else None)
    await msg.ack()


async def _on_released(msg) -> None:
    """An approved (or auto) reply went out: the case is answered."""
    e = json.loads(msg.data)
    await _set(e["case_id"], state="RESOLVED",
               approval_status="auto_approved" if e.get("actor") == "auto reply" else "approved")
    await rt.pool.execute('UPDATE cases."case" SET replied_at = coalesce(replied_at, now()) WHERE id = $1',
                          e["case_id"])
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=2, max_size=12,
                                        **POOLER_KWARGS)
    await rt.pool.execute(DDL)
    rt.events = asyncio.Queue()
    flusher = asyncio.create_task(_flusher())
    rt.nc, rt.js = await bus.connect()
    await rt.js.subscribe("inquiry.received", durable="orchestrator", cb=_on_inquiry, manual_ack=True)
    await rt.js.subscribe("case.events.released", durable="orchestrator-released", cb=_on_released, manual_ack=True)
    yield
    flusher.cancel()
    await rt.nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link orchestrator", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _row(r: asyncpg.Record) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(r).items()}


TABS = {
    "needs_approval": "state = 'AWAITING_APPROVAL' AND closed_at IS NULL",
    "open": "closed_at IS NULL AND state <> 'RESOLVED'",
    "all": "true",
}


@app.get("/cases")
async def cases(tab: str = "open", origin: str = "customer", limit: int = 100, q: str = "") -> dict[str, Any]:
    where = TABS.get(tab, TABS["open"])
    rows = await rt.pool.fetch(
        f"""SELECT * FROM cases."case" WHERE origin = $1 AND {where} AND ($3 = '' OR id ILIKE $3 OR summary ILIKE $3)
            ORDER BY closed_at IS NOT NULL, priority_level DESC NULLS LAST, opened_at LIMIT $2""",
        origin, max(1, min(limit, 500)), f"%{q}%" if q else "",
    )
    counts = await rt.pool.fetchrow(
        f"""SELECT count(*) FILTER (WHERE {TABS['needs_approval']}) AS needs_approval,
                   count(*) FILTER (WHERE {TABS['open']}) AS open, count(*) AS all
            FROM cases."case" WHERE origin = $1""", origin)
    return {"cases": [_row(r) for r in rows], "counts": dict(counts)}


@app.get("/stats")
async def stats(hours: int = 24) -> dict[str, Any]:
    """The four admin KPIs, plus cases per hour for the one chart."""
    row = await rt.pool.fetchrow(
        """SELECT count(*) FILTER (WHERE closed_at IS NULL AND state <> 'RESOLVED') AS open_cases,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM replied_at - opened_at))
                      FILTER (WHERE replied_at IS NOT NULL) AS median_reply_s,
                  avg((approval_status = 'auto_approved')::int) FILTER (WHERE replied_at IS NOT NULL) AS auto_share
           FROM cases."case" WHERE origin = 'customer' AND opened_at > now() - make_interval(hours => $1)""", hours)
    p95 = await rt.pool.fetchval(
        """SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY total) FROM (
               SELECT case_id, revision, sum(ms) AS total FROM cases.stage_event
               WHERE at > now() - make_interval(hours => $1) AND stage <> 'response' GROUP BY case_id, revision) t""", hours)
    series = await rt.pool.fetch(
        """SELECT date_trunc('hour', opened_at) AS hour, count(*) AS opened FROM cases."case"
           WHERE origin = 'customer' AND opened_at > now() - make_interval(hours => $1) GROUP BY 1 ORDER BY 1""", hours)
    return {"open_cases": row["open_cases"], "median_reply_s": row["median_reply_s"],
            "auto_share": row["auto_share"], "p95_pipeline_ms": p95,
            "series": [{"hour": r["hour"].isoformat(), "opened": r["opened"]} for r in series]}


@app.post("/cases/{case_id}/escalate")
async def escalate(case_id: str, actor: str) -> dict[str, Any]:
    row = await rt.pool.fetchrow(
        """UPDATE cases."case" SET priority_level = least(10, coalesce(priority_level, 5) + 2), band = 'high',
               state = 'IN_REVIEW', updated_at = now() WHERE id = $1 AND closed_at IS NULL RETURNING *""", case_id)
    if row is None:
        raise HTTPException(404, "That case is not open.")
    _record(case_id, row["revision"], "escalated", "done", by=actor)
    return _row(row)


@app.get("/cases/{case_id}")
async def case(case_id: str) -> dict[str, Any]:
    row = await rt.pool.fetchrow('SELECT * FROM cases."case" WHERE id = $1', case_id)
    if row is None:
        raise HTTPException(404, "No such case.")
    events = await rt.pool.fetch("SELECT * FROM cases.stage_event WHERE case_id = $1 ORDER BY id", case_id)
    payload = await rt.pool.fetchrow(
        "SELECT * FROM cases.payload WHERE case_id = $1 ORDER BY revision DESC LIMIT 1", case_id
    )
    return {"case": _row(row), "stages": [_row(e) for e in events], "payload": _row(payload) if payload else None}


@app.post("/cases/{case_id}/close")
async def close(case_id: str, user_id: str | None = None, reason: str = "solved") -> dict[str, Any]:
    row = await rt.pool.fetchrow(
        """UPDATE cases."case" SET state = 'CLOSED', closed_at = now(), updated_at = now()
           WHERE id = $1 AND closed_at IS NULL AND ($2::text IS NULL OR user_id = $2) RETURNING *""",
        case_id, user_id,
    )
    if row is None:
        raise HTTPException(404, "That case is not open.")
    await rt.js.publish("case.events.closed", json.dumps({
        "kind": "closed", "case_id": case_id, "revision": row["revision"], "conversation_id": row["conversation_id"],
        "subscriber_id": row["subscriber_id"], "department": row["department"], "summary": row["summary"],
        "reason": reason, "opened_at": row["opened_at"].isoformat(), "closed_at": datetime.now(timezone.utc).isoformat(),
    }).encode(), headers={"Nats-Msg-Id": f"{case_id}-closed"})
    return _row(row)
