"""Rule-based romanized -> native script transliteration.

Singlish and Tanglish are typed in Latin script with no fixed orthography,
so MT models trained on native script perform badly on them directly. This
module converts them to Sinhala/Tamil script first; translation then runs on
the native form.

The engine is a greedy longest-match abugida assembler: match a consonant
cluster, then a following vowel, and emit either the bare consonant (inherent
`a`), consonant + vowel sign, or consonant + virama when no vowel follows.
"""

from __future__ import annotations

import re

from .detect import ENGLISH_MARKERS
from .langcodes import LanguageCode
from .schemas import TransliterationResult

# --------------------------------------------------------------------------
# Sinhala
# --------------------------------------------------------------------------

SI_CONSONANTS = {
    "kh": "ඛ", "gh": "ඝ", "ng": "ං", "ngg": "ඟ",
    "chh": "ඡ", "ch": "ච", "jh": "ඣ", "ny": "ඤ",
    "gn": "ඥ",
    "thth": "ත්ත", "thh": "ද", "th": "ත",
    "dhh": "ධ", "dh": "ද", "nd": "ඳ", "mb": "ඹ",
    # Romanized Sinhala rarely marks the dental/retroflex split, so single
    # "d" takes the far more frequent dental ද; "dd"/"D" force retroflex ඩ.
    "dd": "ඩ", "D": "ඩ", "T": "ට", "tt": "ට්ට",
    "sh": "ශ", "shh": "ෂ", "ph": "ඵ", "bh": "බ",
    "k": "ක", "g": "ග", "j": "ජ", "t": "ට",
    "d": "ද", "n": "න", "p": "ප", "b": "බ",
    "m": "ම", "y": "ය", "r": "ර", "l": "ල",
    "L": "ළ", "w": "ව", "v": "ව", "s": "ස",
    "h": "හ", "f": "ෆ", "z": "ස", "c": "ක",
    "x": "ක්ස", "q": "ක",
}

SI_INDEPENDENT_VOWELS = {
    "aa": "ආ", "ae": "ඇ", "aae": "ඈ", "ii": "උ",
    "ee": "ඒ", "ea": "ඒ", "oo": "ඔ", "uu": "ඌ",
    "ai": "ඓ", "au": "ඕ", "a": "අ", "i": "ඉ",
    "u": "උ", "e": "එ", "o": "ඔ",
}

SI_VOWEL_SIGNS = {
    "aae": "ෑ", "aa": "ා", "ae": "ැ", "ii": "ී",
    "ee": "ේ", "ea": "ේ", "oo": "ො", "uu": "ූ",
    "ai": "ෛ", "au": "ෞ", "ru": "ෘ",
    "a": "", "i": "ි", "u": "ු", "e": "ෙ", "o": "ො",
}

SI_VIRAMA = "්"

# --------------------------------------------------------------------------
# Tamil
# --------------------------------------------------------------------------

TA_CONSONANTS = {
    "ng": "ங", "ny": "ஞ", "zh": "ழ", "sh": "ஷ",
    "ch": "ச", "th": "த", "nh": "ந",
    "kk": "க்க", "tt": "ட்ட",
    "pp": "ப்ப", "rr": "ற",
    # Romanized Tamil writes native /s/ as "s", and native Tamil spells it ச,
    # not the grantha ஸ. Grantha letters appear only in Sanskrit loanwords, so
    # mapping bare "s" to ஸ put an out-of-distribution glyph in front of MT on
    # every "seiyanum", "sollunga", "sari". Grantha stays reachable through the
    # explicit uppercase key.
    "k": "க", "g": "க", "s": "ச", "S": "ஸ", "j": "ஜ",
    "t": "ட", "d": "ட", "N": "ண", "n": "ன",
    "p": "ப", "b": "ப", "m": "ம", "y": "ய",
    "r": "ர", "l": "ல", "L": "ள", "v": "வ",
    "w": "வ", "h": "ஹ", "f": "ப", "c": "ச",
    "x": "க்ஸ", "z": "ழ", "q": "க",
}

