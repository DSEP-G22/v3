"""Schema contract tests: construction, validation rules, JSON Schema emission."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load the real schema by file path, not by name. `MVP/api/schema.py` is a re-export shim
# that is also importable as `schema`, so whichever directory reaches `sys.path` first wins
# -- and running this suite in the same command as the MVP's tests made the shim win.
_SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schema.py"
_spec = importlib.util.spec_from_file_location("triage_schema_under_test", _SCHEMA_FILE)
schema = importlib.util.module_from_spec(_spec)
sys.modules["triage_schema_under_test"] = schema
_spec.loader.exec_module(schema)

from triage_schema_under_test import (  # noqa: E402
    Channel,
    Department,
    ImageEvidence,
    LedState,
    Modality,
    OutageScope,
    PriorityBand,
    Provenance,
    RequestBody,
    Signals,
    TicketInvalid,
    Triage,
    TriageSource,
    UnifiedTicket,
    validate_ticket,
    write_schema_json,
)


def _ticket(**overrides) -> UnifiedTicket:
    base = dict(
        ticket_id="T-1",
        customer_id="C-1",
        channel=Channel.web_portal,
        request=RequestBody(modality=Modality.text, text="my router keeps dropping"),
        fused_text="my router keeps dropping",
    )
    base.update(overrides)
    return UnifiedTicket(**base)


def test_minimal_ticket_validates():
    validate_ticket(_ticket())


def test_roundtrip_through_json():
    t = _ticket(
        images=[ImageEvidence(attachment_id="A-1", detected_classes=["power"], model_version="v1")],
        signals=Signals(service_down=True, urgency_keywords=["urgent"]),
        triage=Triage(
            intent="contact_customer_service",
            department=Department.technical_support,
            urgency=PriorityBand.high,
            priority_score=64,
            confidence=0.8,
            source="llm",
        ),
    )
    restored = UnifiedTicket.model_validate_json(t.model_dump_json())
    assert restored == t


def test_image_only_ticket_is_invalid():
    """Images are supplementary evidence -- a ticket needs text or audio to be a request."""
    with pytest.raises(TicketInvalid, match="request.text is empty"):
        validate_ticket(_ticket(request=RequestBody(modality=Modality.text, text="   ")))


def test_provenance_span_beyond_fused_text_rejected():
    t = _ticket(
        provenance=[
            Provenance(modality=Modality.text, source="request", span=(0, 999), confidence=1.0)
        ]
    )
    with pytest.raises(TicketInvalid, match="exceeds fused_text length"):
        validate_ticket(t)


def test_overlapping_provenance_spans_rejected():
    t = _ticket(
        provenance=[
            Provenance(modality=Modality.text, source="request", span=(0, 10), confidence=1.0),
            Provenance(modality=Modality.image, source="img", span=(5, 15), confidence=1.0),
        ]
    )
    with pytest.raises(TicketInvalid, match="spans overlap"):
        validate_ticket(t)


def test_priority_score_is_bounded():
    with pytest.raises(ValueError):
        Triage(
            intent="x",
            department=Department.general,
            urgency=PriorityBand.low,
            priority_score=101,
            confidence=0.5,
            source="rules",
        )


def test_schema_json_is_current(tmp_path):
    """schema.json on disk must match the model -- the labeller and Postgres both read it."""
    emitted = json.loads(write_schema_json(tmp_path / "schema.json").read_text(encoding="utf-8"))
    on_disk = json.loads(
        (Path(__file__).resolve().parents[1] / "schema.json").read_text(encoding="utf-8")
    )
    assert emitted == on_disk


# --------------------------------------------------------------------------- #
# Signals: Bitext flag mapping and the model feature vector
# --------------------------------------------------------------------------- #
def test_bitext_flags_map_to_signal_fields():
    """The corpus already tags these five properties -- free supervision, no LLM pass."""
    s = Signals.from_bitext_flags("BQZ")
    assert s.colloquial and s.noisy_text
    assert not s.offensive and not s.polite and not s.interrogative


def test_bitext_clean_flags_set_nothing():
    """B (basic syntax) and L (semantic variation) carry no triage meaning."""
    s = Signals.from_bitext_flags("BL")
    assert s.as_features()["colloquial"] == 0.0
    assert s.as_features()["noisy_text"] == 0.0


def test_bitext_overrides_win():
    s = Signals.from_bitext_flags("Q", colloquial=False, service_down=True)
    assert s.colloquial is False
    assert s.service_down is True


def test_feature_vector_is_all_floats_and_stable():
    keys = list(Signals().as_features())
    assert keys == list(Signals(service_down=True).as_features())  # order is deterministic
    assert all(isinstance(v, float) for v in Signals().as_features().values())


def test_outage_scope_is_one_hot_not_ordinal():
    """local and regional are separate columns -- scope is categorical, not a magnitude."""
    f = Signals(outage_scope=OutageScope.regional).as_features()
    assert f["outage_regional"] == 1.0 and f["outage_local"] == 0.0


# --------------------------------------------------------------------------- #
# Evidence lifting and rendering
# --------------------------------------------------------------------------- #
def test_merge_visual_lifts_only_fault_leds():
    img = ImageEvidence(
        attachment_id="A-1",
        led_states=[
            LedState(label="WAN", colour="red", behaviour="solid"),
            LedState(label="POWER", colour="green", behaviour="solid"),
        ],
        error_codes=["E-101"],
    )
    s = Signals()
    s.merge_visual([img])
    assert s.fault_leds == ["WAN"]        # green POWER is not a fault
    assert s.device_visible is True
    assert s.error_codes == ["E-101"]


def test_merge_visual_is_idempotent():
    img = ImageEvidence(attachment_id="A-1", led_states=[LedState(label="WAN", colour="red", behaviour="solid")])
    s = Signals()
    s.merge_visual([img])
    first = s.model_dump()
    s.merge_visual([img])
    assert s.model_dump() == first


def test_render_and_fields_describe_the_same_image():
    """The LLM reads render(); the classifier reads the fields. They must not drift."""
    img = ImageEvidence(
        attachment_id="A-9",
        detected_classes=["router-body"],
        device_model="ZTE-H198A",
        led_states=[LedState(label="WAN", colour="red", behaviour="blinking")],
        error_codes=["E-5"],
    )
    text = img.render()
    assert "ZTE-H198A" in text and "router-body" in text
    assert "LED WAN=red/blinking" in text and "E-5" in text


def test_render_handles_empty_evidence():
    assert "no features extracted" in ImageEvidence(attachment_id="A-0").render()


def test_top_class_prefers_highest_confidence():
    img = ImageEvidence(
        attachment_id="A-1",
        detected_classes=["usb-cable", "router-body"],
        class_confidences={"usb-cable": 0.3, "router-body": 0.9},
    )
    assert img.top_class == "router-body"


# --------------------------------------------------------------------------- #
# Distillation guard: self-labelled rows must be traceable
# --------------------------------------------------------------------------- #
def test_model_sourced_triage_requires_version():
    """Rows the distilled model labelled itself must never re-enter its own training set."""
    t = _ticket(
        triage=Triage(
            intent="x", department=Department.general, urgency=PriorityBand.low,
            priority_score=10, confidence=0.9, source=TriageSource.model,
        )
    )
    with pytest.raises(TicketInvalid, match="requires model_version"):
        validate_ticket(t)


def test_llm_sourced_triage_needs_no_version():
    validate_ticket(
        _ticket(
            triage=Triage(
                intent="x", department=Department.general, urgency=PriorityBand.low,
                priority_score=10, confidence=0.9, source=TriageSource.llm,
            )
        )
    )


def test_duplicate_attachment_ids_rejected():
    t = _ticket(images=[ImageEvidence(attachment_id="A-1"), ImageEvidence(attachment_id="A-1")])
    with pytest.raises(TicketInvalid, match="duplicate attachment_id"):
        validate_ticket(t)


# --------------------------------------------------------------------------- #
# Derived properties used by the agent panel
# --------------------------------------------------------------------------- #
def test_transcribed_request_is_flagged_noisy():
    r = RequestBody(modality=Modality.audio, text="hello", audio_ref="s3://a.wav", asr_confidence=0.4)
    assert r.is_transcribed and r.low_confidence


def test_typed_request_is_not_transcribed():
    r = RequestBody(modality=Modality.text, text="hello")
    assert not r.is_transcribed and not r.low_confidence


def test_critical_band_always_needs_review():
    tri = Triage(
        intent="x", department=Department.general, urgency=PriorityBand.critical,
        priority_score=95, confidence=1.0, source=TriageSource.rules,
    )
    assert tri.needs_human_review


def test_jsonl_roundtrip():
    t = _ticket(signals=Signals.from_bitext_flags("QZ"))
    assert UnifiedTicket.from_jsonl(t.to_jsonl()) == t
