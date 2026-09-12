"""Ported from v2 tests/unit/test_priority.py: the rules over the words.

The half that assigns priority from a grounded bundle moved to services/grounding with
grounding/priority.py (Phase 5).
"""

from __future__ import annotations

import pytest

from app.rules import triage


@pytest.mark.parametrize(
    "text,expected",
    [
        ("no internet in the whole area since this morning", "network_operations"),
        ("I was charged twice on my last invoice", "billing"),
        ("my router is broken and the light is red", "technical_support"),
        ("please send a technician, the cable outside is damaged", "field_service"),
        ("I want to cancel my account", "retention"),
        ("I would like to upgrade my plan to something faster", "sales"),
    ],
)
def test_routing_follows_what_they_wrote(text: str, expected: str):
    assert triage(text).department == expected


def test_the_text_outranks_the_category_they_picked():
    outcome = triage("I was charged twice on my last invoice", category="connection")
    assert outcome.department == "billing"
    assert outcome.routed_by == "what they wrote"


def test_the_category_is_the_fallback_when_nothing_matches():
    outcome = triage("Hello, I have a question about something.", category="billing")
    assert outcome.department == "billing"
    assert outcome.routed_by == "the category they chose"


def test_every_level_is_inside_the_scale():
    for text in ("", "hello", "URGENT!!! NO INTERNET IN THE WHOLE AREA AGAIN, THIS IS UNACCEPTABLE",
                 "thank you for the excellent service"):
        assert 1 <= triage(text).level <= 10


def test_a_broken_service_outranks_a_calm_question():
    assert triage("my router is broken and nothing works").level > triage("could you tell me when my next bill is due").level


def test_a_wider_fault_outranks_a_single_line():
    assert triage("no internet in the whole area, everyone in my street is down").level > triage("my internet is not working").level


def test_shouting_and_repetition_raise_the_level():
    calm = triage("my internet is not working")
    angry = triage("my internet is not working AGAIN, this is the third time, unacceptable!!")
    assert angry.level > calm.level


def test_a_business_account_outranks_a_consumer_on_the_same_words():
    text = "our connection is not working"
    assert triage(text, customer_segment="enterprise").level > triage(text, customer_segment="consumer").level


def test_the_reasons_are_sentences_an_agent_can_read():
    outcome = triage("no internet since this morning, this is urgent")
    assert outcome.reasons
    for reason in outcome.reasons:
        assert reason["detail"].strip() and reason["matched"] is True
