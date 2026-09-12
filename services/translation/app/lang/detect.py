"""Language + script detection for Sri Lankan customer-support text.

Two stages:

1. Script detection by Unicode block ratio ,  unambiguous for Sinhala/Tamil
   native script.
2. For Latin-script text, a lexicon + orthography scorer separates English
   from Singlish (romanized Sinhala) and Tanglish (romanized Tamil). No
   off-the-shelf detector handles those two, which is why this is hand-rolled.
"""

from __future__ import annotations

import re
from collections import Counter

from .langcodes import (
    SINHALA_RANGE,
    TAMIL_RANGE,
    LanguageCode,
    Script,
)
from .schemas import DetectionResult

_TOKEN_RE = re.compile(r"[a-z']+")

# Function words / high-frequency support-domain words. Chosen to be
# discriminative: words that also read as English were left out.
SINGLISH_MARKERS = {
    "mata", "mage", "man", "api", "ape", "oyaa", "oya", "obata", "eyaa",
    "eka", "ekak", "ekata", "eke", "ekk", "meka", "mehema", "ehema",
    "thiyenne", "thiyenava", "thiyenawa", "thiyena", "nathi", "naha", "nane",
    "wenne", "wenawa", "wela", "welaa", "karanna", "karanawa", "kara",
    "puluwan", "baha", "beha", "denna", "denawa", "gannna", "ganna",
    "gaththa", "hodai", "hodata", "hariyata", "hari", "monawada", "monawa",
    "kohomada", "kohomath", "koheda", "kawadada", "kiyanna", "kiyanawa",
    "balanna", "balala", "issella", "dan", "dhan", "adha", "ada", "heta",
    "iye", "kalin", "hinda", "nisa", "nisaa", "ekkala", "wage", "wagey",
    "tikak", "tika", "godak", "hungak", "aiyo", "ane", "bn", "yanne",
    "enne", "awilla", "gihin", "danne", "denne", "welawata", "sathiyak",
    "masaka", "mudal", "salli", "gewanna", "gewwa", "aduwak", "prashnayak",
    "prashne", "krama", "hadanna", "hadala", "nawaththanna", "vitharak",
}

TANGLISH_MARKERS = {
    "naan", "naa", "enakku", "ennoda", "en", "nee", "neenga", "ninga",
    "unga", "ungaloda", "avanga", "avan", "aval", "namma", "engaluku",
    "irukku", "iruku", "irukkum", "irundhu", "iruntha", "illa", "ille",
    "illai", "enna", "ennathu", "epdi", "eppadi", "epo", "eppo", "enga",
    "yaaru", "panna", "pannunga", "pannitu", "pannala", "pannuren",
    "vendum", "venum", "vennam", "mudiyala", "mudiyum", "mudiyathu",
    "sollunga", "solli", "sonna", "romba", "rombo", "konjam", "seri",
    "sari", "vanakkam", "kuduthu", "kudunga", "vanthu", "varala", "varum",
    "poitu", "poyiduchu", "aachu", "aagala", "nalla", "nallaa", "kaasu",
    "panam", "bill", "kattanum", "problem", "prachanai", "prachchanai",
    "velai", "seiyanum", "thevai", "thaan", "than", "dhan", "appuram",
    "innum", "ippo", "nethu", "naalaikku", "indha", "andha", "adhu", "idhu",
}

# Very common English words; used only to keep short English sentences from
# tipping into a romanized call on one coincidental token.
ENGLISH_MARKERS = {
    "the", "is", "are", "was", "were", "my", "your", "i", "we", "you",
    "and", "but", "not", "with", "for", "from", "have", "has", "cannot",
    "can", "will", "would", "please", "internet", "connection", "router",
    "bill", "payment", "account", "service", "issue", "problem", "help",
    "working", "slow", "down", "since", "yesterday", "today", "morning",
    "night", "call", "support", "number", "package", "data", "speed",
    "why", "how", "what", "when", "where", "who", "which", "this", "that",
    "there", "here", "it", "its", "me", "him", "her", "them", "us", "they",
    "he", "she", "do", "does", "did", "am", "be", "been", "being", "get",
    "got", "give", "make", "made", "need", "want", "know", "think", "say",
    "said", "see", "look", "come", "go", "going", "take", "put", "keep",
    "still", "again", "already", "only", "also", "very", "too", "much",
    "many", "some", "any", "all", "no", "yes", "ok", "okay", "please",
    "thanks", "thank", "sorry", "now", "then", "so", "but", "or", "if",
    "because", "of", "in", "on", "at", "to", "by", "as", "up", "out",
    "off", "over", "under", "after", "before", "every", "each", "more",
    "less", "high", "low", "fast", "slow", "bad", "good", "fine", "work",
    "works", "working", "fix", "fixed", "reset", "restart", "check",
    "charged", "charge", "money", "amount", "month", "week", "day", "days",
}

# Orthographic tells: sequences far more common in romanized Sinhala/Tamil
# than in English.
_SINGLISH_PATTERNS = (
    re.compile(r"\b\w*(nn|thth|ddh|ndh)\w*\b"),
    re.compile(r"\w+(wa|wak|nawa|nne|nna)\b"),
)
_TANGLISH_PATTERNS = (
    re.compile(r"\w+(kku|nga|nnu|thu|kkum)\b"),
    re.compile(r"\b\w*(zh|rr|tt)\w*\b"),
)


