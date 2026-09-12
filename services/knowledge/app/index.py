"""Knowledge base: heading-aware chunks, dense retrieval, and the fault graph.

Chunking is v1 knowledge_ingest/chunk.py (800 chars, 100 overlap, never split mid heading).
Embeddings are MiniLM-L6 via fastembed (ONNX, no torch); the hash embedder is v1's CI
stand-in. The corpus is config/knowledge/*.md plus the v1 graph seed, held in memory.
ponytail: in-memory NumPy index over ~40 chunks; move to pgvector (knowledge schema) when
documents become editable in /admin or the corpus outgrows RAM.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")
CHUNK_SIZE, CHUNK_OVERLAP, DIM = 800, 100, 384
_HEADING = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
_WORD = re.compile(r"[a-z][a-z\-]{3,}")


def chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    marks = list(_HEADING.finditer(text))
    sections = [text[: marks[0].start()]] if marks and marks[0].start() > 0 else []
    sections += [text[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
                 for i, m in enumerate(marks)] or [text]
    out: list[str] = []
    for s in (s.strip() for s in sections if s.strip()):
        if len(s) <= size:
            out.append(s)
            continue
        out += [s[i: i + size].strip() for i in range(0, len(s), max(size - overlap, 1)) if s[i: i + size].strip()]
    return out


class HashEmbedder:
    model = "hash-embedder-384"

    def embed(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, t in enumerate(texts):
            for tok in t.lower().split():
                d = hashlib.sha256(tok.encode()).digest()
                m[row, int.from_bytes(d[:4], "big") % DIM] += 1.0 if d[4] % 2 == 0 else -1.0
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(n == 0, 1, n)


class MiniLM:
    model = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._m = TextEmbedding(self.model, cache_dir=os.environ.get("MODEL_DIR", "/models"))

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self._m.embed(texts)), dtype=np.float32)


def embedder():
    try:
        return MiniLM() if os.environ.get("EMBEDDER", "minilm") == "minilm" else HashEmbedder()
    except Exception:  # noqa: BLE001 - no model available: degrade to the hash embedder
        return HashEmbedder()


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: str


class Index:
    def __init__(self, emb=None) -> None:
        self.emb = emb or HashEmbedder()
        self.chunks: list[Chunk] = []
        self.vectors = np.zeros((0, DIM), dtype=np.float32)

    def load(self, directory: Path = CONFIG_DIR / "knowledge") -> Index:
        for path in sorted(directory.glob("*.md")):
            for i, text in enumerate(chunks(path.read_text(encoding="utf-8"))):
                self.chunks.append(Chunk(f"{path.stem}#{i}", text, path.stem))
        if self.chunks:
            self.vectors = self.emb.embed([c.text for c in self.chunks])
        return self

    def search(self, query: str, k: int = 8) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q = self.emb.embed([query])[0]
        scores = self.vectors @ q
        top = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in top]


class Graph:
    """LedState -> Symptom -> Fault -> Procedure -> Document, Fault -> Action (v1 graph seed)."""

    def __init__(self, path: Path = CONFIG_DIR / "graph_seed.yaml") -> None:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"nodes": [], "edges": []}
        self.nodes = {n["id"]: n for n in doc["nodes"]}
        self.adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for e in doc["edges"]:
            self.adj[e["from"]].append((e["type"], e["to"]))

    def seeds(self, text: str) -> list[str]:
        """Nodes whose name or LED props appear in the text."""
        low = text.lower()
        hits = []
        for nid, n in self.nodes.items():
            props = n.get("props", {})
            if n["label"] == "LedState":
                if props.get("colour", "~") in low and props.get("position", "~") in low:
                    hits.append(nid)
            elif (name := str(props.get("name", "")).lower()) and name in low:
                hits.append(nid)
        return hits

    def expand(self, seeds: list[str], hops: int = 2) -> dict[str, list[str]]:
        seen, queue = set(seeds), deque((s, 0) for s in seeds)
        while queue:
            nid, depth = queue.popleft()
            if depth >= hops:
                continue
            for _, nxt in self.adj.get(nid, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        by_label: dict[str, list[str]] = defaultdict(list)
        for nid in seen:
            by_label[self.nodes[nid]["label"]].append(nid)
        return dict(by_label)


def seed_terms(text: str, max_terms: int = 12) -> list[str]:
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        if w not in out:
            out.append(w)
    return out[:max_terms]
