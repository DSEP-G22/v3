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


_SENTENCE = re.compile(r"(?<=[.!?ඃ।])\s+")
_LKR = re.compile(r"\bLKR\s?(?=\d)")
_NUMBER = re.compile(r"\d[\d,.:]*\d|\d")


def _prepare(text: str) -> str:
    """NLLB keeps digits, ids, phone numbers and links as written, but reads "LKR" as dollars or
    lira. Written "Rs." it becomes the local රු. / ரூ. with the amount untouched. (Masking runs
    behind placeholders was worse: the model dropped the brackets and every number became 0.)"""
    return _LKR.sub("Rs. ", text)


def _numbers(text: str) -> list[str]:
    """Every number as bare digits, so 7:30 and 7.30 or 1,758.20 and 1758.20 compare equal."""
    return sorted(re.sub(r"\D", "", n) for n in _NUMBER.findall(text))


def numbers_kept(source: str, translated: str) -> bool:
    """True when the translation carries every number in the source, no more and no fewer."""
    return _numbers(source) == _numbers(translated)


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
        pieces = [_prepare(p) for p in split_sentences(text)]
        self._tok.src_lang = src_code
        batch = [self._tok.convert_ids_to_tokens(self._tok.encode(p)) for p in pieces]
        results = self._model.translate_batch(
            batch, target_prefix=[[tgt_code]] * len(batch),
            beam_size=self.beams_in if target_language == LanguageCode.EN else self.beams_out,
            max_decoding_length=256, no_repeat_ngram_size=4,
        )
        out = []
        for source, r in zip(pieces, results):
            tokens = r.hypotheses[0][1:]  # drop the forced target-language token
            decoded = self._tok.decode(self._tok.convert_tokens_to_ids(tokens), skip_special_tokens=True).strip()
            # A wrong amount or time is worse than an untranslated sentence: keep the source then.
            out.append(decoded if numbers_kept(source, decoded) else source)
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