def _in_range(ch: str, rng: tuple[int, int]) -> bool:
    return rng[0] <= ord(ch) <= rng[1]


def script_ratios(text: str) -> dict[str, float]:
    """Share of alphabetic characters belonging to each script."""
    counts: Counter[str] = Counter()
    total = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total += 1
        if _in_range(ch, SINHALA_RANGE):
            counts[Script.SINHALA.value] += 1
        elif _in_range(ch, TAMIL_RANGE):
            counts[Script.TAMIL.value] += 1
        elif ch.isascii():
            counts[Script.LATIN.value] += 1
        else:
            counts[Script.UNKNOWN.value] += 1
    if not total:
        return {}
    return {k: v / total for k, v in counts.items()}


def detect_script(text: str) -> tuple[Script, dict[str, float]]:
    ratios = script_ratios(text)
    if not ratios:
        return Script.UNKNOWN, ratios
    dominant, share = max(ratios.items(), key=lambda kv: kv[1])
    if share < 0.6 and len(ratios) > 1:
        return Script.MIXED, ratios
    return Script(dominant), ratios


def english_share(text: str) -> float:
    """Share of word tokens that are recognizable English.

    Deliberately crude: `ENGLISH_MARKERS` is a function-word list, not a
    dictionary. It is enough to tell "why so high?" (English) from "wada
    karanne naha" (not), which is all the mixed-message logic needs.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t in ENGLISH_MARKERS) / len(tokens)


def is_english_word(token: str) -> bool:
    return token.lower() in ENGLISH_MARKERS


def _score_romanized(text: str) -> tuple[float, float, list[str], list[str]]:
    """Return (singlish_score, tanglish_score, si_hits, ta_hits)."""
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0.0, 0.0, [], []

    si_hits = [t for t in tokens if t in SINGLISH_MARKERS]
    ta_hits = [t for t in tokens if t in TANGLISH_MARKERS]
    en_hits = [t for t in tokens if t in ENGLISH_MARKERS]

    n = len(tokens)
    si = len(si_hits) / n
    ta = len(ta_hits) / n
    en = len(en_hits) / n

    lowered = text.lower()
    si += 0.08 * sum(1 for p in _SINGLISH_PATTERNS if p.search(lowered))
    ta += 0.08 * sum(1 for p in _TANGLISH_PATTERNS if p.search(lowered))

    # English evidence suppresses both romanized scores rather than competing
    # as a third class: code-mixed tickets are the norm here.
    si = max(0.0, si - 0.5 * en)
    ta = max(0.0, ta - 0.5 * en)
    return si, ta, si_hits, ta_hits


def detect(
    text: str,
    min_romanized_score: float = 0.12,
    native_script_floor: float = 0.10,
) -> DetectionResult:
    """Detect the language of `text`.

    Native Sinhala/Tamil script wins outright. Latin-script text is scored
    against the romanized lexicons; below `min_romanized_score` it is treated
    as English (the safe default ,  English needs no translation).

    `native_script_floor` is the share of Sinhala/Tamil characters at which
    code-mixed text is called native rather than Latin.
    """
    if not text or not text.strip():
        return DetectionResult(
            language=LanguageCode.UNKNOWN, script=Script.UNKNOWN, confidence=0.0
        )

    script, ratios = detect_script(text)

    latin_share = ratios.get(Script.LATIN.value, 0.0)
    non_en = 1.0 - english_share(text)

    if script is Script.SINHALA:
        return DetectionResult(
            language=LanguageCode.SI, script=script,
            confidence=ratios.get(Script.SINHALA.value, 1.0), script_ratios=ratios,
            mixed=latin_share > 0.05, non_english_share=non_en,
        )
    if script is Script.TAMIL:
        return DetectionResult(
            language=LanguageCode.TA, script=script,
            confidence=ratios.get(Script.TAMIL.value, 1.0), script_ratios=ratios,
            mixed=latin_share > 0.05, non_english_share=non_en,
        )
    # Code-mixed text (native script + English loanwords) is common here. Any
    # meaningful amount of native script decides the language, even when Latin
    # characters dominate the count.
    si_share = ratios.get(Script.SINHALA.value, 0.0)
    ta_share = ratios.get(Script.TAMIL.value, 0.0)
    if max(si_share, ta_share) >= native_script_floor:
        lang = LanguageCode.SI if si_share >= ta_share else LanguageCode.TA
        return DetectionResult(
            language=lang, script=Script.MIXED,
            confidence=max(si_share, ta_share), script_ratios=ratios,
            mixed=True, non_english_share=non_en,
        )

    si, ta, si_hits, ta_hits = _score_romanized(text)
    best = max(si, ta)
    if best >= min_romanized_score:
        mixed = english_share(text) > 0.15
        if si >= ta:
            return DetectionResult(
                language=LanguageCode.SI_LATN, script=Script.LATIN,
                confidence=min(1.0, si), script_ratios=ratios, markers=si_hits,
                mixed=mixed, non_english_share=non_en,
            )
        return DetectionResult(
            language=LanguageCode.TA_LATN, script=Script.LATIN,
            confidence=min(1.0, ta), script_ratios=ratios, markers=ta_hits,
            mixed=mixed, non_english_share=non_en,
        )

    return DetectionResult(
        language=LanguageCode.EN, script=Script.LATIN,
        confidence=1.0 - best, script_ratios=ratios,
        non_english_share=non_en,
    )
