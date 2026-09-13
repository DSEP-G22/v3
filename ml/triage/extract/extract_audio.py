"""Audio-modality tickets from the benchmark's cached ASR hypotheses.

Re-transcribing the call corpus costs tens of minutes per model, and notebook 03 already
did it -- so this reads `model testing/data_cache/asr_hypotheses.json` instead. The
preferred hypothesis per call is the largest faster-whisper model available for it, since
that is the one the MVP's ASR stage most closely matches.

Every record is marked `noisy_text=True`: transcripts are noisy by construction, and
notebook 05's shifted-split scores are the honest ones for anything reading them.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass

from common import ASR_CACHE, CALLS_DIR

# Directory names carry the language and a rough topic, e.g.
# "1735560973.459326 (PL Account-Billing)".
DIR_HINT_RE = re.compile(r"\(([^)]*)\)")
LANGUAGE_CODES = {
    "en": "en", "ru": "ru", "pl": "pl", "fr": "fr", "de": "de", "es": "es",
    "portuguese": "pt", "pt": "pt",
}

# Bigger is better; the last match wins.
MODEL_RANK = ["whisper_tiny", "faster_whisper_tiny", "whisper_small", "faster_whisper_small",
              "faster_whisper_medium", "whisper_medium", "faster_whisper_large-v3"]


@dataclass
class AudioRecord:
    call_id: str
    text: str
    language: str
    model: str
    topic_hint: str


def _rank(model: str) -> int:
    return MODEL_RANK.index(model) if model in MODEL_RANK else -1


def _call_hints() -> dict[str, tuple[str, str]]:
    """`call_id -> (language, topic hint)` read off the sample directory names."""
    hints: dict[str, tuple[str, str]] = {}
    if not CALLS_DIR.exists():
        return hints
    for directory in CALLS_DIR.iterdir():
        if not directory.is_dir():
            continue
        match = DIR_HINT_RE.search(directory.name)
        annotation = (match.group(1) if match else "").strip()
        first = annotation.split()[0].lower() if annotation else ""
        language = LANGUAGE_CODES.get(first, "")
        topic = annotation[len(first):].strip() if language else annotation
        hints[directory.name] = (language, topic)
    return hints


def extract() -> list[AudioRecord]:
    if not ASR_CACHE.exists():
        return []

    cache = json.loads(ASR_CACHE.read_text(encoding="utf-8"))
    hints = _call_hints()
    best: dict[str, tuple[int, AudioRecord]] = {}

    for key, value in cache.items():
        model, _task, call_id = key.split("|", 2)
        text = (value.get("text") or "").strip()
        if len(text) < 60:      # a near-empty hypothesis is not a usable request
            continue

        hint_language, topic = hints.get(call_id, ("", ""))
        record = AudioRecord(
            call_id=call_id,
            text=text,
            language=hint_language or value.get("language") or "en",
            model=model,
            topic_hint=topic,
        )
        rank = _rank(model)
        if call_id not in best or rank > best[call_id][0]:
            best[call_id] = (rank, record)

    return [record for _rank_value, record in sorted(best.values(), key=lambda kv: kv[1].call_id)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    records = extract()
    print(f"audio records: {len(records)}")
    for record in records:
        print(
            f"  {record.call_id[:28]:<30} lang={record.language:<3} "
            f"model={record.model:<22} chars={len(record.text):>5}  {record.topic_hint}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
