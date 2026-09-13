"""Single source of truth for the DSEP22 unified ticket type.

This module is standalone by design: it copies the enums and evidence sub-models from
`v1/libs/domain` rather than importing them, so `MVP/` and `TriageModel/` share one
schema without depending on the `v1` package layout. Nothing here does I/O.

`MVP/api/schema.py` re-exports this module through a path shim -- never edit a second copy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums (copied verbatim from v1/libs/domain/enums.py)
# --------------------------------------------------------------------------- #
class Modality(str, Enum):
    text = "text"
    audio = "audio"
    image = "image"
    # A request the customer both typed and spoke. Not "text plus an attachment" -- images
    # are supplementary evidence and never change the modality; this is two renderings of
    # the request itself, and both are carried in `RequestBody.text`.
    multimodal = "multimodal"


class Channel(str, Enum):
    web_portal = "web_portal"
    email = "email"
    phone = "phone"
    chat = "chat"


class TicketState(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    AGGREGATED = "AGGREGATED"
    TRIAGED = "TRIAGED"
    DIAGNOSED = "DIAGNOSED"
    READY_FOR_AGENT = "READY_FOR_AGENT"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class AttachmentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Department(str, Enum):
    technical_support = "technical_support"
    billing = "billing"
    network_operations = "network_operations"
    field_service = "field_service"
    sales = "sales"
    retention = "retention"
    general = "general"


class PriorityBand(str, Enum):
    critical = "critical"
    high = "high"
    normal = "normal"
    low = "low"


class Sentiment(str, Enum):
    angry = "angry"
    frustrated = "frustrated"
    neutral = "neutral"
    satisfied = "satisfied"


class OutageScope(str, Enum):
    """How wide the reported fault is. Drives the outage_scope term of the priority score."""

    single = "single"      # one customer / one device
    local = "local"        # street, building, single cell
    regional = "regional"  # area-wide outage


class TriageSource(str, Enum):
    """Which mechanism produced a Triage.

    Matters for distillation: rows the distilled model labelled itself must never re-enter
    its own training set, or the model trains on its own errors.
    """

    rules = "rules"    # static equation -- what the MVP ships
    llm = "llm"        # teacher pass over the corpus
    model = "model"    # distilled classifier -- phase 2
    human = "human"    # agent correction, the gold standard


class DecisionType(str, Enum):
    APPROVE_SEND = "APPROVE_SEND"
    EDIT = "EDIT"
    REJECT = "REJECT"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"
    EXECUTE_ACTION = "EXECUTE_ACTION"


class FlagCode(str, Enum):
    PARTIAL_PAYLOAD = "PARTIAL_PAYLOAD"
    LOW_ASR_CONFIDENCE = "LOW_ASR_CONFIDENCE"
    LOW_VLM_CONFIDENCE = "LOW_VLM_CONFIDENCE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    RETRIEVAL_EMPTY = "RETRIEVAL_EMPTY"
    UNVERIFIED_CITATION = "UNVERIFIED_CITATION"
    PII_DETECTED = "PII_DETECTED"
    NO_DRAFT = "NO_DRAFT"


# --------------------------------------------------------------------------- #
# Evidence sub-models (ported from v1/libs/domain/contracts/media.py + payload.py)
# --------------------------------------------------------------------------- #
class Segment(BaseModel):
    start_s: float
    end_s: float
    text: str
    confidence: float


class LedState(BaseModel):
    label: str      # e.g. "WAN", "DSL", "POWER"
    colour: str     # e.g. "red", "green", "amber", "off"
    behaviour: str  # "solid" | "blinking" | "off"

    @property
    def is_fault(self) -> bool:
        """A red/amber/dark indicator is a fault; green is not. The single most
        diagnostic visual cue in ISP support."""
        return self.colour.lower() in {"red", "amber", "orange", "off"}


class Provenance(BaseModel):
    modality: Modality
    source: str
    span: tuple[int, int]
    confidence: float
    model_version: str | None = None


class PolicyFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    span: tuple[int, int] | None = None


class UrgencySignal(BaseModel):
    name: str
    weight: int
    matched: bool


# --------------------------------------------------------------------------- #
# The four blocks of the unified type
# --------------------------------------------------------------------------- #
class RequestBody(BaseModel):
    """WHAT the customer asked -- typed, spoken, or both.

    `text` is the whole request as one string, which is what every downstream stage reads.
    When the customer both typed and spoke, `typed_text` and `transcript_text` keep the two
    halves separately addressable, so the agent panel can show which words were transcribed
    and the corpus can measure them apart.
    """

    modality: Modality
    text: str
    language: str = "en"
    audio_ref: str | None = None
    duration_s: float | None = None
    asr_confidence: float | None = None
    asr_model_version: str | None = None
    segments: list[Segment] = Field(default_factory=list)
    typed_text: str | None = None
    transcript_text: str | None = None

    @property
    def is_transcribed(self) -> bool:
        """True when any of the text is machine-produced, and therefore noisy. Notebook 05
        shows the clean/noisy shift split -- transcribed text belongs to the shifted
        distribution, and a part-transcribed request is partly in it too."""
        return self.modality in (Modality.audio, Modality.multimodal)

    @property
    def low_confidence(self) -> bool:
        """ASR below the review threshold. The agent panel badges these."""
        return self.asr_confidence is not None and self.asr_confidence < 0.6


class ImageEvidence(BaseModel):
    """Supplementary evidence attached to a request. Never the request itself."""

    attachment_id: str
    detected_classes: list[str] = Field(default_factory=list)
    class_confidences: dict[str, float] = Field(default_factory=dict)
    device_model: str | None = None
    led_states: list[LedState] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    caption: str | None = None      # VLM summary; stays None in the MVP
    model_version: str = "unknown"
    low_confidence: bool = False

    @property
    def top_class(self) -> str | None:
        """Highest-confidence detection, or None if nothing was detected."""
        if self.class_confidences:
            return max(self.class_confidences.items(), key=lambda kv: kv[1])[0]
        return self.detected_classes[0] if self.detected_classes else None

    def render(self) -> str:
        """One-line rendering appended to `fused_text` by the fusion stage.

        Lives here, next to the structured fields, so the text form and the structured form
        cannot drift apart -- the LLM reads this string while the classifier reads the
        fields, and they must describe the same image.
        """
        parts: list[str] = []
        if self.device_model:
            parts.append(f"device={self.device_model}")
        if self.detected_classes:
            parts.append("visible=" + ",".join(self.detected_classes))
        for led in self.led_states:
            parts.append(f"LED {led.label}={led.colour}/{led.behaviour}")
        if self.error_codes:
            parts.append("errors=" + ",".join(self.error_codes))
        if self.caption:
            parts.append(self.caption)
        return f"[image {self.attachment_id}] " + ("; ".join(parts) or "no features extracted")


class Signals(BaseModel):
    """Flags extracted from the request text and the image evidence.

    Rule-prefilled before labelling; the LLM labeller may override any field.
    """

    # lexical / linguistic (the Bitext `flags` column maps here)
    urgency_keywords: list[str] = Field(default_factory=list)
    colloquial: bool = False        # Bitext Q
    noisy_text: bool = False        # Bitext Z, and always true for ASR output
    offensive: bool = False         # Bitext W
    polite: bool = False            # Bitext P
    interrogative: bool = False     # Bitext I
    # semantic
    sentiment: Sentiment = Sentiment.neutral
    sentiment_score: float = 0.0    # 0..1, higher = angrier
    service_down: bool = False
    payment_related: bool = False
    repeat_contact: bool = False
    outage_scope: OutageScope = OutageScope.single
    # visual
    device_visible: bool = False
    fault_leds: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    # account context (from the customer record, not from the text)
    customer_segment_score: float = Field(default=0.0, ge=0.0, le=1.0)  # 0=mass, 1=VIP
    prior_contacts_score: float = Field(default=0.0, ge=0.0, le=1.0)
    sla_age_score: float = Field(default=0.0, ge=0.0, le=1.0)           # 1=SLA breached

    # Bitext flag letter -> field. B (basic syntax) and L (semantic variation) are
    # clean-phrasing markers with no triage meaning, so they are deliberately unmapped.
    BITEXT_FLAG_MAP: ClassVar[dict[str, str]] = {
        "Q": "colloquial",
        "Z": "noisy_text",
        "W": "offensive",
        "P": "polite",
        "I": "interrogative",
    }

    @classmethod
    def from_bitext_flags(cls, flags: str, **overrides: Any) -> "Signals":
        """Build from a Bitext `flags` string such as "BQZ".

        This is free supervision: the 27K corpus already hand-tags these five linguistic
        properties, so they need no LLM pass and no annotation budget.
        """
        set_fields = {
            cls.BITEXT_FLAG_MAP[ch]: True for ch in (flags or "") if ch in cls.BITEXT_FLAG_MAP
        }
        return cls(**{**set_fields, **overrides})

    def merge_visual(self, images: list["ImageEvidence"]) -> None:
        """Lift visual facts out of the evidence list so triage never re-opens the images.
        Idempotent -- safe to call again after re-processing."""
        self.device_visible = bool(images)
        self.fault_leds = sorted(
            {led.label for img in images for led in img.led_states if led.is_fault}
        )
        self.error_codes = sorted({code for img in images for code in img.error_codes})

    def as_features(self) -> dict[str, float]:
        """Flatten to the numeric feature vector consumed by the triage model and by the
        Spark job. Insertion-ordered, so the parquet column order is deterministic."""
        return {
            "n_urgency_keywords": float(len(self.urgency_keywords)),
            "colloquial": float(self.colloquial),
            "noisy_text": float(self.noisy_text),
            "offensive": float(self.offensive),
            "polite": float(self.polite),
            "interrogative": float(self.interrogative),
            "sentiment_score": self.sentiment_score,
            "service_down": float(self.service_down),
            "payment_related": float(self.payment_related),
            "repeat_contact": float(self.repeat_contact),
            "outage_local": float(self.outage_scope is OutageScope.local),
            "outage_regional": float(self.outage_scope is OutageScope.regional),
            "device_visible": float(self.device_visible),
            "n_fault_leds": float(len(self.fault_leds)),
            "n_error_codes": float(len(self.error_codes)),
            "customer_segment_score": self.customer_segment_score,
            "prior_contacts_score": self.prior_contacts_score,
            "sla_age_score": self.sla_age_score,
        }


class Triage(BaseModel):
    """The prediction target: what the distilled classifier must learn to emit."""

    intent: str                     # 27-way Bitext taxonomy
    department: Department
    urgency: PriorityBand
    priority_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    source: TriageSource
    rationale: str | None = None
    signals_detail: list[UrgencySignal] = Field(default_factory=list)
    alternatives: list[Department] = Field(default_factory=list)
    model_version: str | None = None

    def explain(self) -> str:
        """Human-readable one-liner. The agent panel renders this under the urgency band."""
        matched = ", ".join(s.name for s in self.signals_detail if s.matched)
        return (
            f"{self.department.value} / {self.urgency.value} "
            f"(score={self.priority_score}, via {self.source.value}) [{matched}]"
        )

    @property
    def needs_human_review(self) -> bool:
        """Low confidence or a critical band both force a human into the loop."""
        return self.confidence < 0.6 or self.urgency is PriorityBand.critical


class UnifiedTicket(BaseModel):
    schema_version: str = "1.0.0"
    ticket_id: str
    customer_id: str
    channel: Channel
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request: RequestBody
    images: list[ImageEvidence] = Field(default_factory=list)
    signals: Signals = Field(default_factory=Signals)
    triage: Triage | None = None
    fused_text: str = ""
    provenance: list[Provenance] = Field(default_factory=list)
    partial: bool = False   # a modality stage failed; triage on what we have
    revision: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_triaged(self) -> bool:
        return self.triage is not None

    def to_jsonl(self) -> str:
        """One line of the corpus wire format (`TriageModel/data/*.jsonl`)."""
        return self.model_dump_json()

    @classmethod
    def from_jsonl(cls, line: str) -> "UnifiedTicket":
        return cls.model_validate_json(line)


class TicketInvalid(ValueError):
    pass


def validate_ticket(ticket: UnifiedTicket) -> None:
    """Structural checks pydantic cannot express: non-empty request, sane spans.

    An image-only submission is a validation error by design -- images are supplementary
    evidence, so a ticket must carry text or audio to be a request at all.
    """
    if not ticket.request.text.strip():
        raise TicketInvalid(
            f"ticket {ticket.ticket_id}: request.text is empty (text or audio required)"
        )
    if not ticket.fused_text.strip():
        raise TicketInvalid(f"ticket {ticket.ticket_id}: fused_text is empty")

    ids = [img.attachment_id for img in ticket.images]
    if len(ids) != len(set(ids)):
        raise TicketInvalid(f"ticket {ticket.ticket_id}: duplicate attachment_id in images")

    if ticket.triage is not None and ticket.triage.source is TriageSource.model:
        if ticket.triage.model_version is None:
            raise TicketInvalid(
                f"ticket {ticket.ticket_id}: source=model requires model_version, so "
                f"self-labelled rows can be excluded from the next training set"
            )

    fused_len = len(ticket.fused_text)
    spans = sorted((p.span for p in ticket.provenance), key=lambda s: s[0])
    prev_end: int | None = None
    for start, end in spans:
        if start < 0 or end > fused_len or start > end:
            raise TicketInvalid(
                f"ticket {ticket.ticket_id}: span ({start}, {end}) exceeds "
                f"fused_text length {fused_len}"
            )
        if prev_end is not None and start < prev_end:
            raise TicketInvalid(
                f"ticket {ticket.ticket_id}: provenance spans overlap at offset {start}"
            )
        prev_end = end


SCHEMA_PATH = Path(__file__).with_name("schema.json")


def write_schema_json(path: Path = SCHEMA_PATH) -> Path:
    """Emit the JSON Schema read by the LLM labeller and the Postgres jsonb check."""
    path.write_text(
        json.dumps(UnifiedTicket.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    return path


if __name__ == "__main__":
    print(write_schema_json())
