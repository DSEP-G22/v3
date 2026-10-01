"""Image: router photos to a short visual summary. ONNX classifier + HSV LED colours.

The classifier (EfficientNet-B0, model testing notebook 02) says which router component the
photo shows; the LED pass says which indicator colours are lit. Grounding turns colour into
meaning using the customer's actual device model.

A photo the classifier does not recognise (its best class below VLM_BELOW: a bill, a phone
screen, a cable outside, anything it was not trained on) goes to a vision language model for
a short description instead. That call is capped at VLM_RPM per minute, so a burst of photos
never trips the provider's rate limit; past the cap, or with no key, the classifier answers.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import contextlib
import io
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel

from app.led import lit_colours

INQUIRY_URL = os.environ.get("INQUIRY_URL", "http://inquiry:8000")
#: Classifier labels in words the writer can repeat, so a power plug is never read as the WAN cable.
PART = {
    "power": "power socket", "power-cable": "power cable", "power-conn": "power connector (the round power plug)",
    "fiber-cable": "fibre (internet) cable", "lan-cable": "network (LAN) cable", "lans": "LAN ports",
    "lans-conn": "LAN cable connector", "phone": "phone socket", "phone-cable": "phone cable",
    "phone-conn": "phone connector", "usb": "USB port", "usb-cable": "USB cable", "usb-conn": "USB connector",
}
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))
VLM_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
VLM_MODEL = os.environ.get("VISION_VLM_MODEL", "gemini-flash-latest")
VLM_BELOW = float(os.environ.get("VLM_BELOW", "0.6"))
VLM_RPM = int(os.environ.get("VLM_RPM", "8"))
VLM_TIMEOUT_S = 8.0
VLM_PROMPT = ("A customer of a telecom provider sent this photo to support. In at most two short, plain "
              "sentences, say what it shows that matters for their support request: the device, document or "
              "screen, which part of it, any lights and their colours, any error text, any visible damage. "
              "Only describe what is visible; do not guess. Reply with the description only.")

http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=20.0))
state: dict[str, Any] = {}


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = int(os.environ.get("OMP_NUM_THREADS", "1"))
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if os.environ.get("VISION_DEVICE") == "cuda" \
        else ["CPUExecutionProvider"]
    state["sess"] = ort.InferenceSession(str(MODEL_DIR / "router.onnx"), opts, providers=providers)
    state["meta"] = json.loads((MODEL_DIR / "router_meta.json").read_text(encoding="utf-8"))
    await asyncio.to_thread(_classify, Image.new("RGB", (64, 64)))  # warm
    yield


app = FastAPI(title="Lanka Link image", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok" if "sess" in state else "loading"}


def _classify(img: Image.Image) -> list[tuple[str, float]]:
    meta = state["meta"]
    size = meta["img_size"]
    x = np.asarray(img.convert("RGB").resize((size, size), Image.BILINEAR), dtype=np.float32) / 255.0
    x = (x - np.array(meta["mean"], dtype=np.float32)) / np.array(meta["std"], dtype=np.float32)
    logits = state["sess"].run(None, {"input": x.transpose(2, 0, 1)[None]})[0][0]
    p = np.exp(logits - logits.max())
    p /= p.sum()
    top = np.argsort(-p)[:3]
    return [(meta["classes"][i], float(p[i])) for i in top]


_vlm_calls: collections.deque[float] = collections.deque()


def _vlm_slot() -> bool:
    """True when one more call fits inside VLM_RPM for the last sixty seconds."""
    now = time.monotonic()
    while _vlm_calls and now - _vlm_calls[0] > 60:
        _vlm_calls.popleft()
    if len(_vlm_calls) >= VLM_RPM:
        return False
    _vlm_calls.append(now)
    return True


def _jpeg(img: Image.Image) -> str:
    small = img.convert("RGB")
    small.thumbnail((1024, 1024))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


async def describe(img: Image.Image) -> str | None:
    """What a vision language model sees in the photo, or None (no key, over the cap, failed)."""
    key = os.environ.get("GOOGLE_API_KEY")
    if not key or not _vlm_slot():
        return None
    body = {"model": VLM_MODEL, "temperature": 0.2, "max_tokens": 1024, "reasoning_effort": "low",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": VLM_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{await asyncio.to_thread(_jpeg, img)}"}},
            ]}]}
    try:
        r = await http.post(f"{VLM_URL}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"},
                            timeout=VLM_TIMEOUT_S)
        r.raise_for_status()
        text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
    return " ".join(text.split())[:400] or None


class In(BaseModel):
    attachment: dict[str, Any]


@app.post("/run")
async def run(body: In) -> dict[str, Any]:
    started = time.perf_counter()
    r = await http.get(f"{INQUIRY_URL}/internal/attachments/{body.attachment['id']}/bytes")
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    classes, leds = await asyncio.gather(asyncio.to_thread(_classify, img), asyncio.to_thread(lit_colours, img))
    label, conf = classes[0]
    lit = [led["colour"] for led in leds]
    summary = f"The photo shows the router's {PART.get(label, label.replace('-', ' ').replace('_', ' '))}."
    summary += f" Lit indicators: {', '.join(lit)}." if lit else " No lit indicators are visible."
    model, seen = "efficientnet-b0-router-onnx+hsv", None
    if conf < VLM_BELOW and (seen := await describe(img)):
        # Not one of the router parts it was trained on: the model's own words, not a wrong label.
        summary, model = f"Photo description: {seen}", f"{model}+vlm:{VLM_MODEL}"
    return {"summary": summary, "confidence": round(conf, 4), "classes": [{"label": c, "p": round(p, 4)} for c, p in classes],
            "leds": leds, "model": model, "vlm": bool(seen), "ms": int((time.perf_counter() - started) * 1000)}