TA_INDEPENDENT_VOWELS = {
    "aa": "ஆ", "ii": "ஈ", "ee": "ஏ", "oo": "ஓ",
    "uu": "ஊ", "ai": "ஐ", "ei": "ஐ", "ay": "ஐ", "au": "ஔ", "a": "அ",
    "i": "இ", "u": "உ", "e": "எ", "o": "ஒ",
}

TA_VOWEL_SIGNS = {
    "aa": "ா", "ii": "ீ", "ee": "ே", "oo": "ோ",
    # "ei" and "ay" are how romanized Tamil usually writes the ஐ diphthong
    # ("seiyanum", "kaiyil", "vayasu"). Without them the engine consumed the
    # consonant, failed to find a vowel sign, emitted a virama, and then
    # matched the stranded "e"/"i" as independent vowels mid-word, producing
    # forms like ஸெஇயல that no MT model has ever seen.
    "uu": "ூ", "ai": "ை", "ei": "ை", "ay": "ை", "au": "ௌ", "a": "",
    "i": "ி", "u": "ு", "e": "ெ", "o": "ொ",
}

TA_VIRAMA = "்"

# --------------------------------------------------------------------------
# Word lexicons
# --------------------------------------------------------------------------
# Romanization drops vowel length and gemination, so the rule engine cannot
# recover the correct spelling of common words ("naha" -> නහ, not නැහැ). These
# are the high-frequency function words and support-domain terms, spelled
# correctly; the engine only handles what falls through. Checked before the
# rule engine, matched case-insensitively on whole words.

