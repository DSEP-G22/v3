from app.lang.detect import detect, detect_script, script_ratios
from app.lang.langcodes import LanguageCode, Script


def test_native_sinhala():
    r = detect("මගේ අන්තර්ජාල සම්බන්ධතාවය වැඩ කරන්නේ නැහැ")
    assert r.language is LanguageCode.SI
    assert r.script is Script.SINHALA


def test_native_tamil():
    r = detect("எனது இணைய இணைப்பு வேலை செய்யவில்லை")
    assert r.language is LanguageCode.TA
    assert r.script is Script.TAMIL


def test_singlish():
    r = detect("mata router eka wada karanne naha, kohomada hadanne")
    assert r.language is LanguageCode.SI_LATN
    assert r.markers


def test_tanglish():
    r = detect("enakku internet romba slow ah irukku, enna panna vendum")
    assert r.language is LanguageCode.TA_LATN
    assert r.markers


def test_plain_english_not_flagged():
    r = detect("My internet connection has been very slow since yesterday morning")
    assert r.language is LanguageCode.EN


def test_empty():
    assert detect("   ").language is LanguageCode.UNKNOWN


def test_mixed_script_picks_native_block():
    r = detect("මගේ router eka broken")
    assert r.language is LanguageCode.SI


def test_script_ratios_sum_to_one():
    ratios = script_ratios("abc මම")
    assert abs(sum(ratios.values()) - 1.0) < 1e-9


def test_detect_script_latin():
    script, _ = detect_script("hello world")
    assert script is Script.LATIN
