"""The labelling prompt: system instructions, few-shot examples, and the forced JSON schema.

The teacher sees the fused request plus the rule-prefilled `Signals`, and returns a `Triage`
together with a corrected `Signals`. The prefilled flags are explicitly framed as hints so
the model overrides them when the text disagrees -- otherwise the labels would only ever
recover the keyword rules that produced them, and distilling that is pointless.
"""

from __future__ import annotations

import json
from typing import Any

import _paths  # noqa: F401  (sets sys.path)

from schema import Department, PriorityBand, Sentiment, Signals, UnifiedTicket

DEPARTMENTS = [d.value for d in Department]
URGENCIES = [b.value for b in PriorityBand]
SENTIMENTS = [s.value for s in Sentiment]
SCOPES = ["single", "local", "regional"]

SYSTEM = f"""\
You are labelling customer-support tickets for a telecom operator, to build the training set
for a small triage classifier. Your labels are the ground truth that model will imitate, so
be consistent above all: the same ticket must always get the same label.

For each ticket decide four things.

1. intent -- a short snake_case label for what the customer wants. Prefer a label from the
   taxonomy you are given when one fits; invent one only when nothing fits.

2. department -- exactly one of: {", ".join(DEPARTMENTS)}
   - network_operations: outages and faults affecting more than one customer
   - field_service: something needs a technician on site
   - technical_support: one customer's device, connection, login or account settings
   - billing: invoices, charges, refunds, payment methods
   - sales: new orders, upgrades, deliveries, pricing
   - retention: the customer is cancelling, leaving, or formally complaining
   - general: genuinely none of the above

3. urgency -- one of: {", ".join(URGENCIES)}
   - critical: service is down for many people, or there is a safety or legal risk
   - high: this customer has no working service, or has been failed repeatedly
   - normal: a real problem with a working service, or a question needing a real answer
   - low: routine questions, information requests, praise
   Anger alone is not urgency. A furious customer asking a routine question is `normal`.
   An outage reported politely is still `high` or `critical`.

4. priority_score -- 0-100, consistent with the band:
   critical 80-100, high 60-79, normal 35-59, low 0-34.

Also return a corrected `signals` object. You are given rule-extracted flags as HINTS. They
come from keyword matching and are often wrong: correct anything the text contradicts, and
set flags the keywords missed. Judge the flags from the customer's words, not from the hints.

Return only the JSON object. No prose, no code fences.
"""

FEW_SHOT: list[tuple[str, dict[str, Any]]] = [
    (
        """[REQUEST]
The internet has been down since 6am for our whole street. I have called twice already and
nobody has called back. We run a business from here.

SIGNALS (hints, may be wrong): service_down=true; outage_scope=local; repeat_contact=true;
sentiment=frustrated (0.40); urgency_keywords=[still waiting]""",
        {
            "triage": {
                "intent": "report_outage",
                "department": "network_operations",
                "urgency": "critical",
                "priority_score": 88,
                "confidence": 0.92,
                "rationale": "Multi-premises outage lasting hours, repeat contact, business impact.",
            },
            "signals": {
                "service_down": True,
                "outage_scope": "local",
                "repeat_contact": True,
                "payment_related": False,
                "sentiment": "frustrated",
                "sentiment_score": 0.55,
                "urgency_keywords": ["down since 6am", "called twice"],
            },
        },
    ),
    (
        """[REQUEST]
Hello, could you please send me a copy of last month's invoice? Thank you kindly.

SIGNALS (hints, may be wrong): payment_related=true; polite=true; interrogative=true;
sentiment=neutral (0.00)""",
        {
            "triage": {
                "intent": "get_invoice",
                "department": "billing",
                "urgency": "low",
                "priority_score": 8,
                "confidence": 0.97,
                "rationale": "Routine document request, service unaffected, no time pressure.",
            },
            "signals": {
                "payment_related": True,
                "polite": True,
                "interrogative": True,
                "service_down": False,
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "urgency_keywords": [],
            },
        },
    ),
    (
        """[REQUEST]
This is the WORST service I have ever had. Absolutely useless. I want to cancel everything
right now and I am telling everyone about this.

SIGNALS (hints, may be wrong): sentiment=angry (0.85); urgency_keywords=[right now];
service_down=false""",
        {
            "triage": {
                "intent": "cancel_service",
                "department": "retention",
                "urgency": "high",
                "priority_score": 68,
                "confidence": 0.9,
                "rationale": "Churn risk with reputational threat; no technical fault reported, "
                "so this is a retention call rather than an outage.",
            },
            "signals": {
                "service_down": False,
                "payment_related": False,
                "repeat_contact": False,
                "sentiment": "angry",
                "sentiment_score": 0.9,
                "offensive": False,
                "urgency_keywords": ["right now"],
            },
        },
    ),
]