SI_WORD_LEXICON = {
    "mata": "මට", "mage": "මගේ", "man": "මම", "mama": "මම",
    "api": "අපි", "ape": "අපේ", "oya": "ඔයා", "oyaa": "ඔයා",
    "obata": "ඔබට", "eyaa": "එයා",
    "eka": "එක", "ekak": "එකක්", "ekata": "එකට", "eke": "එකේ",
    "meka": "මේක", "mehema": "මෙහෙම", "ehema": "එහෙම",
    "thiyenawa": "තියෙනවා", "thiyenava": "තියෙනවා", "thiyenne": "තියෙන්නේ",
    "thiyena": "තියෙන", "nathi": "නැති", "naha": "නැහැ", "nane": "නැනේ",
    "wenne": "වෙන්නේ", "wenawa": "වෙනවා", "wela": "වෙලා", "welaa": "වෙලා",
    "karanna": "කරන්න", "karanawa": "කරනවා", "karanne": "කරන්නේ", "kara": "කර",
    "puluwan": "පුළුවන්", "baha": "බැහැ", "beha": "බැහැ",
    "denna": "දෙන්න", "denawa": "දෙනවා", "denne": "දෙන්නේ",
    "ganna": "ගන්න", "gaththa": "ගත්තා",
    "hodai": "හොඳයි", "hodata": "හොඳට", "hariyata": "හරියට", "hari": "හරි",
    "monawada": "මොනවද", "monawa": "මොනවා", "kohomada": "කොහොමද",
    "kohomath": "කොහොමත්", "koheda": "කොහෙද", "kawadada": "කවදාද",
    "kiyanna": "කියන්න", "kiyanawa": "කියනවා",
    "balanna": "බලන්න", "balala": "බලලා", "issella": "ඉස්සෙල්ලා",
    "dan": "දැන්", "dhan": "දැන්", "ada": "අද", "adha": "අද",
    "heta": "හෙට", "iye": "ඊයේ", "kalin": "කලින්",
    "hinda": "හින්දා", "nisa": "නිසා", "nisaa": "නිසා",
    "wage": "වගේ", "wagey": "වගේ", "tikak": "ටිකක්", "tika": "ටික",
    "godak": "ගොඩක්", "hungak": "හුඟාක්", "aiyo": "අයියෝ", "ane": "අනේ",
    "yanne": "යන්නේ", "enne": "එන්නේ", "awilla": "ඇවිල්ලා", "gihin": "ගිහින්",
    "danne": "දන්නේ", "welawata": "වෙලාවට", "sathiyak": "සතියක්",
    "masaka": "මාසක", "mudal": "මුදල්", "salli": "සල්ලි",
    "gewanna": "ගෙවන්න", "gewwa": "ගෙව්වා", "aduwak": "අඩුවක්",
    "prashnayak": "ප්‍රශ්නයක්", "prashne": "ප්‍රශ්නේ", "prashnaya": "ප්‍රශ්නය",
    "hadanna": "හදන්න", "hadala": "හදලා", "nawaththanna": "නවත්තන්න",
    "vitharak": "විතරක්", "witharak": "විතරක්",
    "wada": "වැඩ", "wadak": "වැඩක්", "wadha": "වැඩ",
    "hema": "හැම", "hemadama": "හැමදාම", "dawasa": "දවස", "dawase": "දවසේ",
    "raa": "රෑ", "hawasa": "හවස", "udaya": "උදය", "sambandaya": "සම්බන්ධය",
    "hemadaama": "හැමදාම",
    # Support-domain vocabulary. Each of these was previously guessed by the
    # rule engine and came out wrong in a way that changed the meaning of the
    # ticket: "wadi" (more) became වදි, which is not a word, and a complaint
    # about a bill being higher read as noise.
    "wadi": "වැඩි", "adu": "අඩු", "wediyen": "වැඩියෙන්",
    "aduwen": "අඩුවෙන්", "wadiyata": "වැඩියට",
    "namuth": "නමුත්", "eth": "එත්", "hebeth": "හැබැයි",
    "kiyala": "කියලා", "kiyanne": "කියන්නේ", "kiyawanna": "කියවන්න",
    "labenne": "ලැබෙන්නේ", "labuna": "ලැබුණා", "labena": "ලැබෙන",
    "yawanna": "යවන්න", "yawala": "යවලා", "ewanna": "එවන්න",
    "enna": "එන්න", "awa": "ආවා", "aawa": "ආවා", "giya": "ගියා",
    "innawa": "ඉන්නවා", "hitiya": "හිටියා", "una": "උණා", "unaa": "උණා",
    "sthuthi": "ස්තූතියි", "sthuthiyi": "ස්තූතියි", "karunakara": "කරුණාකර",
    "karunakarala": "කරුණාකරලා", "samawenna": "සමාවෙන්න",
    "awashya": "අවශ්‍ය", "awashyai": "අවශ්‍යයි", "one": "ඕන", "oni": "ඕනි",
    "epa": "එපා", "puluwanda": "පුළුවන්ද", "puluwanam": "පුළුවන් නම්",
    "hoyanna": "හොයන්න", "hoyala": "හොයලා",
    "hariyanne": "හරියන්නේ", "waradi": "වැරදි",
    "waradak": "වැරැද්දක්", "prashna": "ප්‍රශ්න",
    "aanduwa": "ආණ්ඩුව", "sewaya": "සේවය", "sewawa": "සේවාව",
    "gaana": "ගාන", "ganan": "ගණන්", "gaanak": "ගාණක්",
    "masika": "මාසික", "masaya": "මාසය", "masee": "මාසේ",
    "wesa": "වැස", "wahinawa": "වහිනවා", "kandulu": "කඳුළු",
    "hondin": "හොඳින්", "nathnam": "නැත්නම්", "nathuwa": "නැතුව",
    "thawa": "තව", "thawama": "තාමා", "thama": "තාම",
    "ikmanata": "ඉක්මනට", "ikman": "ඉක්මන්", "parakku": "පරක්කු",
    "dawasak": "දවසක්", "dawaswal": "දවස්වල", "wathawak": "වතාවක්",
    "sathiya": "සතිය", "mase": "මාසේ", "awuruddak": "අවුරුද්දක්",
    "welawe": "වෙලාවේ", "welawak": "වෙලාවක්", "welawa": "වෙලාව",
    "nawathila": "නැවතිලා", "nawathuna": "නැවතුණා", "aayeth": "ආයෙත්",
    "aye": "ආයේ", "aayemath": "ආයෙමත්", "harima": "හරිම",
    "hodama": "හොඳම", "narakai": "නරකයි",
    "narak": "නරක", "amaru": "අමාරු", "amarui": "අමාරුයි",
    "leasi": "ලේසි", "wenas": "වෙනස්", "wenasak": "වෙනසක්",
}

