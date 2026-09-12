"""Canonical language/script codes shared by the translation service and the
ingestion pipeline's unified schema.

Stdlib-only on purpose: the unified schema imports this module, so it must
stay importable without pulling in torch/transformers.
"""

from __future__ import annotations

from enum import Enum


class LanguageCode(str, Enum):
    """BCP-47-flavoured codes for the languages the pipeline accepts.

    The ``*_LATN`` members cover romanized input ("Singlish" / "Tanglish"),
    which is native-language content typed in Latin script.
    """

    EN = "en"
    SI = "si"
    TA = "ta"
    SI_LATN = "si-Latn"   # Singlish
    TA_LATN = "ta-Latn"   # Tanglish
    UNKNOWN = "und"

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self]


class Script(str, Enum):
    LATIN = "Latn"
    SINHALA = "Sinh"
    TAMIL = "Taml"
    MIXED = "Mixed"
    UNKNOWN = "Zyyy"


_DISPLAY_NAMES = {
    LanguageCode.EN: "English",
    LanguageCode.SI: "Sinhala",
    LanguageCode.TA: "Tamil",
    LanguageCode.SI_LATN: "Singlish (romanized Sinhala)",
    LanguageCode.TA_LATN: "Tanglish (romanized Tamil)",
    LanguageCode.UNKNOWN: "Unknown",
}

#: Romanized variant -> the native-script language it represents.
ROMANIZED_TO_NATIVE = {
    LanguageCode.SI_LATN: LanguageCode.SI,
    LanguageCode.TA_LATN: LanguageCode.TA,
}

#: Native-script language -> the script its text is written in.
SCRIPT_BY_LANGUAGE = {
    LanguageCode.EN: Script.LATIN,
    LanguageCode.SI: Script.SINHALA,
    LanguageCode.TA: Script.TAMIL,
    LanguageCode.SI_LATN: Script.LATIN,
    LanguageCode.TA_LATN: Script.LATIN,
    LanguageCode.UNKNOWN: Script.UNKNOWN,
}

#: FLORES-200 codes, used by NLLB and most modern MT checkpoints.
FLORES_CODES = {
    LanguageCode.EN: "eng_Latn",
    LanguageCode.SI: "sin_Sinh",
    LanguageCode.TA: "tam_Taml",
}

#: Whisper / ASR language hints.
ASR_HINTS = {
    LanguageCode.EN: "en",
    LanguageCode.SI: "si",
    LanguageCode.TA: "ta",
    LanguageCode.SI_LATN: "si",
    LanguageCode.TA_LATN: "ta",
}

# Unicode blocks used for script detection.
SINHALA_RANGE = (0x0D80, 0x0DFF)
TAMIL_RANGE = (0x0B80, 0x0BFF)


def base_language(code: LanguageCode) -> LanguageCode:
    """Collapse a romanized code onto its native-script language.

    ``si-Latn -> si``; everything else is returned unchanged.
    """
    return ROMANIZED_TO_NATIVE.get(code, code)


def is_romanized(code: LanguageCode) -> bool:
    return code in ROMANIZED_TO_NATIVE


def needs_translation(code: LanguageCode) -> bool:
    """True when the text must be translated before it can enter the
    English-bodied unified payload."""
    return base_language(code) in (LanguageCode.SI, LanguageCode.TA)


def parse(value: str | None) -> LanguageCode:
    """Lenient parse of user/ASR-supplied language tags."""
    if not value:
        return LanguageCode.UNKNOWN
    normalized = value.strip().replace("_", "-").lower()
    aliases = {
        "en": LanguageCode.EN, "eng": LanguageCode.EN, "en-us": LanguageCode.EN,
        "en-gb": LanguageCode.EN, "english": LanguageCode.EN,
        "si": LanguageCode.SI, "sin": LanguageCode.SI, "si-lk": LanguageCode.SI,
        "sinhala": LanguageCode.SI, "sinhalese": LanguageCode.SI,
        "ta": LanguageCode.TA, "tam": LanguageCode.TA, "ta-lk": LanguageCode.TA,
        "ta-in": LanguageCode.TA, "tamil": LanguageCode.TA,
        "si-latn": LanguageCode.SI_LATN, "singlish": LanguageCode.SI_LATN,
        "ta-latn": LanguageCode.TA_LATN, "tanglish": LanguageCode.TA_LATN,
        "tamlish": LanguageCode.TA_LATN,
        "und": LanguageCode.UNKNOWN, "unknown": LanguageCode.UNKNOWN,
    }
    return aliases.get(normalized, LanguageCode.UNKNOWN)
