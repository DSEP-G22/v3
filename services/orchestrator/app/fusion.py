"""Fused text with exact-offset provenance. Ported from v1 libs/domain/policy/fusion.py.

The only place fused text is built. v3 fuses every customer message on the case (all
revisions), so a follow-up adds to the story instead of replacing it.
"""

from __future__ import annotations

from dataclasses import dataclass

SEPARATOR = "\n\n"


@dataclass(frozen=True)
class Part:
    modality: str  # text | audio | image
    source: str  # message id or attachment id
    text: str
    confidence: float = 1.0


def fuse(parts: list[Part]) -> tuple[str, list[dict]]:
    fragments, provenance, offset = [], [], 0
    for p in parts:
        body = p.text.strip()
        if not body:
            continue
        tag = {"text": "CUSTOMER_TEXT", "audio": f"AUDIO:{p.source}", "image": f"IMAGE:{p.source}"}[p.modality]
        fragment = f"[{tag}] {body}"
        fragments.append(fragment)
        provenance.append({"modality": p.modality, "source": p.source, "span": [offset, offset + len(fragment)],
                           "confidence": p.confidence})
        offset += len(fragment) + len(SEPARATOR)
    return SEPARATOR.join(fragments), provenance


if __name__ == "__main__":
    text, prov = fuse([Part("text", "m1", "net down"), Part("audio", "a1", "  "), Part("image", "i1", "red light", 0.8)])
    assert text == "[CUSTOMER_TEXT] net down\n\n[IMAGE:i1] red light"
    for p in prov:
        start, end = p["span"]
        assert text[start:end].startswith("[")
    print("fusion ok")
