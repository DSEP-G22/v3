from app.lang.langcodes import LanguageCode
from app.lang.transliterate import transliterate


def _is_sinhala(s):
    return any(0x0D80 <= ord(c) <= 0x0DFF for c in s)


def _is_tamil(s):
    return any(0x0B80 <= ord(c) <= 0x0BFF for c in s)


def test_singlish_produces_sinhala_script():
    r = transliterate("mata prashnayak thiyenawa", LanguageCode.SI_LATN)
    assert _is_sinhala(r.native_text)
    assert r.target_language is LanguageCode.SI
    assert r.coverage > 0.9


def test_tanglish_produces_tamil_script():
    r = transliterate("enakku prachanai irukku", LanguageCode.TA_LATN)
    assert _is_tamil(r.native_text)
    assert r.target_language is LanguageCode.TA


def test_loanwords_pass_through():
    r = transliterate("mage router eka", LanguageCode.SI_LATN)
    assert "router" in r.native_text


def test_punctuation_and_digits_preserved():
    r = transliterate("mata 100 ekak denna!", LanguageCode.SI_LATN)
    assert "100" in r.native_text and r.native_text.endswith("!")


def test_non_romanized_is_noop():
    r = transliterate("plain english", LanguageCode.EN)
    assert r.native_text == "plain english"
    assert r.coverage == 0.0


def test_lexicon_fixes_vowel_length():
    # The rule engine alone yields නහ; the lexicon knows it is නැහැ.
    r = transliterate("naha", LanguageCode.SI_LATN)
    assert r.native_text == "නැහැ"


def test_lexicon_sentence_sinhala():
    r = transliterate("mata wada karanne naha", LanguageCode.SI_LATN)
    assert r.native_text == "මට වැඩ කරන්නේ නැහැ"


def test_lexicon_sentence_tamil():
    r = transliterate("enakku prachanai irukku", LanguageCode.TA_LATN)
    assert r.native_text == "எனக்கு பிரச்சனை இருக்கு"


def test_lexicon_loses_to_passthrough_words():
    r = transliterate("mata router eka", LanguageCode.SI_LATN)
    assert r.native_text == "මට router එක"


def test_code_switched_english_is_left_alone():
    """English words inside a Singlish sentence must not go through the engine.

    "light" used to come out as ලිඝ්ට් and "red" as රෙද්, neither of which is a word.
    MT then translated the non-words confidently, and the fault description in the
    ticket, which is usually carried by exactly these terms, was lost.
    """
    r = transliterate("mage router eka wada naha signal light red", LanguageCode.SI_LATN)
    assert "light" in r.native_text
    assert "red" in r.native_text
    assert "signal" in r.native_text
    assert _is_sinhala(r.native_text)


def test_english_text_reports_no_coverage():
    """Coverage has to be able to say "this was not romanized Sinhala at all".

    The old measure counted every character the rule engine consumed as covered, so a
    pure English sentence scored 1.00 and the caller's quality floor could never fire.
    """
    r = transliterate("my internet is not working since yesterday", LanguageCode.SI_LATN)
    assert r.coverage == 0.0


def test_coverage_reflects_words_the_lexicon_knew():
    known = transliterate("mata wada karanne naha", LanguageCode.SI_LATN)
    assert known.coverage == 1.0

    # A word the lexicon does not have is a guess, and says so rather than claiming
    # full coverage on rule output. "gedara" is ordinary Sinhala the lexicon simply
    # does not carry, so it goes through the rule engine and is not counted as known.
    guessed = transliterate("mata gedara", LanguageCode.SI_LATN)
    assert 0.0 < guessed.coverage < 1.0


def test_tamil_s_uses_the_native_letter_not_grantha():
    """Bare "s" is native /s/ and spells ச. ஸ is a Sanskrit loan letter.

    Emitting ஸ put an out of distribution glyph in front of MT on every "seiyanum",
    "sollunga" and "sari".
    """
    r = transliterate("seiyanum", LanguageCode.TA_LATN)
    assert "ஸ" not in r.native_text
    assert r.native_text.startswith("செ")


def test_tamil_ei_is_a_diphthong_not_two_vowels():
    """"ei" is how romanized Tamil writes ஐ. Left unmapped it stranded a vowel mid word."""
    r = transliterate("velai seiyala illa", LanguageCode.TA_LATN)
    assert r.native_text == "வேலை செய்யல இல்ல"