TA_WORD_LEXICON = {
    "naan": "நான்", "naa": "நா", "enakku": "எனக்கு", "ennoda": "என்னோட",
    "nee": "நீ", "neenga": "நீங்க", "ninga": "நீங்க", "unga": "உங்க",
    "ungaloda": "உங்களோட", "avanga": "அவங்க", "avan": "அவன்", "aval": "அவள்",
    "namma": "நம்ம", "engaluku": "எங்களுக்கு",
    "irukku": "இருக்கு", "iruku": "இருக்கு", "irukkum": "இருக்கும்",
    "irundhu": "இருந்து", "iruntha": "இருந்த",
    "illa": "இல்ல", "ille": "இல்ல", "illai": "இல்லை", "illama": "இல்லாம",
    "enna": "என்ன", "ennathu": "என்னது", "epdi": "எப்படி", "eppadi": "எப்படி",
    "eppo": "எப்போ", "epo": "எப்போ", "enga": "எங்க", "yaaru": "யாரு",
    "panna": "பண்ண", "pannunga": "பண்ணுங்க", "pannitu": "பண்ணிட்டு",
    "pannala": "பண்ணல", "pannuren": "பண்ணுறேன்",
    "vendum": "வேண்டும்", "venum": "வேணும்", "vennam": "வேண்டாம்",
    "mudiyala": "முடியல", "mudiyum": "முடியும்", "mudiyathu": "முடியாது",
    "sollunga": "சொல்லுங்க", "solli": "சொல்லி", "sonna": "சொன்ன",
    "romba": "ரொம்ப", "konjam": "கொஞ்சம்", "seri": "சரி", "sari": "சரி",
    "vanakkam": "வணக்கம்", "kuduthu": "குடுத்து", "kudunga": "குடுங்க",
    "vanthu": "வந்து", "varala": "வரல", "varum": "வரும்",
    "poitu": "போயிட்டு", "poyiduchu": "போயிடுச்சு", "aachu": "ஆச்சு",
    "aagala": "ஆகல", "nalla": "நல்ல", "nallaa": "நல்லா",
    "kaasu": "காசு", "panam": "பணம்", "kattanum": "கட்டணும்",
    "prachanai": "பிரச்சனை", "prachchanai": "பிரச்சனை", "prachinai": "பிரச்சனை",
    "velai": "வேலை", "seiyanum": "செய்யணும்", "thevai": "தேவை",
    "thaan": "தான்", "than": "தான்", "dhan": "தான்",
    "appuram": "அப்புறம்", "innum": "இன்னும்", "ippo": "இப்போ",
    "nethu": "நேத்து", "naalaikku": "நாளைக்கு",
    "indha": "இந்த", "andha": "அந்த", "adhu": "அது", "idhu": "இது",
    "ethu": "எது",
    # Support-domain vocabulary, same reasoning as the Sinhala block: these
    # were rule-engine guesses that came out as non-words.
    "seiyala": "செய்யல",
    "seiyuran": "செய்யுறேன்", "seithu": "செய்து",
    "vellai": "வேலை",
    "kedachu": "கெடச்சு", "kedaikala": "கிடைக்கல", "kidaikala": "கிடைக்கல",
    "anuppunga": "அனுப்புங்க", "anupunga": "அனுப்புங்க",
    "sollanum": "சொல்லணும்", "kekanum": "கேக்கணும்", "kettu": "கேட்டு",
    "paarunga": "பாருங்க", "paathu": "பாத்து", "paakanum": "பாக்கணும்",
    "theriyala": "தெரியல", "theriyum": "தெரியும்", "puriyala": "புரியல",
    "naal": "நாள்", "naalu": "நாலு",
    "maasam": "மாசம்", "maasa": "மாச", "varusham": "வருஷம்",
    "neram": "நேரம்", "neramum": "நேரமும்", "ippothu": "இப்போது",
    "sikkiram": "சீக்கிரம்", "seekiram": "சீக்கிரம்", "nirutthi": "நிறுத்தி", "nikkuthu": "நிக்குது", "odanjhu": "ஒடஞ்சு",
    "modham": "மோதம்", "kastam": "கஷ்டம்", "nandri": "நன்றி", "mannikanum": "மன்னிக்கணும்",
    "thayavu": "தயவு", "thayavuseidhu": "தயவுசெய்து",
    "kammi": "கம்மி", "adhigam": "அதிகம்", "jaasthi": "ஜாஸ்தி",
    "sondha": "சொந்த", "veedu": "வீடு", "veetla": "வீட்ல",
    "ungaluku": "உங்களுக்கு",
}

