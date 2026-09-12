"""Image: router photos to a short visual summary. ONNX classifier + HSV LED colours.

The classifier (EfficientNet-B0, model testing notebook 02) says which router component the
photo shows; the LED pass says which indicator colours are lit. Grounding turns colour into
meaning using the customer's actual device model.
ponytail: the optional llava binding (4 s budget) is not wired; add it behind VISION_VLM_URL
if the classifier plus LED colours prove too coarse.
"""

from __future__ import annotations

import asyncio
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
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))

http = httpx.AsyncClient(timeout=10)
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
    summary = f"Photo of router equipment, most likely the {label.replace('_', ' ')}."
    summary += f" Lit indicators: {', '.join(lit)}." if lit else " No lit indicators are visible."
    return {"summary": summary, "confidence": round(conf, 4), "classes": [{"label": c, "p": round(p, 4)} for c, p in classes],
            "leds": leds, "model": "efficientnet-b0-router-onnx+hsv", "ms": int((time.perf_counter() - started) * 1000)}
