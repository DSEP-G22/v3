import struct

from app.text import normalise, pii_flags, script_language, small_talk, sniff, validate, wav_seconds


def wav(seconds: float, rate: int = 8000) -> bytes:
    n = int(seconds * rate) * 2
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", n) + b"\0" * n


def test_small_talk_never_opens_a_case():
    for t in ("hi", "Hello!", "ආයුබෝවන්", "வணக்கம்", "good morning"):
        assert small_talk(t) == "greeting", t
    for t in ("thanks", "Thank you so much", "ස්තූතියි", "நன்றி"):
        assert small_talk(t) == "thanks", t
    assert small_talk("hi my internet is down") is None
    assert small_talk("mata internet eka wada karanne naha") is None


def test_script_hint_and_pii():
    assert script_language("මගේ අන්තර්ජාලය") == "si"
    assert script_language("இணையம் இல்லை") == "ta"
    assert script_language("mata internet eka wada karanne naha") == "en"
    assert pii_flags("call me on 0771234567") == ["pii_detected"]
    assert pii_flags("router light is red") == []


def test_normalise_strips_quotes_and_banned_dashes():
    out = normalise("line down" + chr(0x2014) + "since noon\n> old quoted text")
    assert out == "line down, since noon"


def test_magic_bytes_decide_the_type():
    assert sniff(b"\x89PNG\r\n\x1a\n....") == ("image/png", "image")
    assert sniff(b"\x1aE\xdf\xa3....") == ("audio/webm", "audio")
    assert sniff(wav(1)) == ("audio/wav", "audio")
    assert sniff(b"%PDF-1.7") is None
    assert abs(wav_seconds(wav(2.5)) - 2.5) < 0.01


def test_validation_messages():
    assert validate("", []).code == "empty"
    assert validate("ok", []).code == "too_short"
    assert validate("", [("x.pdf", b"%PDF")]).code == "file_type"
    assert validate("", [("v.wav", wav(70))]).code == "voice_length"
    assert validate("no net", []) is None
    assert validate("", [("p.png", b"\x89PNG\r\n\x1a\n")]) is None
