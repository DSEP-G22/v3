"""Customer-side urgency band from XLNet-base fine-tuned on the TriageModel data, int8 ONNX.

Model testing notebook 08 (DSEP-G22/model-testing): gold macro-F1 0.789 against the distilled
head's 0.724, critical recall 19 of 20, about 80 ms a ticket on one CPU thread. It reads text
only, so the TriageModel still gives the score, intent and reasons: XLNet decides the band and
the level is clamped into it. Chosen by the llm_triage binding (impl "model", model_version
VERSION); it loads on first use, so it costs no RAM until picked.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.model import BAND_RANGE

VERSION = "xlnet-priority-int8"
DIR = Path(os.environ.get("XLNET_PRIORITY_DIR") or Path(__file__).resolve().parents[1] / "models" / "xlnet-priority")
_lock = threading.Lock()
_loaded: tuple[Any, Any, list[str]] | None = None


def _load() -> tuple[Any, Any, list[str]]:
    global _loaded
    with _lock:
        if _loaded is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            meta = json.loads((DIR / "labels.json").read_text(encoding="utf-8"))
            tok = Tokenizer.from_file(str(DIR / "tokenizer.json"))
            tok.no_padding()
            tok.enable_truncation(meta["max_len"])
            so = ort.SessionOptions()
            so.intra_op_num_threads = int(os.environ.get("OMP_NUM_THREADS", "1"))
            sess = ort.InferenceSession(str(DIR / "model.int8.onnx"), so, providers=["CPUExecutionProvider"])
            _loaded = (tok, sess, meta["labels"])
    return _loaded


def band(text: str) -> tuple[str, float]:
    tok, sess, labels = _load()
    e = tok.encode(text)
    z = sess.run(None, {"input_ids": np.array([e.ids], np.int64),
                        "attention_mask": np.array([e.attention_mask], np.int64)})[0][0]
    p = np.exp(z - z.max())
    p /= p.sum()
    return labels[int(p.argmax())], float(p.max())


def apply(reading: dict[str, Any], text: str) -> dict[str, Any]:
    """The TriageModel (or rules) reading with XLNet's band, its level moved into that band."""
    b, confidence = band(text)
    lo, hi = BAND_RANGE[b]
    return {**reading, "level": min(max(reading["level"], lo), hi), "band": b, "confidence": round(confidence, 3),
            "source": "model", "model_version": VERSION}
