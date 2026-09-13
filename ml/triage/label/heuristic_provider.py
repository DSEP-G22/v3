"""An offline stand-in teacher, so the labelling → training chain can be run without a key.

It answers in exactly the shape the real prompt forces, using the ported static equation for
urgency and the intent→department map for routing. That makes it useful for two things:
exercising the pipeline end to end in CI, and giving the distilled model a floor to beat.

It is NOT a substitute for the LLM pass. Its labels are the keyword rules by construction, so
a student distilled from them learns the rules and nothing more -- which is precisely the
thing the plan says the LLM pass exists to avoid. Runs made with it are tagged as such in
`labelled_by` so no score table can quietly attribute them to a real teacher.
"""

from __future__ import annotations

from typing import Any

import _paths  # noqa: F401  (sets sys.path)

from pipeline import triage as triage_stage  # noqa: E402

from schema import Signals  # noqa: E402


class HeuristicProvider:
    name = "heuristic"

    def model_id(self) -> str:
        return "heuristic/static-equation-v1"

    def chat(
        self, messages: list[dict[str, str]], json_schema: dict | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        # The ticket text is the last user turn; the hint block follows a blank line.
        content = messages[-1]["content"]
        text = content.split("SIGNALS (hints")[0].strip()

        signals = _signals_from_hints(content)
        result = triage_stage.triage(text, signals, intent=_intent_from_taxonomy(content))

        return {
            "triage": {
                "intent": result.intent,
                "department": result.department.value,
                "urgency": result.urgency.value,
                "priority_score": result.priority_score,
                "confidence": 0.5,       # honest: this is a rule, not a judgement
                "rationale": result.rationale or "static equation",
            },
            "signals": {
                "colloquial": signals.colloquial,
                "noisy_text": signals.noisy_text,
                "offensive": signals.offensive,
                "polite": signals.polite,
                "interrogative": signals.interrogative,
                "service_down": signals.service_down,
                "payment_related": signals.payment_related,
                "repeat_contact": signals.repeat_contact,
                "device_visible": signals.device_visible,
                "sentiment": signals.sentiment.value,
                "sentiment_score": signals.sentiment_score,
                "outage_scope": signals.outage_scope.value,
                "urgency_keywords": signals.urgency_keywords,
                "fault_leds": signals.fault_leds,
                "error_codes": signals.error_codes,
            },
        }


def _signals_from_hints(content: str) -> Signals:
    """Re-extract from the request text rather than parsing the hint block back."""
    from pipeline import signals as signals_stage

    text = content.split("SIGNALS (hints")[0].strip()
    body = text.split("\n", 1)[1] if "\n" in text else text
    return signals_stage.extract(body)


STOPWORDS = {"about", "with", "have", "need", "want", "help", "there", "your", "please"}


def _intent_from_taxonomy(content: str) -> str | None:
    """Pick the taxonomy entry whose distinctive words best match the request text.

    Only the request is searched, not the whole prompt -- matching against the prompt made
    every ticket hit the same intent, because the taxonomy list is itself part of the prompt.
    Words are scored by how rare they are across the taxonomy, so `invoice` counts for much
    more than `order`, which appears in a third of the labels.
    """
    if "Known intent taxonomy:" not in content:
        return None

    taxonomy = [
        entry.strip()
        for entry in content.split("Known intent taxonomy:")[1].split(",")
        if entry.strip()
    ]
    request = content.split("SIGNALS (hints")[0].lower()

    document_frequency: dict[str, int] = {}
    for intent in taxonomy:
        for word in set(intent.split("_")):
            document_frequency[word] = document_frequency.get(word, 0) + 1

    best, best_score = None, 0.0
    for intent in taxonomy:
        score = 0.0
        for word in set(intent.split("_")):
            if len(word) <= 3 or word in STOPWORDS:
                continue
            if word in request:
                score += 1.0 / document_frequency[word]
        if score > best_score:
            best, best_score = intent, score
    return best
