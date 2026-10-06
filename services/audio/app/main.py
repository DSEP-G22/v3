"""Audio: voice notes to text with faster-whisper small int8, then English via translation.

Fixes the v2 regression where voice notes were never transcribed: this service is always in
the path for audio attachments, and an empty transcript is reported as such, not dropped.

Three models: base Whisper small detects the language and transcribes English; a Sinhala
fine-tune transcribes Sinhala, which the base model hears poorly and slowly; a Tamil fine-tune
transcribes Tamil. Detection
is narrowed to the three languages a Lanka Link customer speaks, so Sinhala that Whisper
mistakes for Hindi or Malayalam still lands on the Sinhala model.

Both fine-tunes are hot swappable: the `speech` binding (admin, Models page) names one of
SINHALA_MODELS and the `speech_ta` binding one of TAMIL_MODELS; a watcher loads the choice in
the background and swaps it in between notes, with no restart. "faster-whisper-small-int8"
means no fine-tune for that language, the base model.
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
CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")
MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
#: Binding model id -> (path or Hub repo, revision). All baked into the image, int8 CTranslate2.
SINHALA_MODELS: dict[str, tuple[str, str | None]] = {
    # Yohan2003/whisper-small-sinhala-run11-v6-e6, converted at build (convert.py). Test CER 4.4%.
    "whisper-small-si-run11-int8": (os.path.join(MODEL_DIR, "whisper", "si-run11-int8"), None),
    # janiduchamika/whisper-small-sinhala-general-185k, its own CT2 build. Test WER 25%.
    "whisper-small-si-185k-int8": ("janiduchamika/faster-whisper-small-sinhala-ct2-float16",
                                   "9b9e64f9aee9bd22af26ba93ba7dc93f39b3cc4e"),
}
TAMIL_MODELS: dict[str, tuple[str, str | None]] = {
    # vasista22/whisper-tamil-small (IIT Madras), converted at build (convert.py). Research and
    # numbers: docs/TAMIL-ASR.md.
    "whisper-small-ta-vasista22-int8": (os.path.join(MODEL_DIR, "whisper", "ta-vasista22-int8"), None),
}
BASE_ONLY = "faster-whisper-small-int8"
#: language -> (binding role, its models). Each language swaps on its own binding.
FINE_TUNES = {"si": ("speech", SINHALA_MODELS), "ta": ("speech_ta", TAMIL_MODELS)}
#: What runs before the bindings are read, and whenever control cannot be reached at boot.
DEFAULT_SPEECH = os.environ.get("SPEECH_MODEL", "whisper-small-si-run11-int8")
DEFAULT_SPEECH_TA = os.environ.get("SPEECH_TA_MODEL", "whisper-small-ta-vasista22-int8")
WATCH_S = 10.0
SPOKEN = ("si", "ta", "en")

http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=20.0))
model = None
#: language -> (fine-tuned model, its binding id). One tuple each, so a swap is a single assignment.
fine: dict[str, tuple[Any, str]] = {"si": (None, BASE_ONLY), "ta": (None, BASE_ONLY)}
_kw: dict[str, Any] = {}


def _load(name: str, lang: str = "si") -> Any:
    from faster_whisper import WhisperModel

    path, revision = FINE_TUNES[lang][1][name]
    m = WhisperModel(path, revision=revision, **_kw)
    list(m.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)[0])  # warm before it takes traffic
    return m


async def use(name: str, lang: str = "si") -> None:
    """Swap one language's fine-tune. The new one loads and warms first; a note already being
    transcribed keeps the model it started with, and the old one is freed when it finishes."""
    if name == fine[lang][1] or (name != BASE_ONLY and name not in FINE_TUNES[lang][1]):
        return
    try:
        loaded = None if name == BASE_ONLY else await asyncio.to_thread(_load, name, lang)
    except Exception:  # noqa: BLE001 - weights missing or unreadable: keep what is running
        return
    fine[lang] = (loaded, name)


async def _bound(role: str = "speech") -> str | None:
    with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
        r = await http.get(f"{CONTROL_URL}/bindings/{role}", timeout=3)
        r.raise_for_status()
        return r.json()["model_version"]
    return None


async def _watch() -> None:
    while True:
        await asyncio.sleep(WATCH_S)
        for lang, (role, _) in FINE_TUNES.items():
            if name := await _bound(role):
                await use(name, lang)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global model
    from faster_whisper import WhisperModel

    device = os.environ.get("ASR_DEVICE", "cpu")
    _kw.update(device=device, compute_type="float16" if device == "cuda" else "int8",
               cpu_threads=int(os.environ.get("OMP_NUM_THREADS", "4")),
               download_root=os.path.join(MODEL_DIR, "whisper"))
    model = await asyncio.to_thread(WhisperModel, os.environ.get("WHISPER_MODEL", "small"), **{**_kw})
    # Warm: one second of silence through the full decode path.
    await asyncio.to_thread(lambda: list(model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)[0]))
    await use(await _bound("speech") or DEFAULT_SPEECH, "si")
    await use(await _bound("speech_ta") or DEFAULT_SPEECH_TA, "ta")
    watcher = asyncio.create_task(_watch())
    yield
    watcher.cancel()


app = FastAPI(title="Lanka Link audio", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok" if model else "loading", "speech_model": fine["si"][1], "speech_model_ta": fine["ta"][1]}


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
    fm, fname = fine.get(lang, (None, BASE_ONLY))  # one read: a hot swap mid-note must not change the model under it
    m = fm if fm is not None else model
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
        "model": fname if m is not model else f"faster-whisper-{os.environ.get('WHISPER_MODEL', 'small')}",
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
    assert set(SINHALA_MODELS) | {BASE_ONLY} >= {DEFAULT_SPEECH}
    assert set(TAMIL_MODELS) | {BASE_ONLY} >= {DEFAULT_SPEECH_TA}
    print("language routing ok")
