"""Tests for the labelling pipeline: prompt shape, answer merging, cache, self-agreement.

A stub provider stands in for the LLM so the whole path -- prompt build, schema-forced call,
cache, merge, validation -- is exercised without a key or a network call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LABEL_DIR = Path(__file__).resolve().parents[1] / "label"
sys.path.insert(0, str(LABEL_DIR))

import _paths  # noqa: F401,E402  (sets sys.path for schema + MVP stages)
import prompt as prompt_module  # noqa: E402
import run_labelling  # noqa: E402
import validate as validate_module  # noqa: E402
from cache import LabelCache  # noqa: E402

from schema import (  # noqa: E402
    Channel,
    Department,
    Modality,
    OutageScope,
    PriorityBand,
    RequestBody,
    Sentiment,
    Signals,
    TriageSource,
    UnifiedTicket,
    validate_ticket,
)


def make_ticket(text: str = "my internet is down", **overrides) -> UnifiedTicket:
    base = dict(
        ticket_id="T-1",
        customer_id="C-1",
        channel=Channel.web_portal,
        request=RequestBody(modality=Modality.text, text=text),
        signals=Signals(service_down=True, sentiment=Sentiment.frustrated, sentiment_score=0.4),
        fused_text=f"[REQUEST]\n{text}",
    )
    base.update(overrides)
    return UnifiedTicket(**base)


ANSWER = {
    "triage": {
        "intent": "report_outage",
        "department": "network_operations",
        "urgency": "high",
        "priority_score": 72,
        "confidence": 0.88,
        "rationale": "No service, single premises.",
    },
    "signals": {
        "service_down": True,
        "payment_related": False,
        "repeat_contact": False,
        "offensive": False,
        "polite": False,
        "interrogative": False,
        "colloquial": False,
        "noisy_text": False,
        "device_visible": False,
        "sentiment": "angry",
        "sentiment_score": 0.7,
        "outage_scope": "local",
        "urgency_keywords": ["down"],
        "fault_leds": [],
        "error_codes": [],
    },
}


class StubProvider:
    """Deterministic stand-in for a hosted model. Records every call it receives."""

    name = "stub"

    def __init__(self, answer: dict | None = None) -> None:
        self.answer = answer or ANSWER
        self.calls: list[list[dict]] = []

    def model_id(self) -> str:
        return "stub/v1"

    def chat(self, messages, json_schema=None, **kwargs):
        self.calls.append(messages)
        assert json_schema is not None, "labelling must always force a JSON schema"
        return self.answer


# --------------------------------------------------------------------------- #
# prompt
# --------------------------------------------------------------------------- #
def test_prompt_carries_system_fewshot_and_the_ticket():
    messages = prompt_module.build_messages(make_ticket())

    assert messages[0]["role"] == "system"
    assert len(messages) == 1 + 2 * len(prompt_module.FEW_SHOT) + 1
    assert messages[-1]["role"] == "user"
    assert "my internet is down" in messages[-1]["content"]


def test_prompt_frames_prefilled_signals_as_hints():
    """If the flags read as answers the labeller just echoes the keyword rules back."""
    rendered = prompt_module.user_message(make_ticket())
    assert "hints, may be wrong" in rendered
    assert "service_down=true" in rendered


def test_prompt_omits_unset_flags():
    rendered = prompt_module.render_signals(Signals(service_down=True))
    assert "service_down=true" in rendered
    assert "payment_related" not in rendered      # a wall of false teaches nothing


def test_audio_tickets_are_flagged_as_transcripts():
    ticket = make_ticket(
        request=RequestBody(modality=Modality.audio, text="hello i cannot connect", language="pl")
    )
    assert "ASR transcript (pl)" in prompt_module.user_message(ticket)


def test_response_schema_constrains_the_enums():
    schema = prompt_module.response_schema()
    triage = schema["properties"]["triage"]["properties"]

    assert triage["department"]["enum"] == [d.value for d in Department]
    assert triage["urgency"]["enum"] == [b.value for b in PriorityBand]
    assert schema["additionalProperties"] is False


# --------------------------------------------------------------------------- #
# merging an answer back onto a ticket
# --------------------------------------------------------------------------- #
def test_apply_label_populates_triage_and_keeps_the_ticket_valid():
    labelled = run_labelling.apply_label(make_ticket(), ANSWER, "stub/v1")

    assert labelled.triage is not None
    assert labelled.triage.department is Department.network_operations
    assert labelled.triage.urgency is PriorityBand.high
    assert labelled.triage.source is TriageSource.llm
    assert labelled.triage.model_version == "stub/v1"
    validate_ticket(labelled)


def test_corrected_signals_override_the_prefill():
    labelled = run_labelling.apply_label(make_ticket(), ANSWER, "stub/v1")

    assert labelled.signals.sentiment is Sentiment.angry          # was frustrated
    assert labelled.signals.sentiment_score == 0.7                # was 0.4
    assert labelled.signals.outage_scope is OutageScope.local     # was single


def test_account_context_survives_the_labeller():
    """The labeller never sees segment or SLA age, so it must not be able to erase them."""
    ticket = make_ticket()
    ticket.signals.customer_segment_score = 0.9
    ticket.signals.sla_age_score = 0.5

    labelled = run_labelling.apply_label(ticket, ANSWER, "stub/v1")
    assert labelled.signals.customer_segment_score == 0.9
    assert labelled.signals.sla_age_score == 0.5


def test_prefill_is_kept_for_the_override_report():
    labelled = run_labelling.apply_label(make_ticket(), ANSWER, "stub/v1")
    assert labelled.metadata["prefilled_signals"]["sentiment"] == "frustrated"


def test_score_is_clamped_into_its_band():
    """A teacher that says `low` but scores 95 is contradicting itself; the band wins."""
    answer = json.loads(json.dumps(ANSWER))
    answer["triage"]["urgency"] = "low"
    answer["triage"]["priority_score"] = 95

    labelled = run_labelling.apply_label(make_ticket(), answer, "stub/v1")
    assert labelled.triage.urgency is PriorityBand.low
    assert labelled.triage.priority_score == 34


def test_intent_is_normalised():
    answer = json.loads(json.dumps(ANSWER))
    answer["triage"]["intent"] = "Report Outage"
    assert run_labelling.apply_label(make_ticket(), answer, "s").triage.intent == "report_outage"


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def test_second_call_is_served_from_cache(tmp_path):
    provider = StubProvider()
    cache = LabelCache(tmp_path / "cache.json")
    ticket = make_ticket()

    _first, from_cache_1 = run_labelling.label_one(
        ticket, provider, cache, taxonomy=None, temperature=0.3, model_id="stub/v1"
    )
    _second, from_cache_2 = run_labelling.label_one(
        ticket, provider, cache, taxonomy=None, temperature=0.3, model_id="stub/v1"
    )

    assert (from_cache_1, from_cache_2) == (False, True)
    assert len(provider.calls) == 1


def test_cache_survives_a_reload(tmp_path):
    path = tmp_path / "cache.json"
    provider = StubProvider()
    ticket = make_ticket()

    cache = LabelCache(path)
    run_labelling.label_one(
        ticket, provider, cache, taxonomy=None, temperature=0.3, model_id="stub/v1"
    )
    cache.flush()

    _reloaded, from_cache = run_labelling.label_one(
        ticket, provider, LabelCache(path), taxonomy=None, temperature=0.3, model_id="stub/v1"
    )
    assert from_cache
    assert len(provider.calls) == 1


def test_a_prompt_change_invalidates_the_cache(tmp_path):
    """Reusing labels written under a different prompt would silently mix two datasets."""
    key_a = LabelCache.key(model="m", temperature=0.3, prompt_version=1, payload="x")
    key_b = LabelCache.key(model="m", temperature=0.3, prompt_version=2, payload="x")
    assert key_a != key_b


def test_the_repeat_pass_is_not_served_from_the_first_pass(tmp_path):
    """Self-agreement is meaningless if the second sample is a cache replay of the first."""
    provider = StubProvider()
    cache = LabelCache(tmp_path / "cache.json")
    ticket = make_ticket()

    run_labelling.label_one(
        ticket, provider, cache, taxonomy=None, temperature=0.3, model_id="stub/v1"
    )
    _repeat, from_cache = run_labelling.label_one(
        ticket, provider, cache, taxonomy=None, temperature=0.3, model_id="stub/v1",
        cache_salt="|repeat",
    )

    assert not from_cache
    assert len(provider.calls) == 2


def test_corrupt_cache_is_survivable(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(LabelCache(path)) == 0


# --------------------------------------------------------------------------- #
# validation report
# --------------------------------------------------------------------------- #
def test_self_agreement_counts_matching_labels():
    first = run_labelling.apply_label(make_ticket(), ANSWER, "s")

    disagreeing = json.loads(json.dumps(ANSWER))
    disagreeing["triage"]["urgency"] = "low"
    disagreeing["triage"]["priority_score"] = 10
    second = run_labelling.apply_label(make_ticket(), disagreeing, "s")

    agreement = validate_module.self_agreement([first], [second])
    assert agreement["department"] == 1.0
    assert agreement["urgency"] == 0.0
    assert agreement["score_within_10"] == 0.0


def test_self_agreement_is_empty_without_overlap():
    first = run_labelling.apply_label(make_ticket(), ANSWER, "s")
    other = run_labelling.apply_label(make_ticket(ticket_id="T-2"), ANSWER, "s")
    other.ticket_id = "T-2"
    assert validate_module.self_agreement([first], [other])["n"] == 0.0


@pytest.mark.parametrize(
    "intent,department,expected_mismatch",
    [
        ("get_invoice", Department.billing, False),
        ("get_invoice", Department.network_operations, True),
        ("recover_password", Department.technical_support, False),
    ],
)
def test_intent_department_consistency_map(intent, department, expected_mismatch):
    allowed = validate_module.INTENT_DEPARTMENTS[intent]
    assert (department not in allowed) is expected_mismatch
