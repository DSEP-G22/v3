"""Customer-side priority from the distilled TriageModel head.

Input: a frozen MiniLM embedding of the fused text (384) plus the 18 engineered Signals the
model was trained on (TriageModel/schema.py Signals.as_features). Output: urgency band, a
0..100 priority score and an intent. The weights are numpy (ml/export_triage.py), so the
service carries no torch. TRIAGE_LIVE_DIR, when it holds a model, wins over the baked copy:
the Airflow retrain DAG writes there and calls POST /reload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from app import rules

BAKED_DIR = Path(os.environ.get("TRIAGE_MODEL_DIR") or Path(__file__).resolve().parents[1] / "models")
LIVE_DIR = Path(os.environ.get("TRIAGE_LIVE_DIR", "/models-live"))
EMBED_CACHE = os.environ.get("MODEL_CACHE_DIR")
FILE = "triage_multitask"

#: Level ranges per band, identical to lanka_common.contracts.band_for, so a model band and
#: the one to ten level shown next to it can never disagree.
BAND_RANGE = {"low": (1, 3), "normal": (4, 6), "high": (7, 8), "critical": (9, 10)}

COLLOQUIAL = ("gonna", "wanna", "gotta", "yeah", "yep", "nope", "kinda", "dunno", "ain't", "lemme", "pls", "plz", "machan")
POLITE = ("please", "kindly", "thank you", "thanks", "appreciate", "would you", "could you", "sorry to bother")
OFFENSIVE = ("damn", "stupid", "idiot", "shit", "crap", "bloody", "fuck", "moron")
FAULT_LIGHTS = ("red light", "blinking red", "flashing red", "amber", "orange light", "no lights", "lights are off")

#: Why a signal lifted the score, for the console's "why this priority".
SIGNAL_WORDS = {
    "service_down": "They report that the service is not working.",
    "sentiment_score": "The message reads as upset.",
    "n_urgency_keywords": "They asked for this urgently.",
    "repeat_contact": "They say they have been in touch about this before.",
    "outage_local": "They describe a problem across their street or building.",
    "outage_regional": "They describe a problem across the wider area.",
    "device_visible": "They sent a photo of the equipment.",
    "n_fault_leds": "They describe a warning light on the equipment.",
    "n_error_codes": "They quote an error code.",
    "payment_related": "The request is about a payment or a bill.",
    "customer_segment_score": "The account is a business or premium one.",
}


def features(text: str, *, segment: str = "consumer", sla_age_score: float = 0.0,
             repeat_contact: bool = False) -> dict[str, float]:
    """The 18 Signals features, computed with the same lexicons triage routes on."""
    s = rules.extract_signals(text)
    low = text.lower()
    repeat = s.repeat_contact or repeat_contact
    return {
        "n_urgency_keywords": float(len(s.urgency_keywords)),
        "colloquial": float(any(t in low for t in COLLOQUIAL)),
        "noisy_text": float("[audio" in low),
        "offensive": float(any(t in low for t in OFFENSIVE)),
        "polite": float(any(t in low for t in POLITE)),
        "interrogative": float(s.interrogative),
        "sentiment_score": s.sentiment_score,
        "service_down": float(s.service_down),
        "payment_related": float(s.payment_related),
        "repeat_contact": float(repeat),
        "outage_local": float(s.outage_scope == "local"),
        "outage_regional": float(s.outage_scope == "regional"),
        "device_visible": float("[image" in low),
        "n_fault_leds": float(sum(t in low for t in FAULT_LIGHTS)),
        "n_error_codes": float(len(s.error_codes)),
        "customer_segment_score": rules.SEGMENT_SCORES.get(segment.lower(), 0.2),
        "prior_contacts_score": 1.0 if repeat else 0.0,
        "sla_age_score": max(0.0, min(1.0, sla_age_score)),
    }


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


class TriageModel:
    def __init__(self, directory: Path) -> None:
        meta = json.loads((directory / f"{FILE}.json").read_text(encoding="utf-8"))
        with np.load(directory / f"{FILE}.npz") as npz:
            self.w = {k: npz[k].astype(np.float32) for k in npz.files}
        self.labels: dict[str, list[str]] = meta["label_maps"]
        self.signal_names: list[str] = meta["signal_names"]
        self.embedding_model: str = meta["embedding_model"]
        self.version = f"{meta.get('source', FILE)}@{int((directory / f'{FILE}.npz').stat().st_mtime)}"
        self.directory = directory
        self._embedder: Any = None

    def embed(self, text: str) -> np.ndarray:
        if self._embedder is None:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(self.embedding_model, cache_dir=EMBED_CACHE)
        v = np.asarray(next(iter(self._embedder.embed([text]))), dtype=np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def predict(self, text: str, **context: Any) -> dict[str, Any]:
        feats = features(text, **context)
        x = np.concatenate([self.embed(text), np.array([feats[n] for n in self.signal_names], dtype=np.float32)])
        hidden = np.maximum(0.0, self.w["w1"] @ x + self.w["b1"])
        heads = {}
        for target, labels in self.labels.items():
            p = _softmax(self.w[f"w_{target}"] @ hidden + self.w[f"b_{target}"])
            i = int(p.argmax())
            heads[target] = (labels[i], float(p[i]))
        score = float(np.clip((self.w["ws"] @ hidden + self.w["bs"])[0] * 100, 0, 100))
        band, confidence = heads["urgency"]
        lo, hi = BAND_RANGE.get(band, (1, 10))
        level = min(max(round(score / 10), lo), hi)
        reasons = [{"signal": n, "move": 0, "detail": SIGNAL_WORDS[n]} for n in SIGNAL_WORDS
                   if feats.get(n, 0) > (0.25 if n in ("sentiment_score", "customer_segment_score") else 0)]
        return {"level": level, "band": band, "score": round(score), "confidence": round(confidence, 3),
                "intent": heads["intent"][0], "department_hint": heads["department"][0],
                "source": "model", "model_version": self.version, "reasons": reasons}


def load() -> TriageModel | None:
    for directory in (LIVE_DIR, BAKED_DIR):
        if (directory / f"{FILE}.npz").exists():
            try:
                return TriageModel(directory)
            except (OSError, KeyError, ValueError):
                continue
    return None