_WORD_RE = re.compile(r"[A-Za-z]+|[^A-Za-z]+")


def _sorted_keys(table: dict[str, str]) -> list[str]:
    """Longest-first so greedy matching prefers 'thth' over 'th' over 't'."""
    return sorted(table, key=len, reverse=True)


def _match(word: str, pos: int, keys: list[str], table: dict[str, str]):
    """Greedy longest-match at `pos`.

    Exact (case-sensitive) matches are tried first so the uppercase keys , 
    which encode the retroflex/dental distinctions romanization drops, e.g.
    `D` -> ඩ vs `d` -> ද ,  win over their lowercase counterparts.
    """
    for key in keys:
        if word.startswith(key, pos):
            return key, table[key]
    lowered = word.lower()
    for key in keys:
        if key.islower() and lowered.startswith(key, pos):
            return key, table[key]
    return None, None


class _Engine:
    def __init__(self, consonants, ind_vowels, vowel_signs, virama):
        self.consonants = consonants
        self.ind_vowels = ind_vowels
        self.vowel_signs = vowel_signs
        self.virama = virama
        self._ck = _sorted_keys(consonants)
        self._ivk = _sorted_keys(ind_vowels)
        self._vsk = _sorted_keys(vowel_signs)

    def word(self, w: str) -> tuple[str, int, int]:
        """Transliterate one Latin word. Returns (native, mapped, total)."""
        out: list[str] = []
        i = 0
        mapped = 0
        while i < len(w):
            key, glyph = _match(w, i, self._ck, self.consonants)
            if key:
                i += len(key)
                mapped += len(key)
                vkey, sign = _match(w, i, self._vsk, self.vowel_signs)
                if vkey:
                    i += len(vkey)
                    mapped += len(vkey)
                    out.append(glyph + sign)
                else:
                    out.append(glyph + self.virama)
                continue

            key, glyph = _match(w, i, self._ivk, self.ind_vowels)
            if key:
                i += len(key)
                mapped += len(key)
                out.append(glyph)
                continue

            out.append(w[i])
            i += 1
        return "".join(out), mapped, len(w)


_SI_ENGINE = _Engine(SI_CONSONANTS, SI_INDEPENDENT_VOWELS, SI_VOWEL_SIGNS, SI_VIRAMA)
_TA_ENGINE = _Engine(TA_CONSONANTS, TA_INDEPENDENT_VOWELS, TA_VOWEL_SIGNS, TA_VIRAMA)

_ENGINE_BY_LANGUAGE = {
    LanguageCode.SI_LATN: (_SI_ENGINE, LanguageCode.SI, SI_WORD_LEXICON),
    LanguageCode.TA_LATN: (_TA_ENGINE, LanguageCode.TA, TA_WORD_LEXICON),
}

