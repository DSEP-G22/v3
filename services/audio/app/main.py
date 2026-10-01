"""Audio: voice notes to text with faster-whisper small int8, then English via translation.

Fixes the v2 regression where voice notes were never transcribed: this service is always in
the path for audio attachments, and an empty transcript is reported as such, not dropped.

Two models: base Whisper small detects the language and transcribes English and Tamil; a
Whisper small fine-tuned on 185k Sinhala clips (SINHALA_MODEL) transcribes Sinhala, which
the base model hears poorly and slowly. Detection is narrowed to the three languages a Lanka
Link customer speaks, so Sinhala that Whisper mistakes for Hindi or Malayalam still lands on
the Sinhala model.
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
#: Fine-tuned Sinhala Whisper small, CTranslate2 (pinned; baked into the image). Empty turns it off.
SINHALA_MODEL = os.environ.get("SINHALA_MODEL", "janiduchamika/faster-whisper-small-sinhala-ct2-float16")
SINHALA_REVISION = os.environ.get("SINHALA_REVISION", "9b9e64f9aee9bd22af26ba93ba7dc93f39b3cc4e")
SPOKEN = ("si", "ta", "en")

http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=20.0))
model = None
si_model = None


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global model, si_model
    from faster_whisper import WhisperModel

    device = os.environ.get("ASR_DEVICE", "cpu")
    kw = {"device": device, "compute_type": "float16" if device == "cuda" else "int8",
          "cpu_threads": int(os.environ.get("OMP_NUM_THREADS", "4")),
          "download_root": os.path.join(os.environ.get("MODEL_DIR", "/models"), "whisper")}
    model = await asyncio.to_thread(WhisperModel, os.environ.get("WHISPER_MODEL", "small"), **kw)
    if SINHALA_MODEL:
        try:
            si_model = await asyncio.to_thread(WhisperModel, SINHALA_MODEL, revision=SINHALA_REVISION, **kw)
        except Exception:  # noqa: BLE001 - missing weights: Sinhala goes to the base model, as before
            si_model = None
    # Warm: one second of silence through the full decode path of each model.
    for m in (model, si_model):
        if m is not None:
            await asyncio.to_thread(lambda m=m: list(m.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)[0]))
    yield


app = FastAPI(title="Lanka Link audio", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok" if model else "loading"}


class In(BaseModel):
    attachment: dict[str, Any]
    language_hint: str | None = None


def spoken_language(probs: list[tuple[str, float]], hint: str | None) -> str:
    """Sinhala, unless the audio is clearly English or Tamil. Whisper hears English well and Tamil
    fairly, but files most Sinhala under Hindi, Urdu, Kannada or even Tamil at low probability
    (5 of 10 test clips). Only these three languages reach us, so anything unclear is Sinhala.
    A customer who typed in Tamil keeps Tamil; one who typed Sinhala needs stronger English."""
    p = dict(probs)
    top = max(p, key=p.get) if p else "si"
    if hint == "ta" and top != "en":
        return "ta"
    if top == "en" and p["en"] >= (0.8 if hint == "si" else 0.6):
        return "en"
    if top == "ta" and p["ta"] >= 0.5:
        return "ta"
    return "si"


def _transcribe(data: bytes, hint: str | None) -> dict[str, Any]:
    """The language comes from the audio, not from what the customer typed: forcing it from the
    text is wrong when they differ (a Sinhala speaker typing English, say) and far slower, since a
    20 second English note took 42 seconds forced to Sinhala against 5 seconds detected. The
    typed language only settles a near tie between English and Sinhala or Tamil."""
    from faster_whisper import decode_audio

    audio = decode_audio(io.BytesIO(data))
    duration = len(audio) / 16000
    if duration > MAX_SECONDS:
        return {"text": "", "language": hint, "confidence": 0.0, "duration_s": round(duration, 2),
                "note": "longer than a minute"}
    _, _, probs = model.detect_language(audio, vad_filter=True)
    lang = spoken_language(probs, hint)
    m = si_model if lang == "si" and si_model is not None else model
    # Greedy, no timestamps, one retry at a higher temperature: a Sinhala note is several times
    # the tokens of an English one, and the default five retries could each re-decode it.
    # Without the Sinhala model, base Whisper keeps detecting for itself (forced Sinhala loops).
    segments, info = m.transcribe(audio, language=None if lang == "si" and m is model else lang, vad_filter=True,
                                  beam_size=1, without_timestamps=True, condition_on_previous_text=False,
                                  temperature=(0.0, 0.4))
    segs = list(segments)
    return {
        "text": normalise(" ".join(s.text.strip() for s in segs).strip()),
        "language": info.language or lang,
        "confidence": weighted([(s.start, s.end, s.avg_logprob) for s in segs]),
        "duration_s": round(duration, 2),
        "asr_model": "sinhala-finetuned" if m is si_model else "base",
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
    out["model"] = (SINHALA_MODEL if out.pop("asr_model", "base") == "sinhala-finetuned"
                    else f"faster-whisper-{os.environ.get('WHISPER_MODEL', 'small')}")
    out["ms"] = int((time.perf_counter() - started) * 1000)
    return out


if __name__ == "__main__":
    # Probabilities as base Whisper small gave them for real Sinhala clips, and for clear English.
    assert spoken_language([("hi", 0.2), ("ne", 0.2), ("bn", 0.1)], None) == "si"
    assert spoken_language([("ur", 0.68), ("hi", 0.17), ("en", 0.03)], None) == "si"
    assert spoken_language([("ta", 0.12), ("ru", 0.11), ("hi", 0.08)], None) == "si"
    assert spoken_language([("kn", 0.33), ("si", 0.28)], None) == "si"
    assert spoken_language([("en", 0.93)], None) == "en"
    assert spoken_language([("en", 0.7)], "si") == "si"
    assert spoken_language([("ta", 0.81)], None) == "ta"
    assert spoken_language([("ml", 0.5), ("ta", 0.3)], "ta") == "ta"
    print("language routing ok")