def _signals_schema() -> dict[str, Any]:
    """A flat, strict schema for the corrected signals the labeller returns."""
    boolean_fields = [
        "colloquial", "noisy_text", "offensive", "polite", "interrogative",
        "service_down", "payment_related", "repeat_contact", "device_visible",
    ]
    properties: dict[str, Any] = {name: {"type": "boolean"} for name in boolean_fields}
    properties.update(
        {
            "urgency_keywords": {"type": "array", "items": {"type": "string"}},
            "sentiment": {"type": "string", "enum": SENTIMENTS},
            "sentiment_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "outage_scope": {"type": "string", "enum": SCOPES},
            "fault_leds": {"type": "array", "items": {"type": "string"}},
            "error_codes": {"type": "array", "items": {"type": "string"}},
        }
    )
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def response_schema() -> dict[str, Any]:
    """The JSON Schema every labelling call is forced to conform to."""
    return {
        "type": "object",
        "properties": {
            "triage": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "department": {"type": "string", "enum": DEPARTMENTS},
                    "urgency": {"type": "string", "enum": URGENCIES},
                    "priority_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "intent", "department", "urgency", "priority_score", "confidence", "rationale"
                ],
                "additionalProperties": False,
            },
            "signals": _signals_schema(),
        },
        "required": ["triage", "signals"],
        "additionalProperties": False,
    }


def render_signals(signals: Signals) -> str:
    """The hint block. Only flags that are actually set are shown -- a wall of `false` teaches
    the model nothing and costs tokens on every call."""
    parts: list[str] = []
    for field in (
        "service_down", "payment_related", "repeat_contact", "device_visible",
        "colloquial", "noisy_text", "offensive", "polite", "interrogative",
    ):
        if getattr(signals, field):
            parts.append(f"{field}=true")
    if signals.outage_scope.value != "single":
        parts.append(f"outage_scope={signals.outage_scope.value}")
    parts.append(f"sentiment={signals.sentiment.value} ({signals.sentiment_score:.2f})")
    if signals.urgency_keywords:
        parts.append("urgency_keywords=[" + ", ".join(signals.urgency_keywords) + "]")
    if signals.fault_leds:
        parts.append("fault_leds=[" + ", ".join(signals.fault_leds) + "]")
    if signals.error_codes:
        parts.append("error_codes=[" + ", ".join(signals.error_codes) + "]")
    return "; ".join(parts)


def user_message(ticket: UnifiedTicket, taxonomy: list[str] | None = None) -> str:
    lines = [ticket.fused_text.strip(), ""]
    lines.append(f"SIGNALS (hints, may be wrong): {render_signals(ticket.signals)}")
    if ticket.request.modality.value == "audio":
        lines.append(
            f"NOTE: this is an ASR transcript ({ticket.request.language}); expect "
            "transcription noise and judge the intent through it."
        )
    if taxonomy:
        lines.append("")
        lines.append("Known intent taxonomy: " + ", ".join(sorted(taxonomy)))
    return "\n".join(lines)


def build_messages(ticket: UnifiedTicket, taxonomy: list[str] | None = None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    for example_input, example_output in FEW_SHOT:
        messages.append({"role": "user", "content": example_input})
        messages.append({"role": "assistant", "content": json.dumps(example_output)})
    messages.append({"role": "user", "content": user_message(ticket, taxonomy)})
    return messages
