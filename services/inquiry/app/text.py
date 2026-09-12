"""Pure text and file rules for chat intake. Ported from v1 text_svc, v1 intake_api/magic and
v2 intake/validation; no I/O here so every rule is testable on its own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from lanka_common.punctuation import normalise as scrub

MIN_TEXT = 3  # chat, not a form: "no net" is a real complaint
MAX_TEXT = 4000
MAX_FILES = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_VOICE_SECONDS = 60

_QUOTED = re.compile(r"(^On .+wrote:$)|(^-{2,}\s*Original Message\s*-{2,}$)|(^From:.+$)", re.I | re.M)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_NIC = re.compile(r"\b\d{9}[vVxX]\b|\b\d{12}\b")

_GREETING = re.compile(
    r"^(hi+|hello|hey|hai|good (morning|afternoon|evening)|ayubowan|vanakkam|"
    r"ආයුබෝවන්|හෙලෝ|வணக்கம்|ஹலோ)[\s!.,]*(there|lanka link)?[\s!.,]*$",
    re.I,
)
_THANKS = re.compile(
    r"^(thanks?( you)?( so much)?|thank u|thx|ty|ok thanks|stuti|isthuthi|nandri|"
    r"ස්තූතියි|බොහොම ස්තූතියි|நன்றி|மிக்க நன்றி)[\s!.,]*$",
    re.I,
)

TEMPLATES = {
    "greeting": {
        "en": "Hello! Tell us what is going on and we will take a look.",
        "si": "ආයුබෝවන්! ඔබට ඇති ගැටලුව අපට කියන්න, අපි බලන්නම්.",
        "ta": "வணக்கம்! உங்கள் பிரச்சினையைச் சொல்லுங்கள், நாங்கள் பார்க்கிறோம்.",
    },
    "thanks": {
        "en": "You are welcome. We are here if you need anything else.",
        "si": "ඔබව සාදරයෙන් පිළිගනිමු. තවත් යමක් අවශ්‍ය නම් අපි මෙහි සිටිමු.",
        "ta": "மகிழ்ச்சி. வேறு ஏதாவது தேவைப்பட்டால் நாங்கள் இங்கே இருக்கிறோம்.",
    },
}


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    if m := _QUOTED.search(t):
        t = t[: m.start()]
    t = "\n".join(line for line in t.splitlines() if not line.strip().startswith(">"))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return scrub(t.strip())


def script_language(text: str) -> str:
    """A hint only; the translation service does real detection (incl. Singlish/Tanglish)."""
    for ch in text:
        if 0x0D80 <= ord(ch) <= 0x0DFF:
            return "si"
        if 0x0B80 <= ord(ch) <= 0x0BFF:
            return "ta"
    return "en"


def pii_flags(text: str) -> list[str]:
    return ["pii_detected"] if any(p.search(text) for p in (_EMAIL, _PHONE, _CARD, _NIC)) else []


def small_talk(text: str) -> str | None:
    """'greeting' or 'thanks' when the whole message is just that; those never open a case."""
    t = text.strip()
    if _GREETING.match(t):
        return "greeting"
    if _THANKS.match(t):
        return "thanks"
    return None


_SIGNATURES: list[tuple[bytes, int, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", "image"),
    (b"\xff\xd8\xff", 0, "image/jpeg", "image"),
    (b"ID3", 0, "audio/mpeg", "audio"),
    (b"\xff\xfb", 0, "audio/mpeg", "audio"),
    (b"\xff\xf3", 0, "audio/mpeg", "audio"),
    (b"OggS", 0, "audio/ogg", "audio"),
    (b"\x1aE\xdf\xa3", 0, "audio/webm", "audio"),  # EBML: MediaRecorder's webm/opus
]


def sniff(data: bytes) -> tuple[str, str] | None:
    """(mime, kind) from magic bytes. The declared type and filename are never trusted."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav", "audio"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "image"
    if data[4:8] == b"ftyp":
        return "audio/mp4", "audio"  # Safari's MediaRecorder
    for sig, off, mime, kind in _SIGNATURES:
        if data[off : off + len(sig)] == sig:
            return mime, kind
    return None


def wav_seconds(data: bytes) -> float | None:
    """Duration of a PCM WAV from its header; other containers are checked by ASR."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    i = 12
    rate = channels = bits = None
    while i + 8 <= len(data):
        cid, size = data[i : i + 4], int.from_bytes(data[i + 4 : i + 8], "little")
        if cid == b"fmt ":
            channels = int.from_bytes(data[i + 10 : i + 12], "little")
            rate = int.from_bytes(data[i + 12 : i + 16], "little")
            bits = int.from_bytes(data[i + 22 : i + 24], "little")
        elif cid == b"data" and rate and channels and bits:
            return size / (rate * channels * bits / 8)
        i += 8 + size + (size & 1)
    return None


@dataclass
class Rejection:
    code: str
    message: str


def validate(text: str, files: list[tuple[str, bytes]]) -> Rejection | None:
    if len(files) > MAX_FILES:
        return Rejection("too_many_files", f"Attach at most {MAX_FILES} files at a time.")
    for name, data in files:
        if len(data) > MAX_FILE_BYTES:
            return Rejection("file_size", f"{name} is larger than 10 MB. Send a smaller version.")
        if sniff(data) is None:
            return Rejection("file_type", f"We cannot open {name}. Send a photo or a voice note instead.")
        secs = wav_seconds(data)
        if secs is not None and secs > MAX_VOICE_SECONDS + 1:
            return Rejection("voice_length", "Keep voice notes under a minute.")
    if not text and not files:
        return Rejection("empty", "Tell us what is happening, or attach a photo or a voice note.")
    if text and not files and len(text) < MIN_TEXT:
        return Rejection("too_short", "Add a little more detail. What is happening, and since when?")
    if len(text) > MAX_TEXT:
        return Rejection("too_long", f"Keep it under {MAX_TEXT} characters.")
    return None
