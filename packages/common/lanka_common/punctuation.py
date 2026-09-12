"""Plain-text punctuation scrub applied to everything a model writes.

Ported from v2 cst2/text/punctuation.py. JSON safe and idempotent; the table is built from
codepoints so this file passes scripts/check_no_em_dashes.py.
"""

from __future__ import annotations

from typing import Any

_TABLE: tuple[tuple[int, str], ...] = (
    (0x2014, ", "),  # em dash
    (0x2013, "-"),  # en dash
    (0x2015, ", "),  # horizontal bar
    (0x2012, "-"),
    (0x2011, "-"),
    (0x2212, "-"),
    (0x2018, "'"),
    (0x2019, "'"),
    (0x201A, "'"),
    (0x201C, '"'),
    (0x201D, '"'),
    (0x201E, '"'),
    (0x2026, "..."),
    (0x00A0, " "),
    (0x2007, " "),
    (0x202F, " "),
    (0x2022, "- "),
)

SUBSTITUTIONS: dict[str, str] = {chr(code): repl for code, repl in _TABLE}
BANNED_DASHES: frozenset[str] = frozenset({chr(0x2014), chr(0x2013), chr(0x2015)})


def normalise(text: str) -> str:
    for source, replacement in SUBSTITUTIONS.items():
        if source in text:
            text = text.replace(source, replacement)
    return text


def contains_banned_dash(text: str) -> bool:
    return any(dash in text for dash in BANNED_DASHES)


def normalise_deep(value: Any) -> Any:
    if isinstance(value, str):
        return normalise(value)
    if isinstance(value, dict):
        return {normalise_deep(k): normalise_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise_deep(v) for v in value]
    if isinstance(value, tuple):
        return tuple(normalise_deep(v) for v in value)
    return value
