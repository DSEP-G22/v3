"""Translation service: detect, transliterate and translate in (to English) and out (to si/ta)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from app.lang.langcodes import LanguageCode, base_language, parse
from app.pipeline import TranslationService
from app.translate import (
    GoogleTranslator,
    PassthroughTranslator,
    Translator,
    build,
    split_sentences,
)
from lanka_common.punctuation import normalise

CONTROL_URL = os.environ.get("CONTROL_URL", "http://control:8000")
#: The mt_in / mt_out bindings pick one of these; the baked model is always the safety net.
backends: dict[str, Translator] = {}
_bound: dict[str, tuple[float, str]] = {}  # role -> (fetched at, impl)


def _impl(role: str) -> str:
    """The admin's choice for this role, re-read at most every five seconds."""
    at, impl = _bound.get(role, (0.0, "nllb"))
    if time.monotonic() - at > 5:
        try:
            with urllib.request.urlopen(f"{CONTROL_URL}/bindings/{role}", timeout=2) as r:
                impl = json.load(r)["impl"]
        except Exception:  # noqa: BLE001 - control unreachable: keep the last known choice
            pass
        _bound[role] = (time.monotonic(), impl)
    return impl if impl in backends else "nllb"


def _svc(role: str) -> TranslationService:
    return TranslationService(backends[_impl(role)])


def _with_fallback(role: str, fn: Any) -> Any:
    """Run on the bound backend; if that fails (a cloud backend offline), use the baked model."""
    try:
        return fn(_svc(role))
    except Exception:  # noqa: BLE001
        if _impl(role) == "nllb":
            raise
        return fn(TranslationService(backends["nllb"]))


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    backends["nllb"] = await asyncio.to_thread(build)
    backends["google"] = GoogleTranslator()
    backends["passthrough"] = PassthroughTranslator()
    # Warm: the first real customer should not pay for loading weights.
    await asyncio.to_thread(TranslationService(backends["nllb"]).normalize_text, "මගේ අන්තර්ජාලය වැඩ කරන්නේ නැහැ")
    yield


app = FastAPI(title="Lanka Link translation", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, Any]:
    if not backends:
        return {"status": "loading", "backend": None}
    mt_in, mt_out = await asyncio.to_thread(lambda: (_impl("mt_in"), _impl("mt_out")))
    return {"status": "ok", "backend": backends["nllb"].name, "mt_in": backends[mt_in].name, "mt_out": backends[mt_out].name}


class In(BaseModel):
    text: str
    language_hint: str | None = None  # the customer's declared language, if they chose one
    language_override: str | None = None  # set by staff: skip detection and trust this


@app.post("/run")
async def run(body: In) -> dict[str, Any]:
    started = time.perf_counter()
    declared = parse(body.language_hint) if body.language_hint in ("si", "ta", "si-Latn", "ta-Latn") else None
    # Script hints from intake are "en" for all Latin text, so they are not a declaration.
    if declared in (LanguageCode.SI, LanguageCode.TA) and not any(0x0B80 <= ord(c) <= 0x0DFF for c in body.text):
        declared = None
    if body.language_override in ("en", "si", "ta", "si-Latn", "ta-Latn"):
        declared = parse(body.language_override)
    out = await asyncio.to_thread(_with_fallback, "mt_in", lambda s: s.normalize_text(body.text, declared))
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
    text, translated = await asyncio.to_thread(_with_fallback, "mt_out", lambda s: s.translate_outbound(body.text, target))
    return {"text": normalise(text), "translated": translated, "language": target.value,
            "backend": backends[_impl("mt_out")].name}


class Sentences(BaseModel):
    text: str


@app.post("/sentences")
async def sentences(body: Sentences) -> dict[str, list[str]]:
    """The splitter the response service uses to stream and translate per sentence."""
    return {"sentences": split_sentences(body.text)}
