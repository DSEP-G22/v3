"""Content-hash cache for labelling calls, modelled on `model testing/src/asr_cache.py`.

Labelling 3.5k tickets costs real money, so a crash, a rate limit or an interrupted run must
never pay for the same ticket twice. The key is a hash of everything that could change the
answer -- prompt version, model id, temperature, and the exact text the model saw -- so a
prompt edit correctly invalidates the old labels instead of silently reusing them.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

CACHE_VERSION = 1


class LabelCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._dirty = 0
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # A truncated cache from a killed run is worth re-earning, not worth crashing on.
                self._data = {}

    @staticmethod
    def key(*, model: str, temperature: float, prompt_version: int, payload: str) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "v": CACHE_VERSION,
                    "model": model,
                    "temperature": round(temperature, 3),
                    "prompt": prompt_version,
                    "payload": payload,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return digest[:32]

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict[str, Any], flush_every: int = 25) -> None:
        with self._lock:
            self._data[key] = value
            self._dirty += 1
            should_flush = self._dirty >= flush_every
        if should_flush:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename: an interrupted flush must not leave a corrupt cache behind.
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=0), encoding="utf-8"
            )
            temporary.replace(self.path)
            self._dirty = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
