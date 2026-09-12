"""MT backends. Ported from translation/translate.py; NLLB now runs on CTranslate2 int8.

Kept from the original: sentence-by-sentence translation (NLLB is sentence trained) and
placeholder protection so money, dates, speeds and reference codes survive byte-identical.
Changed: CT2 instead of torch (no torch at runtime), all sentences in one batched call,
beam 2 inbound for latency, a dummy translation at boot so the first customer is not the one
who pays for the model load.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Protocol

from app.lang.langcodes import FLORES_CODES, LanguageCode, base_language
from app.lang.schemas import TranslationResult

log = logging.getLogger(__name__)


class Translator(Protocol):
    name: str

    def translate(self, text: str, source_language: LanguageCode,
                  target_language: LanguageCode = LanguageCode.EN) -> TranslationResult: ...


class PassthroughTranslator:
    name = "passthrough"

    def translate(self, text, source_language, target_language=LanguageCode.EN):
        return TranslationResult(source_text=text, translated_text=text, source_language=source_language,
                                 target_language=target_language, backend=self.name)


_PROTECTED = re.compile(
    r"""(
        [A-Z]{2,}[-/][A-Z0-9-]+
      | https?://\S+ | \S+@\S+\.\S+
      | (?:LKR|Rs\.?|USD)\s?[\d,]+(?:\.\d+)?
      | \+?\d[\d\s()-]{6,}\d
      | \d+(?:[.,]\d+)*\s?(?:Mbps|Kbps|Gbps|GB|MB|TB|kWh|%)
      | \d{1,2}[:.]\d{2}\s?(?:am|pm|AM|PM)?
      | \d[\d,]*(?:\.\d+)?
    )""",
    re.VERBOSE,
)
_SENTENCE = re.compile(r"(?<=[.!?ඃ।])\s+")
_OPEN, _CLOSE = "‹", "›"


def _protect(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}

    def swap(m: re.Match) -> str:
        token = f"{_OPEN}{len(mapping)}{_CLOSE}"
        mapping[token] = m.group(0)
        return token

    return _PROTECTED.sub(swap, text), mapping


def _restore(text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        if token in text:
            text = text.replace(token, original)
            continue
        loose = re.compile(re.escape(token[0]) + r"\s*" + re.escape(token[1:-1]) + r"\s*" + re.escape(token[-1]))
        text = loose.sub(lambda _: original, text)
    return text


def split_sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE.split(text.strip()) if p.strip()]


class CT2NLLBTranslator:
    """NLLB-200 distilled 600M, converted to CTranslate2 int8 (int8_float16 on GPU)."""

    name = "nllb-ct2"

    def __init__(self, model_dir: str, device: str = "cpu", beams_in: int = 2, beams_out: int = 4) -> None:
        import ctranslate2
        from transformers import AutoTokenizer

        compute = "int8_float16" if device == "cuda" else "int8"
        threads = int(os.environ.get("OMP_NUM_THREADS", "4"))
        self._model = ctranslate2.Translator(model_dir, device=device, compute_type=compute,
                                             intra_threads=threads)
        self._tok = AutoTokenizer.from_pretrained(model_dir)
        self.beams_in, self.beams_out = beams_in, beams_out

    def translate(self, text, source_language, target_language=LanguageCode.EN):
        src = base_language(source_language)
        src_code, tgt_code = FLORES_CODES.get(src), FLORES_CODES.get(target_language)
        if not text.strip() or src_code is None or tgt_code is None or src == target_language:
            return TranslationResult(source_text=text, translated_text=text, source_language=source_language,
                                     target_language=target_language, backend=self.name)
        pieces = [_protect(p) for p in split_sentences(text)]
        self._tok.src_lang = src_code
        batch = [self._tok.convert_ids_to_tokens(self._tok.encode(masked)) for masked, _ in pieces]
        results = self._model.translate_batch(
            batch, target_prefix=[[tgt_code]] * len(batch),
            beam_size=self.beams_in if target_language == LanguageCode.EN else self.beams_out,
            max_decoding_length=256, no_repeat_ngram_size=4,
        )
        out = []
        for (_, mapping), r in zip(pieces, results):
            tokens = r.hypotheses[0][1:]  # drop the forced target-language token
            decoded = self._tok.decode(self._tok.convert_tokens_to_ids(tokens), skip_special_tokens=True)
            out.append(_restore(decoded.strip(), mapping))
        return TranslationResult(source_text=text, translated_text=" ".join(out).strip(),
                                 source_language=source_language, target_language=target_language, backend=self.name)


class GoogleTranslator:
    """Opt-in cloud backend (LANKA_TR_BACKEND=google). Text leaves the machine."""

    name = "google"

    def translate(self, text, source_language, target_language=LanguageCode.EN):
        from deep_translator import GoogleTranslator as G

        src = base_language(source_language)
        if not text.strip() or src == target_language:
            return TranslationResult(source_text=text, translated_text=text, source_language=source_language,
                                     target_language=target_language, backend=self.name)
        for attempt in range(4):
            try:
                out = G(source=src.value, target=target_language.value).translate(text)
                if out and out.strip():
                    return TranslationResult(source_text=text, translated_text=out.strip(),
                                             source_language=source_language, target_language=target_language,
                                             backend=self.name)
            except Exception:  # noqa: BLE001 - scraped endpoint, retry
                pass
            time.sleep(0.4 * (attempt + 1))
        raise RuntimeError("google translate returned nothing")


def build() -> Translator:
    backend = os.environ.get("LANKA_TR_BACKEND", "auto")
    model_dir = Path(os.environ.get("MODEL_DIR", "/models")) / "nllb-600m-ct2"
    if backend in ("auto", "nllb") and (model_dir / "model.bin").exists():
        return CT2NLLBTranslator(str(model_dir), device=os.environ.get("LANKA_TR_DEVICE", "cpu"))
    if backend == "google":
        return GoogleTranslator()
    log.warning("no NLLB model at %s and no backend chosen: translation is passthrough", model_dir)
    return PassthroughTranslator()
