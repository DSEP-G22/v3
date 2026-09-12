"""Response: draft from the ContextBundle, stream it safely, release or hold.

    eligibility (before drafting) -> generate_from_bundle (streamed) -> per-sentence compliance
    -> translate-out per sentence (si/ta) -> customer stream, or hold at the first bad sentence
    -> whole-draft compliance -> release (case.events.released) or wait for approval

The drafting model sees the bundle and nothing else: this service has no business, MinIO,
audio, image or inquiry client (tests/architecture). Inquiry writes the released message
when it sees case.events.released.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import policy
from app.render import render_prompt
from lanka_common import bus
from lanka_common.contracts import ContextBundle
from lanka_common.db import POOLER_KWARGS, parse_neon_key
from lanka_common.llm import LLMUnavailable, Stub, build
from lanka_common.punctuation import normalise

GROUNDING_URL = os.environ.get("GROUNDING_URL", "http://grounding:8000")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")
TRANSLATE_URL = os.environ.get("TRANSLATE_URL", "http://translation:8000")
SIGN_OFF = "Lanka Link customer support"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

DDL = """
CREATE TABLE IF NOT EXISTS response.draft (
    case_id     text NOT NULL,
    revision    integer NOT NULL,
    text_en     text NOT NULL,
    text_out    text,
    language    text NOT NULL DEFAULT 'en',
    model       text NOT NULL,
    findings    jsonb NOT NULL DEFAULT '[]',
    status      text NOT NULL CHECK (status IN ('held', 'released', 'superseded', 'declined', 'refused')),
    reasons     jsonb NOT NULL DEFAULT '[]',
    action      jsonb,
    decided_by  text,
    decided_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, revision)
);
"""


class Runtime:
    pool: asyncpg.Pool
    nc: Any
    js: Any
    llm: Any = Stub()
    fallback: Any = None
    binding: dict[str, Any] = {}
    policies: dict[str, dict[str, Any]] = {}


rt = Runtime()
http = httpx.AsyncClient(timeout=30)


async def _bind() -> None:
    with contextlib.suppress(httpx.HTTPError, LLMUnavailable, KeyError):
        r = await http.get(f"{CONTROL_URL}/bindings/llm_draft")
        r.raise_for_status()
        b = rt.binding = r.json()
        rt.llm = build(b["impl"], b["model_version"], b.get("params"), dict(os.environ))
        fb = (b.get("params") or {}).get("fallback")
        rt.fallback = build(fb["impl"], fb["model_version"], {}, dict(os.environ)) if fb else None
    rt.policies.clear()


async def _policy(department: str) -> dict[str, Any]:
    if department not in rt.policies:
        try:
            r = await http.get(f"{CONTROL_URL}/autoreply/{department}")
            r.raise_for_status()
            rt.policies[department] = r.json()
        except httpx.HTTPError:
            return dict(policy.DEFAULT_POLICY)  # fail closed
    return rt.policies[department]


async def _on_control(msg) -> None:
    await _bind()
    await msg.ack()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    rt.pool = await asyncpg.create_pool(parse_neon_key(os.environ["NEON_KEY"]).pooled, min_size=1, max_size=6,
                                        **POOLER_KWARGS)
    await rt.pool.execute(DDL)
    await _bind()
    rt.nc, rt.js = await bus.connect()
    await rt.js.subscribe("control.changed", durable="response", cb=_on_control, manual_ack=True)
    yield
    await rt.nc.drain()
    await rt.pool.close()


app = FastAPI(title="Lanka Link response", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "llm_draft": rt.binding or {"impl": "stub"}}


# -- the only function that talks to the drafting model ------------------------------------------


async def generate_from_bundle(bundle: ContextBundle) -> AsyncIterator[str]:
    """Stream a reply drafted from the bundle. Takes the bundle and nothing else, by design."""
    prompt = render_prompt(bundle)
    produced = False
    try:
        async for token in rt.llm.stream(prompt):
            produced = True
            yield token
    except LLMUnavailable:
        if produced or rt.fallback is None:
            raise
        async for token in rt.fallback.stream(prompt):
            yield token


# -- the stage ------------------------------------------------------------------------------------


async def _translate(text: str, lang: str) -> str:
    if lang not in ("si", "ta") or not TRANSLATE_URL:  # empty URL: CI profile without the model services
        return text
    r = await http.post(f"{TRANSLATE_URL}/run_out", json={"text": text, "target": lang})
    r.raise_for_status()
    return r.json()["text"]


class RunIn(BaseModel):
    case_id: str
    revision: int
    conversation_id: str
    user_id: str
    language: str = "en"
    bundle_id: str | None = None
    recommended_action: dict[str, Any] | None = None


@app.post("/run")
async def run(body: RunIn) -> dict[str, Any]:
    started = time.perf_counter()
    r = await http.get(f"{GROUNDING_URL}/bundles/{body.case_id}/{body.revision}")
    if r.status_code != 200:
        raise HTTPException(409, "No bundle to draft from.")
    bundle = ContextBundle.model_validate(r.json())
    lang = bundle.reply_language if bundle.reply_language in ("en", "si", "ta") else "en"
    action = (body.recommended_action or {}).get("action_id")
    rules = await _policy(bundle.department)
    await rt.pool.execute(
        "UPDATE response.draft SET status = 'superseded' WHERE case_id = $1 AND revision < $2 AND status = 'held'",
        body.case_id, body.revision)

    if not bundle.completeness.sufficient:
        text = ("No reply was drafted. The system could not retrieve "
                f"{', '.join(bundle.completeness.missing)} for this customer, so please reply by hand.")
        return await _hold(body, bundle, text, None, lang, "none", [], ["Grounding is incomplete."], started)

    pre = policy.eligibility(rules, bundle.department, bundle.priority.level, bundle.completeness.score, action, False)
    permitted = {a.action_id for a in bundle.permitted_actions}
    streaming = pre.auto  # only an eligible draft ever streams to the customer
    subject = f"user.{body.user_id}"
    buffer, parts, sent, stopped = "", [], 0, None

    async def emit(sentence: str) -> None:
        nonlocal sent, stopped, streaming
        if not streaming or not sentence.strip():
            return
        if findings := policy.check_sentence(sentence, permitted):
            streaming, stopped = False, findings
            await rt.nc.publish(f"{subject}.stage", json.dumps({"case_id": body.case_id, "chip": "held"}).encode())
            return
        await rt.nc.publish(f"{subject}.draft", json.dumps({
            "case_id": body.case_id, "index": sent, "text": await _translate(sentence, lang)}).encode())
        sent += 1

    try:
        async for token in generate_from_bundle(bundle):
            await rt.nc.publish(f"case.{body.case_id}.stream", token.encode())  # raw, console only
            buffer += token
            *done, buffer = _SENTENCE_END.split(buffer)
            for sentence in done:
                parts.append(sentence)
                await emit(sentence)
    except LLMUnavailable as exc:
        text = f"No reply was drafted because the language model could not be reached ({exc}). Reply by hand."
        return await _hold(body, bundle, text, None, lang, "unavailable", [], ["The model was unavailable."], started)
    if buffer.strip():
        parts.append(buffer)
        await emit(buffer)

    text_en = normalise(" ".join(p.strip() for p in parts)) + f"\n\n{SIGN_OFF}"
    findings = policy.check_draft(text_en, bundle) + (stopped or [])
    decision = policy.finalise(pre, rules, findings)
    model = f"{rt.llm.name}:{rt.llm.model}"
    if not decision.auto:
        return await _hold(body, bundle, text_en, await _translate(text_en, lang) if lang != "en" else None, lang,
                           model, findings, decision.reasons, started, body.recommended_action)

    text_out = await _translate(text_en, lang)
    await _store(body, text_en, text_out, lang, model, findings, "released", [], body.recommended_action, "auto reply")
    await _release(body, text_en, text_out, lang)
    return {"decision": "released", "ms": int((time.perf_counter() - started) * 1000)}


async def _store(body: RunIn, text_en: str, text_out: str | None, lang: str, model: str,
                 findings: list[dict[str, Any]], status: str, reasons: list[str], action: dict[str, Any] | None,
                 decided_by: str | None = None) -> None:
    await rt.pool.execute(
        """INSERT INTO response.draft (case_id, revision, text_en, text_out, language, model, findings, status,
                                       reasons, action, decided_by, decided_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, CASE WHEN $11 IS NULL THEN NULL ELSE now() END)
           ON CONFLICT (case_id, revision) DO UPDATE SET text_en = $3, text_out = $4, findings = $7, status = $8,
               reasons = $9, action = $10, decided_by = $11""",
        body.case_id, body.revision, text_en, text_out, lang, model, json.dumps(findings), status,
        json.dumps(reasons), json.dumps(action) if action else None, decided_by)


async def _hold(body, bundle, text_en, text_out, lang, model, findings, reasons, started, action=None):
    await _store(body, text_en, text_out, lang, model, findings, "held", reasons, action)
    await rt.nc.publish(f"user.{body.user_id}.stage", json.dumps({
        "case_id": body.case_id, "chip": "held", "expected": bundle.sla.response_due_display}).encode())
    await rt.js.publish("case.events.held", json.dumps({
        "kind": "held", "case_id": body.case_id, "revision": body.revision, "reasons": reasons}).encode())
    return {"decision": "held", "reasons": reasons, "ms": int((time.perf_counter() - started) * 1000)}


async def _release(body: RunIn, text_en: str, text_out: str, lang: str, actor: str = "auto reply") -> None:
    await rt.js.publish("case.events.released", json.dumps({
        "kind": "released", "case_id": body.case_id, "revision": body.revision,
        "conversation_id": body.conversation_id, "user_id": body.user_id, "text": text_out, "text_en": text_en,
        "language": lang, "actor": actor,
    }).encode(), headers={"Nats-Msg-Id": f"{body.case_id}-{body.revision}-released"})


# -- approval (the console) ------------------------------------------------------------------------


@app.get("/drafts/{case_id}")
async def drafts(case_id: str) -> dict[str, Any]:
    rows = await rt.pool.fetch("SELECT * FROM response.draft WHERE case_id = $1 ORDER BY revision DESC", case_id)
    return {"drafts": [{**dict(r), "findings": json.loads(r["findings"]), "reasons": json.loads(r["reasons"]),
                        "action": json.loads(r["action"]) if r["action"] else None,
                        "created_at": r["created_at"].isoformat(),
                        "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None} for r in rows]}


class Decide(BaseModel):
    approved: bool
    actor: str
    conversation_id: str
    user_id: str
    text_en: str | None = None  # the agent's edit, if any
    note: str = ""


@app.post("/drafts/{case_id}/{revision}/decide")
async def decide(case_id: str, revision: int, d: Decide) -> dict[str, Any]:
    row = await rt.pool.fetchrow(
        "SELECT * FROM response.draft WHERE case_id = $1 AND revision = $2 AND status = 'held'", case_id, revision)
    if row is None:
        raise HTTPException(409, "That draft has already been decided or replaced.")
    if not d.approved:  # silent to the customer, as in v2
        await rt.pool.execute("""UPDATE response.draft SET status = 'declined', decided_by = $3, decided_at = now(),
                                 reasons = $4 WHERE case_id = $1 AND revision = $2""",
                              case_id, revision, d.actor, json.dumps([d.note or "Sent back."]))
        return {"status": "declined"}
    text_en = normalise(d.text_en or row["text_en"])
    r = await http.get(f"{GROUNDING_URL}/bundles/{case_id}/{revision}")
    bundle = ContextBundle.model_validate(r.json())
    blocking = [f for f in policy.check_draft(text_en, bundle) if f["severity"] == "error"]
    if blocking:
        raise HTTPException(422, "; ".join(f["message"] for f in blocking))
    text_out = await _translate(text_en, row["language"])
    body = RunIn(case_id=case_id, revision=revision, conversation_id=d.conversation_id, user_id=d.user_id,
                 language=row["language"])
    await rt.pool.execute("""UPDATE response.draft SET status = 'released', text_en = $3, text_out = $4,
                             decided_by = $5, decided_at = now() WHERE case_id = $1 AND revision = $2""",
                          case_id, revision, text_en, text_out, d.actor)
    await _release(body, text_en, text_out, row["language"], actor=d.actor)
    return {"status": "released", "action": json.loads(row["action"]) if row["action"] else None}


@app.post("/preview")
async def preview(case_id: str, revision: int, lang: str) -> dict[str, str]:
    """The si/ta rendering of the current draft, for the console's preview."""
    row = await rt.pool.fetchrow("SELECT text_en FROM response.draft WHERE case_id = $1 AND revision = $2",
                                 case_id, revision)
    if row is None:
        raise HTTPException(404, "No draft.")
    return {"text": await _translate(row["text_en"], lang)}


# ponytail: asyncio used only for the lifespan; kept explicit for readers of the stream code.
_ = asyncio
