"""Audio: voice notes to text with faster-whisper small int8, then English via translation.

Fixes the v2 regression where voice notes were never transcribed: this service is always in
the path for audio attachments, and an empty transcript is reported as such, not dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.confidence import LOW_CONFIDENCE, weighted
from lanka_common.punctuation import normalise

INQUIRY_URL = os.environ.get("INQUIRY_URL", "http://inquiry:8000")
TRANSLATE_URL = os.environ.get("TRANSLATE_URL", "http://translation:8000")
MAX_SECONDS = 61.0

http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=20.0))
model = None


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global model
    from faster_whisper import WhisperModel

    device = os.environ.get("ASR_DEVICE", "cpu")
    model = await asyncio.to_thread(
        WhisperModel, os.environ.get("WHISPER_MODEL", "small"), device=device,
        compute_type="float16" if device == "cuda" else "int8",
        cpu_threads=int(os.environ.get("OMP_NUM_THREADS", "4")),
        download_root=os.path.join(os.environ.get("MODEL_DIR", "/models"), "whisper"),
    )
    # Warm: one second of silence through the full decode path.
    await asyncio.to_thread(lambda: list(model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)[0]))
    yield


app = FastAPI(title="Lanka Link audio", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok" if model else "loading"}


class In(BaseModel):
    attachment: dict[str, Any]
    language_hint: str | None = None


def _transcribe(data: bytes, hint: str | None) -> dict[str, Any]:
    """Whisper detects the language itself. Forcing it from the text's language is both wrong
    when they differ (a Sinhala speaker typing English, say) and far slower: a 20 second English
    note took 42 seconds forced to Sinhala against 5 seconds detected, which blew the budget and
    lost every voice note. The hint is kept only to fill in when detection returns nothing."""
    segments, info = model.transcribe(io.BytesIO(data), vad_filter=True, beam_size=1,
                                      condition_on_previous_text=False)
    if info.duration > MAX_SECONDS:
        return {"text": "", "language": info.language, "confidence": 0.0, "duration_s": info.duration,
                "note": "longer than a minute"}
    segs = list(segments)
    return {
        "text": normalise(" ".join(s.text.strip() for s in segs).strip()),
        "language": info.language or hint,
        "confidence": weighted([(s.start, s.end, s.avg_logprob) for s in segs]),
        "duration_s": round(info.duration, 2),
    }


#: One transcription at a time. A thread cannot be cancelled, so a caller that gave up would
#: otherwise leave its transcription running and every later voice note would crawl behind it.
_one = asyncio.Semaphore(1)


@app.post("/run")
async def run(body: In, request: Request) -> dict[str, Any]:
    started = time.perf_counter()
    r = await http.get(f"{INQUIRY_URL}/internal/attachments/{body.attachment['id']}/bytes")
    r.raise_for_status()
    # A fallback only: what the customer typed in, when the audio itself gives nothing away.
    hint = body.language_hint if body.language_hint in ("si", "ta") else None
    async with _one:
        if await request.is_disconnected():
            raise HTTPException(499, "The caller stopped waiting.")
        out = await asyncio.to_thread(_transcribe, r.content, hint)
    out["low_confidence"] = out["confidence"] < LOW_CONFIDENCE
    out["text_en"] = out["text"]
    if out["text"] and out["language"] in ("si", "ta"):
        t = await http.post(f"{TRANSLATE_URL}/run", json={"text": out["text"], "language_hint": out["language"]})
        if t.status_code == 200:
            out["text_en"] = t.json()["text_en"]
    out["model"] = f"faster-whisper-{os.environ.get('WHISPER_MODEL', 'small')}"
    out["ms"] = int((time.perf_counter() - started) * 1000)
    return out
