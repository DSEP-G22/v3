"""Feature construction shared by the trainer and the baselines.

The distilled model reads two things: a frozen MiniLM embedding of the fused text, and the
engineered `Signals` vector. `Signals.as_features()` owns the second half, so the parquet
columns the Spark job writes and the tensor the model trains on cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import _paths  # noqa: F401  (sets sys.path)

from schema import UnifiedTicket  # noqa: E402

MINILM = "sentence-transformers/all-MiniLM-L6-v2"


def load_tickets(path: Path) -> list[UnifiedTicket]:
    import json

    tickets: list[UnifiedTicket] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                tickets.append(UnifiedTicket.model_validate(json.loads(line)))
    return [t for t in tickets if t.triage is not None]


def texts(tickets: list[UnifiedTicket]) -> list[str]:
    """What the text encoders see. `fused_text`, so image evidence is included."""
    return [t.fused_text for t in tickets]


def signal_matrix(tickets: list[UnifiedTicket]) -> tuple[np.ndarray, list[str]]:
    rows = [t.signals.as_features() for t in tickets]
    names = list(rows[0]) if rows else []
    matrix = np.array([[row[name] for name in names] for row in rows], dtype=np.float32)
    return matrix, names


def targets(tickets: list[UnifiedTicket]) -> dict[str, np.ndarray]:
    return {
        "intent": np.array([t.triage.intent for t in tickets]),
        "department": np.array([t.triage.department.value for t in tickets]),
        "urgency": np.array([t.triage.urgency.value for t in tickets]),
        "priority_score": np.array([t.triage.priority_score for t in tickets], dtype=np.float32),
    }


def embed(texts_: list[str], batch_size: int = 256, cache: Path | None = None) -> np.ndarray:
    """Frozen MiniLM embeddings, normalised -- the same recipe as notebook 01.

    Embedding the corpus takes a minute or two on CPU and the trainer is re-run often, so the
    result is cached on disk keyed by the corpus size and a hash of the text.
    """
    import hashlib

    if cache is not None:
        digest = hashlib.sha256("\n".join(texts_).encode("utf-8")).hexdigest()[:16]
        cache_file = cache / f"minilm_{len(texts_)}_{digest}.npy"
        if cache_file.exists():
            return np.load(cache_file)

    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(MINILM)
    vectors = encoder.encode(
        texts_,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        np.save(cache_file, vectors)
    return vectors
