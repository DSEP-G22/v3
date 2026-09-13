"""Join the three corpora into `TriageModel/data/unlabelled.jsonl`.

Every record is a full `UnifiedTicket` with `triage=None` and `signals` rule-prefilled by
the *same* extraction code the MVP runs (`MVP/api/pipeline/signals.py`), so the corpus
cannot drift from production behaviour.

Image pairing is intent-aware and deterministic: device-related intents get router
photographs, billing and account intents get none. Anything the rules fill in is a hint for
the labelling pass, not an answer -- the LLM may override every field.

    python TriageModel/extract/compose.py            # -> data/unlabelled.jsonl
"""

from __future__ import annotations

import argparse
import random
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import extract_audio
import extract_images
import extract_synthetic
import extract_text
from common import SEED, UNLABELLED, write_jsonl

# The MVP's own stages, reused rather than reimplemented.
from pipeline import fuse as fuse_stage
from pipeline import signals as signals_stage
from schema import Channel, ImageEvidence, Modality, RequestBody, UnifiedTicket, validate_ticket

# Intents where a photograph of the hardware is plausible evidence. Everything else --
# billing, refunds, account management -- gets no image, because a customer asking about an
# invoice does not photograph their router.
DEVICE_INTENTS = {
    "contact_customer_service",
    "contact_human_agent",
    "complaint",
    "registration_problems",
    "recover_password",
    "switch_account",
    "edit_account",
    "create_account",
    "delivery_options",
}

# Dominant classes that read as a hardware fault, so those images go to the intents above.
FAULT_CLASSES = extract_images.FAULT_CLASSES

CHANNELS_TEXT = (Channel.web_portal, Channel.email, Channel.chat)


def _new_id(prefix: str, rng: random.Random) -> str:
    return f"{prefix}-{uuid.UUID(int=rng.getrandbits(128), version=4).hex[:10].upper()}"


def _pick_images(
    intent: str,
    pool: dict[str, list[ImageEvidence]],
    rng: random.Random,
    *,
    eligible: bool | None = None,
) -> list[ImageEvidence]:
    """0-2 plausible images. Device-ish intents get them; billing intents never do.

    `eligible` overrides the intent lookup, for records that carry no Bitext intent.
    """
    if eligible is None:
        eligible = intent in DEVICE_INTENTS
    if not eligible or not pool:
        return []

    # Two thirds of eligible tickets carry one image, a sixth carry two, the rest none --
    # attachments are the exception in a real queue, not the norm.
    draw = rng.random()
    count = 1 if draw < 0.55 else 2 if draw < 0.70 else 0
    if count == 0:
        return []

    # Prefer fault-indicating classes; they are rare, so fall back to the whole pool.
    fault_classes = [name for name in pool if name in FAULT_CLASSES]
    chosen: list[ImageEvidence] = []
    seen: set[str] = set()
    # A ticket may not carry the same photograph twice, and the fault-class pools are small
    # enough to collide, so draws are retried a bounded number of times.
    for index in range(count):
        for _attempt in range(8):
            classes = (
                fault_classes
                if (fault_classes and index == 0 and rng.random() < 0.6)
                else list(pool)
            )
            candidate = rng.choice(pool[rng.choice(sorted(classes))])
            if candidate.attachment_id not in seen:
                seen.add(candidate.attachment_id)
                chosen.append(candidate)
                break
    return chosen


def _build_ticket(
    *,
    ticket_id: str,
    text: str,
    modality: Modality,
    channel: Channel,
    language: str,
    images: list[ImageEvidence],
    created_at: datetime,
    bitext_flags: str | None,
    metadata: dict,
    rng: random.Random,
) -> UnifiedTicket:
    request = RequestBody(
        modality=modality,
        text=text,
        language=language,
        asr_model_version="faster_whisper_small (cached)" if modality is Modality.audio else None,
    )

    signals = signals_stage.extract(
        text,
        images,
        is_asr=modality is Modality.audio,
        bitext_flags=bitext_flags,
    )
    # Account context the text cannot know. Sampled, not invented per-record: the corpus
    # needs variation in these terms or the model never learns they matter.
    signals.customer_segment_score = round(rng.choice([0.0, 0.2, 0.2, 0.6, 0.7, 1.0]), 2)
    signals.sla_age_score = round(rng.choice([0.0, 0.0, 0.0, 0.3, 0.6, 1.0]), 2)
    if signals.repeat_contact:
        signals.prior_contacts_score = round(rng.uniform(0.5, 1.0), 2)

    fused_text, provenance = fuse_stage.fuse(request, images)

    ticket = UnifiedTicket(
        ticket_id=ticket_id,
        customer_id=_new_id("CUS", rng),
        channel=channel,
        created_at=created_at,
        request=request,
        images=images,
        signals=signals,
        triage=None,                    # the labelling pass fills this in
        fused_text=fused_text,
        provenance=provenance,
        metadata=metadata,
    )
    validate_ticket(ticket)
    return ticket


