"""Result types produced by the translation service.

Every ticket that enters the pipeline in Sinhala/Tamil (native or romanized)
leaves this layer as a `NormalizedText` whose `english_text` is what the
English-bodied `UnifiedTicketPayload` carries downstream. The original text
is preserved so agent-facing surfaces can reply in the customer's language.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .langcodes import LanguageCode, Script


class DetectionResult(BaseModel):
    language: LanguageCode
    script: Script
    confidence: float = Field(ge=0.0, le=1.0)
    #: Per-script share of the alphabetic characters, e.g. {"Sinh": 0.9, "Latn": 0.1}
    script_ratios: dict[str, float] = Field(default_factory=dict)
    #: Lexicon hits that drove a romanized-language call, for debugging.
    markers: list[str] = Field(default_factory=list)
    #: True when the message visibly mixes English with Sinhala/Tamil ,  the
    #: normal case for Sri Lankan support tickets, not an error.
    mixed: bool = False
    #: Share of word tokens that are not recognizable English (0-1). Drives the
    #: decision to translate a code-mixed message at all.
    non_english_share: float = 0.0


class TransliterationResult(BaseModel):
    source_text: str
    native_text: str
    source_language: LanguageCode
    target_language: LanguageCode
    #: Share of input tokens the rule engine could map (0-1). Low values mean
    #: the text was mostly English/loanwords and was passed through.
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)


class TranslationResult(BaseModel):
    source_text: str
    translated_text: str
    source_language: LanguageCode
    target_language: LanguageCode = LanguageCode.EN
    backend: str
    #: None when the backend cannot report a score (most seq2seq models).
    confidence: Optional[float] = None


class NormalizedText(BaseModel):
    """Canonical output of the text path: original preserved, English derived."""

    original_text: str
    detected_language: LanguageCode
    detected_script: Script
    detection_confidence: float = 0.0
    #: Sinhala/Tamil script form. Equals `original_text` for native-script
    #: input, is the transliterated form for Singlish/Tanglish, None for English.
    native_text: Optional[str] = None
    english_text: str
    translated: bool = False
    transliterated: bool = False
    #: True when English and Sinhala/Tamil were mixed in one message.
    mixed: bool = False
    backend: Optional[str] = None


class NormalizedAudio(BaseModel):
    """Canonical output of the audio path."""

    audio_path: str
    transcript_text: str
    detected_language: LanguageCode
    english_text: str
    translated: bool = False
    duration_sec: Optional[float] = None
    asr_confidence: Optional[float] = None
    asr_model: Optional[str] = None
    backend: Optional[str] = None

    #: Set when Whisper's own decoder statistics say the audio was poor. The
    #: transcript is still returned ,  it is often partially right ,  but nothing
    #: downstream should treat it as reliable without saying so.
    noisy: bool = False
    #: 0 (clean) to 1 (unusable).
    noise_score: float = 0.0
    #: Human-readable justifications for the flag, for the agent console.
    noise_reasons: list[str] = Field(default_factory=list)
