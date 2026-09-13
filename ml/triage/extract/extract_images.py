"""A pool of `ImageEvidence` records from the router COCO corpus, keyed by dominant class.

The corpus is object-detection data, so each image carries several boxes. "Dominant class"
means the most frequent non-background label in the image, which is what `compose.py` keys
on when it decides which requests deserve which photograph.

Confidences here are box-count shares, not model outputs: these records stand in for what
the vision stage would have produced, and the labelling pass must not be told they came from
a classifier that never ran.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from common import ROUTER_DIR

from schema import ImageEvidence

BACKGROUND = "router-detection"     # the COCO supercategory row, not a real component
SPLITS = ("test", "valid", "train")

# Components whose presence implies a fault indicator worth surfacing on the ticket.
FAULT_CLASSES = {"power", "power-conn", "fiber-conn", "lans-conn", "phone-conn"}


def _load_split(split: str) -> list[ImageEvidence]:
    annotations_path = ROUTER_DIR / split / "_annotations.coco.json"
    if not annotations_path.exists():
        return []

    data = json.loads(annotations_path.read_text(encoding="utf-8"))
    categories = {c["id"]: c["name"] for c in data["categories"]}
    per_image: dict[int, Counter] = {}
    for annotation in data["annotations"]:
        name = categories.get(annotation["category_id"], "")
        if not name or name == BACKGROUND:
            continue
        per_image.setdefault(annotation["image_id"], Counter())[name] += 1

    evidence: list[ImageEvidence] = []
    for image in data["images"]:
        counts = per_image.get(image["id"])
        if not counts:
            continue
        total = sum(counts.values())
        ordered = counts.most_common()
        evidence.append(
            ImageEvidence(
                attachment_id=f"{split}/{image['file_name']}",
                detected_classes=[name for name, _ in ordered],
                class_confidences={name: round(count / total, 4) for name, count in ordered},
                model_version=f"coco-annotations:{split}",
            )
        )
    return evidence


def extract(splits: tuple[str, ...] = SPLITS) -> dict[str, list[ImageEvidence]]:
    """Evidence records grouped by dominant class."""
    pool: dict[str, list[ImageEvidence]] = {}
    for split in splits:
        for evidence in _load_split(split):
            dominant = evidence.detected_classes[0]
            pool.setdefault(dominant, []).append(evidence)
    return pool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", nargs="*", default=list(SPLITS))
    args = parser.parse_args()

    pool = extract(tuple(args.splits))
    total = sum(len(items) for items in pool.values())
    print(f"image evidence records: {total} across {len(pool)} dominant classes")
    for name, items in sorted(pool.items(), key=lambda kv: -len(kv[1])):
        marker = " (fault indicator)" if name in FAULT_CLASSES else ""
        print(f"  {name:<14} {len(items):>4}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