#: Words left in Latin script: domain loanwords Sri Lankan customers type in
#: English even mid-sentence. Transliterating them hurts MT quality.
PASSTHROUGH_WORDS = {
    "router", "wifi", "wi", "fi", "modem", "internet", "data", "sim",
    "bill", "package", "reload", "app", "sms", "otp", "id", "nic",
    "email", "mbps", "gb", "mb", "kbps", "4g", "5g", "adsl", "fiber",
    "fibre", "dialog", "mobitel", "slt", "hutch", "airtel", "ok", "okay",
    # Code-switched English that customers type constantly in support tickets.
    # These used to fall through to the abugida engine, which happily rendered
    # "light" as ලිඝ්ට් and "red" as රෙද්: not words in any language, and
    # exactly the kind of confident nonsense MT then translates as if it were
    # Sinhala. Every one of these is a term that carries the fault description.
    "light", "lights", "led", "signal", "red", "green", "blue", "orange",
    "yellow", "white", "blinking", "flashing", "solid", "power", "cable",
    "port", "line", "speed", "slow", "down", "up", "network", "connection",
    "connect", "connected", "disconnect", "disconnected", "restart", "reset",
    "password", "username", "account", "payment", "pay", "paid", "due",
    "plan", "upgrade", "error", "code", "service", "support", "technician",
    "engineer", "visit", "no", "yes", "please", "problem", "issue",
    "fiber", "ont", "lan", "wan", "dns", "ip", "mac", "ssid", "5ghz", "2",
}

#: Letter sequences that occur in English but effectively never survive
#: romanized Sinhala or Tamil spelling. A word carrying one of these was typed
#: as English, whatever the sentence around it is, so it is left alone rather
#: than fed to the abugida engine.
_ENGLISH_ORTHOGRAPHY = re.compile(
    r"(tion|sion|ough|ight|ck|ph|qu|wh|sch|dge|tch|ea[rd]|oo[kd]|ing\b|ed\b|"
    r"ly\b|est\b|[bcdfghjklmnpqrstvwxz]{4})"
)


def _is_english_word(word: str) -> bool:
    """True when a Latin token should be left in Latin script.

    Deliberately conservative in one direction only. A false positive leaves an
    English word in an otherwise Sinhala sentence, which MT handles fine
    because code-switched English is what the customer wrote anyway. A false
    negative produces a non-word, which MT cannot recover from.
    """
    lowered = word.lower()
    if lowered in PASSTHROUGH_WORDS:
        return True
    # English function words ("why", "so", "much", "still"): short, no telltale
    # orthography, and common in code-switched tickets. Without this the engine
    # renders "why so high?" as "why සො හිඝ්", and MT is then translating a
    # sentence half of which is not a word.
    if lowered in ENGLISH_MARKERS:
        return True
    return bool(_ENGLISH_ORTHOGRAPHY.search(lowered))


def transliterate(text: str, source_language: LanguageCode) -> TransliterationResult:
    """Convert romanized Sinhala/Tamil to native script.

    Non-romanized inputs are returned unchanged with coverage 0.
    """
    entry = _ENGINE_BY_LANGUAGE.get(source_language)
    if entry is None:
        return TransliterationResult(
            source_text=text, native_text=text,
            source_language=source_language, target_language=source_language,
            coverage=0.0,
        )

    engine, target, lexicon = entry
    pieces: list[str] = []
    confident = considered = 0

    for chunk in _WORD_RE.findall(text):
        if not chunk[0].isalpha():
            pieces.append(chunk)
            continue
        if _is_english_word(chunk) or chunk.isupper():
            # Left in Latin on purpose, and not counted either way: an English
            # loanword is neither evidence that transliteration worked nor
            # evidence that it failed.
            pieces.append(chunk)
            continue
        lowered = chunk.lower()
        considered += 1
        if lowered in lexicon:
            pieces.append(lexicon[lowered])
            confident += 1
            continue
        pieces.append(engine.word(chunk)[0])

    # Coverage is the share of native words the lexicon knew, not the share of
    # characters the engine consumed. The old measure counted a rule-engine
    # guess as covered, so it returned 1.00 even for output that was not a word
    # in any language, and the caller's quality floor could never fire. Rule
    # output is a guess by construction: romanization drops vowel length and
    # gemination, so "wadi" is as likely to be වැඩි as වදි and only the lexicon
    # settles it.
    return TransliterationResult(
        source_text=text,
        native_text="".join(pieces),
        source_language=source_language,
        target_language=target,
        coverage=(confident / considered) if considered else 0.0,
    )
