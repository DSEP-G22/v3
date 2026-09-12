"""Translation service: detect, transliterate and translate in (to English) and out (to si/ta)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from app.lang.langcodes import LanguageCode, base_language, parse
from app.pipeline import TranslationService
from app.translate import build, split_sentences
from lanka_common.punctuation import normalise

svc: TranslationService | None = None


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global svc
    svc = TranslationService(await asyncio.to_thread(build))
    # Warm: the first real customer should not pay for loading weights.
    await asyncio.to_thread(svc.normalize_text, "මගේ අන්තර්ජාලය වැඩ කරන්නේ නැහැ")
    yield


app = FastAPI(title="Lanka Link translation", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok" if svc else "loading", "backend": svc.translator.name if svc else None}


class In(BaseModel):
    text: str
    language_hint: str | None = None  # the customer's declared language, if they chose one


@app.post("/run")
async def run(body: In) -> dict[str, Any]:
    started = time.perf_counter()
    declared = parse(body.language_hint) if body.language_hint in ("si", "ta", "si-Latn", "ta-Latn") else None
    # Script hints from intake are "en" for all Latin text, so they are not a declaration.
    if declared in (LanguageCode.SI, LanguageCode.TA) and not any(0x0B80 <= ord(c) <= 0x0DFF for c in body.text):
        declared = None
    out = await asyncio.to_thread(svc.normalize_text, body.text, declared)
    lang = out.detected_language
    return {
        "language": lang.value,
        "reply_language": base_language(lang).value if lang != LanguageCode.UNKNOWN else "en",
        "script": out.detected_script.value,
        "confidence": out.detection_confidence,
        "native_text": out.native_text,
        "text_en": normalise(out.english_text),
        "translated": out.translated,
        "transliterated": out.transliterated,
        "mixed": out.mixed,
        "backend": out.backend,
        "ms": int((time.perf_counter() - started) * 1000),
    }


class Out(BaseModel):
    text: str
    target: str


@app.post("/run_out")
async def run_out(body: Out) -> dict[str, Any]:
    target = base_language(parse(body.target))
    text, translated = await asyncio.to_thread(svc.translate_outbound, body.text, target)
    return {"text": normalise(text), "translated": translated, "language": target.value}


class Sentences(BaseModel):
    text: str


@app.post("/sentences")
async def sentences(body: Sentences) -> dict[str, list[str]]:
    """The splitter the response service uses to stream and translate per sentence."""
    return {"sentences": split_sentences(body.text)}
