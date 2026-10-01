"""detect -> (transliterate if romanized) -> translate. Ported from translation/service.py.

Same behaviour and API as the original TranslationService (its tests pass unchanged apart
from import paths), plus outbound translation for replies that keeps the sign-off intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.lang.detect import detect
from app.lang.langcodes import (
    SCRIPT_BY_LANGUAGE,
    LanguageCode,
    Script,
    base_language,
    is_romanized,
    needs_translation,
)
from app.lang.schemas import NormalizedText
from app.lang.transliterate import transliterate
from app.translate import Translator

#: The operator's name is never machine translated (it came back as a spoofed-looking sender).
SIGN_OFF = "Lanka Link customer support"
#: "1. ", "2) " or "- " opening a line of the reply.
_MARKER = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*])\s+")


@dataclass(frozen=True)
class Settings:
    min_romanized_score: float = 0.12
    min_transliteration_coverage: float = 0.35


class TranslationService:
    def __init__(self, translator: Translator, settings: Settings | None = None) -> None:
        self.translator = translator
        self.settings = settings or Settings()

    def normalize_text(self, text: str, declared_language: LanguageCode | None = None) -> NormalizedText:
        if not text or not text.strip():
            return NormalizedText(original_text=text or "", detected_language=LanguageCode.UNKNOWN,
                                  detected_script=Script.UNKNOWN, english_text=text or "")
        if declared_language and declared_language is not LanguageCode.UNKNOWN:
            language, script, confidence = declared_language, SCRIPT_BY_LANGUAGE[declared_language], 1.0
            mixed = detect(text).mixed
        else:
            r = detect(text, min_romanized_score=self.settings.min_romanized_score)
            language, script, confidence, mixed = r.language, r.script, r.confidence, r.mixed

        if not needs_translation(language):
            return NormalizedText(original_text=text, detected_language=language, detected_script=script,
                                  detection_confidence=confidence, english_text=text, mixed=mixed)

        native, transliterated = text, False
        if is_romanized(language):
            tr = transliterate(text, language)
            if tr.coverage < self.settings.min_transliteration_coverage:
                # A bad transliteration sent to MT is worse than the Latin text untouched.
                return NormalizedText(original_text=text, detected_language=language, detected_script=script,
                                      detection_confidence=confidence, english_text=text, mixed=mixed)
            native, transliterated = tr.native_text, True

        t = self.translator.translate(native, base_language(language))
        return NormalizedText(original_text=text, detected_language=language, detected_script=script,
                              detection_confidence=confidence, native_text=native, english_text=t.translated_text,
                              translated=t.translated_text != native, transliterated=transliterated,
                              mixed=mixed, backend=t.backend)

    def translate_outbound(self, text: str, target: LanguageCode) -> tuple[str, bool]:
        """English reply into si/ta. Returns (text, translated)."""
        if target not in (LanguageCode.SI, LanguageCode.TA) or not text.strip():
            return text, False
        body, sign = text, ""
        if text.rstrip().endswith(SIGN_OFF):
            body, sign = text.rstrip()[: -len(SIGN_OFF)].rstrip(), SIGN_OFF
        out = "\n".join(self._line(line, target) for line in body.split("\n"))
        return (f"{out}\n\n{sign}" if sign else out), out != body

    def _line(self, line: str, target: LanguageCode) -> str:
        """One line at a time, so paragraphs and numbered steps keep their breaks: the MT models
        split on any whitespace and join with spaces, which ran a whole reply into one block.
        A step or bullet marker stays as written in front of its translated text."""
        m = _MARKER.match(line)
        head, rest = (m.group(0), line[m.end():]) if m else ("", line)
        if not rest.strip():
            return line
        return head + self.translator.translate(rest.strip(), LanguageCode.EN, target).translated_text
