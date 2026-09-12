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
from fastapi import FastAPI
from pydantic import BaseModel

from app.confidence import LOW_CONFIDENCE, weighted
from lanka_common.punctuation import normalise

INQUIRY_URL = os.environ.get("INQUIRY_URL", "http://inquiry:8000")
TRANSLATE_URL = os.environ.get("TRANSLATE_URL", "http://translation:8000")
MAX_SECONDS = 61.0

http = httpx.AsyncClient(timeout=20)
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
    segments, info = model.transcribe(io.BytesIO(data), language=hint, vad_filter=True, beam_size=1,
                                      condition_on_previous_text=False)
    if info.duration > MAX_SECONDS:
        return {"text": "", "language": info.language, "confidence": 0.0, "duration_s": info.duration,
                "note": "longer than a minute"}
    segs = list(segments)
    return {
        "text": normalise(" ".join(s.text.strip() for s in segs).strip()),
        "language": hint or info.language,
        "confidence": weighted([(s.start, s.end, s.avg_logprob) for s in segs]),
        "duration_s": round(info.duration, 2),
    }


@app.post("/run")
async def run(body: In) -> dict[str, Any]:
    started = time.perf_counter()
    r = await http.get(f"{INQUIRY_URL}/internal/attachments/{body.attachment['id']}/bytes")
    r.raise_for_status()
    # Only a native-language hint helps; an "en" script hint from an empty text is noise.
    hint = body.language_hint if body.language_hint in ("si", "ta") else None
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