def compose(limit: int = 2800, seed: int = SEED, synthetic: int = 700) -> list[UnifiedTicket]:
    rng = random.Random(seed)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    image_pool = extract_images.extract()
    text_frame = extract_text.extract(limit=limit, seed=seed)
    audio_records = extract_audio.extract()

    tickets: list[UnifiedTicket] = []

    for position, row in enumerate(text_frame.itertuples(index=False)):
        intent = str(row.intent)
        tickets.append(
            _build_ticket(
                ticket_id=_new_id("TXT", rng),
                text=str(row.text),
                modality=Modality.text,
                channel=rng.choice(CHANNELS_TEXT),
                language="en",
                images=_pick_images(intent, image_pool, rng),
                created_at=now - timedelta(minutes=position),
                bitext_flags=str(row.flags) if row.flags else None,
                metadata={
                    "source": "bitext",
                    # Weak prior only. Deliberately NOT in `triage` -- the corpus has no
                    # triage labels, which is the entire reason for the labelling pass.
                    "bitext_intent": intent,
                    "bitext_category": str(row.category),
                    "bitext_flags": str(row.flags),
                    "raw_text": str(row.raw_text),
                },
                rng=rng,
            )
        )

    for position, record in enumerate(extract_synthetic.extract(synthetic, seed)):
        tickets.append(
            _build_ticket(
                ticket_id=_new_id("SYN", rng),
                text=record.text,
                modality=Modality.text,
                channel=rng.choice(CHANNELS_TEXT),
                language="en",
                images=_pick_images("", image_pool, rng, eligible=record.device_relevant),
                created_at=now - timedelta(minutes=position, seconds=30),
                bitext_flags=None,          # no Bitext ground truth: the rules fill the flags
                metadata={
                    "source": "synthetic_telecom",
                    "template_id": record.template_id,
                },
                rng=rng,
            )
        )

    for position, record in enumerate(audio_records):
        tickets.append(
            _build_ticket(
                ticket_id=_new_id("AUD", rng),
                text=record.text,
                modality=Modality.audio,
                channel=Channel.phone,
                language=record.language,
                images=[],              # a phone call carries no attachment
                created_at=now - timedelta(hours=position + 1),
                bitext_flags=None,
                metadata={
                    "source": "call_centre",
                    "call_id": record.call_id,
                    "asr_model": record.model,
                    "topic_hint": record.topic_hint,
                },
                rng=rng,
            )
        )

    rng.shuffle(tickets)
    return tickets


def summarise(tickets: list[UnifiedTicket]) -> None:
    modalities = Counter(t.request.modality.value for t in tickets)
    with_images = sum(1 for t in tickets if t.images)
    languages = Counter(t.request.language for t in tickets)
    intents = Counter(str(t.metadata.get("bitext_intent", ", ")) for t in tickets)

    sources = Counter(str(t.metadata.get("source", "?")) for t in tickets)
    print(f"records:        {len(tickets)}")
    print(f"sources:        {dict(sources)}")
    print(f"modalities:     {dict(modalities)}")
    print(f"with images:    {with_images}")
    print(f"languages:      {dict(languages)}")
    print(f"weak intents:   {len(intents)} distinct")
    print(f"service_down:   {sum(1 for t in tickets if t.signals.service_down)}")
    print(f"payment:        {sum(1 for t in tickets if t.signals.payment_related)}")
    print(f"urgency words:  {sum(1 for t in tickets if t.signals.urgency_keywords)}")
    print(f"noisy_text:     {sum(1 for t in tickets if t.signals.noisy_text)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=2800, help="Bitext records to sample")
    parser.add_argument("--synthetic", type=int, default=700, help="synthetic telecom records")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=str(UNLABELLED))
    args = parser.parse_args()

    tickets = compose(limit=args.limit, seed=args.seed, synthetic=args.synthetic)
    summarise(tickets)

    from pathlib import Path

    written = write_jsonl(Path(args.out), (t.model_dump(mode="json") for t in tickets))
    print(f"\nwrote {written} records -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
