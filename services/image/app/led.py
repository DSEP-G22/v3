"""Which indicator colours are lit in a router photo. HSV thresholds, no model.

v1's HeuristicLedExtractor zeroed the hue channel and so could only ever say "unknown";
this keeps the hue and buckets bright, saturated pixels by colour. LED meaning is not
decided here: grounding maps colour to meaning per device model.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Hue on PIL's 0-255 scale.
BUCKETS = (("red", 0, 10), ("amber", 11, 35), ("green", 45, 115), ("blue", 125, 185), ("red", 236, 255))
MIN_SHARE = 0.0008  # of all pixels: a lit LED is small but not a single speck


def lit_colours(img: Image.Image) -> list[dict]:
    hsv = np.asarray(img.convert("RGB").resize((320, 320)).convert("HSV"), dtype=np.int32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bright = (s > 140) & (v > 190)
    found: dict[str, float] = {}
    for name, lo, hi in BUCKETS:
        share = float(((h >= lo) & (h <= hi) & bright).mean())
        found[name] = found.get(name, 0.0) + share
    return [{"colour": c, "behaviour": "solid", "share": round(sh, 4)}
            for c, sh in sorted(found.items(), key=lambda kv: -kv[1]) if sh >= MIN_SHARE]


if __name__ == "__main__":
    canvas = Image.new("RGB", (320, 320), (30, 30, 30))
    canvas.paste((255, 20, 20), (100, 100, 112, 112))
    canvas.paste((20, 230, 40), (200, 100, 212, 112))
    colours = [c["colour"] for c in lit_colours(canvas)]
    assert set(colours) == {"red", "green"}, colours
    assert lit_colours(Image.new("RGB", (320, 320), (40, 40, 40))) == []
    print("led ok")
