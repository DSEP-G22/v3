import pytest

from app.lang.langcodes import LanguageCode
from app.lang.schemas import TranslationResult
from app.pipeline import Settings, TranslationService


class FakeTranslator:
    """Marks its output so tests can assert translation actually ran."""

    name = "fake"

    def translate(self, text, source_language, target_language=LanguageCode.EN):
        return TranslationResult(
            source_text=text,
            translated_text=f"EN[{source_language.value}]:{text}",
            source_language=source_language,
            target_language=target_language,
            backend=self.name,
        )


@pytest.fixture
def service():
    return TranslationService(translator=FakeTranslator(), settings=Settings())


def test_english_passes_through_untouched(service):
    out = service.normalize_text("My router is not working since yesterday")
    assert out.detected_language is LanguageCode.EN
    assert out.english_text == out.original_text
    assert out.translated is False


def test_native_sinhala_is_translated(service):
    out = service.normalize_text("මගේ සම්බන්ධතාවය නැහැ")
    assert out.detected_language is LanguageCode.SI
    assert out.translated is True
    assert out.english_text.startswith("EN[si]:")
    assert out.original_text == "මගේ සම්බන්ධතාවය නැහැ"


def test_singlish_is_transliterated_then_translated(service):
    out = service.normalize_text("mata prashnayak thiyenawa balanna")
    assert out.detected_language is LanguageCode.SI_LATN
    assert out.transliterated is True
    assert out.native_text and out.native_text != out.original_text
    assert out.english_text.startswith("EN[si]:")


def test_tanglish_is_transliterated_then_translated(service):
    out = service.normalize_text("enakku prachanai irukku sollunga")
    assert out.detected_language is LanguageCode.TA_LATN
    assert out.english_text.startswith("EN[ta]:")


def test_declared_language_overrides_detection(service):
    out = service.normalize_text("test message", declared_language=LanguageCode.SI)
    assert out.detected_language is LanguageCode.SI
    assert out.translated is True


def test_empty_text(service):
    out = service.normalize_text("")
    assert out.detected_language is LanguageCode.UNKNOWN
    assert out.english_text == ""
