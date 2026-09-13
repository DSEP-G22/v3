"""Shared paths, seeding and JSONL helpers for the extraction scripts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Iterator

TRIAGE_ROOT = Path(__file__).resolve().parents[1]     # <repo>/TriageModel
REPO_ROOT = TRIAGE_ROOT.parent                        # <repo>
DATA = REPO_ROOT / "data"
MODEL_TESTING = REPO_ROOT / "model testing"

BITEXT_CSV = (
    DATA
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)
ROUTER_DIR = DATA / "router detection.v38-data_video.coco"
CALLS_DIR = DATA / "archive" / "Call center data samples"
ASR_CACHE = MODEL_TESTING / "data_cache" / "asr_hypotheses.json"

OUT_DIR = TRIAGE_ROOT / "data"
UNLABELLED = OUT_DIR / "unlabelled.jsonl"
LABELLED = OUT_DIR / "labelled.jsonl"
GOLD = OUT_DIR / "gold.jsonl"

SEED = 42

# Both the schema and the MVP's rule-based signal extraction are reused rather than
# reimplemented: the corpus must be prefilled by exactly the code that runs in production.
#
# TriageModel goes first on purpose: `MVP/api` also holds a module named `schema` (the
# re-export shim), and importing that one instead of the real definition would produce two
# distinct class objects for the same model.
if str(TRIAGE_ROOT) in sys.path:
    sys.path.remove(str(TRIAGE_ROOT))
sys.path.insert(0, str(TRIAGE_ROOT))

_mvp_api = str(REPO_ROOT / "MVP" / "api")
if _mvp_api not in sys.path:
    sys.path.append(_mvp_api)


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)
