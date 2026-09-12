"""Signal extraction, department routing and a priority from one to ten.

Ported from the MVP's api/pipeline/signals.py and api/pipeline/triage.py, with two changes
that matter.

The scale is one to ten throughout. The MVP carried v1's nought to one hundred equation and
then bucketed it into four bands, which is two scales for one idea. Here the six weighted
terms produce a level directly, and there is no hundred point number anywhere for a screen
to have to hide.

The rules stay rules. No model, no download, no network. That is what makes this
reproducible on a laptop and legible in a review: an operator can read why a ticket was
routed to billing, which is not true of a classifier that returns "general" with sixty
percent confidence and no account of itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------------------

URGENCY_TERMS = (
    "urgent", "urgently", "asap", "immediately", "emergency", "critical", "right now",
    "as soon as possible", "cannot wait", "can't wait", "escalate", "escalation",
    "deadline", "still waiting", "no response", "third time", "second time",
)

#: Phrasings that mean "it is not working". Wider than a native speaker would write,
#: because these are matched against machine translated English: a Sinhala sentence that a
#: person would render as "no internet for two days" comes back as "I have not been on the
#: internet for two days", and both have to route and score the same way.
SERVICE_DOWN_TERMS = (
    "no internet", "no connection", "not working", "isn't working", "is not working",
    "down", "outage", "offline", "disconnected", "keeps dropping", "dropping",
    "no signal", "no service", "cannot connect", "can't connect", "unable to connect",
    "no dial tone", "dead", "blinking red", "red light", "broken", "not able to connect",
    "have not been on the internet", "haven't been on the internet", "without internet",
    "cannot open", "can't open", "cannot browse", "nothing loads", "will not connect",
    "won't connect", "lost connection", "no access", "stopped working", "not connecting",
)

PAYMENT_TERMS = (
    "invoice", "bill", "billing", "charge", "charged", "overcharged", "payment",
    "refund", "credit card", "debit", "direct debit", "subscription", "fee", "fees",
    "price", "pricing", "double charged", "unauthorised", "unauthorized", "outstanding",
)

REPEAT_TERMS = (
    "again", "second time", "third time", "already contacted", "as i said",
    "still waiting", "no one replied", "nobody replied", "follow up", "follow-up",
    "chased", "reopened",
)

ANGRY_TERMS = (
    "furious", "angry", "outrageous", "unacceptable", "ridiculous", "disgusted",
    "appalling", "worst", "terrible", "awful", "fed up", "sick of", "scam", "useless",
    "incompetent", "never again", "cancel my", "lawyer", "complaint", "complain",
)

FRUSTRATED_TERMS = (
    "frustrated", "frustrating", "annoyed", "annoying", "disappointed", "tired of",
    "waiting", "still not", "yet again", "keeps happening", "not happy", "unhappy",
)

SATISFIED_TERMS = (
    "thank you", "thanks", "great", "appreciate", "happy with", "excellent",
    "perfect", "helpful", "well done",
)

REGIONAL_TERMS = (
    "whole area", "entire area", "everyone in", "the whole city", "region", "regional",
    "nationwide", "all our offices",
)
LOCAL_TERMS = (
    "my street", "whole street", "our building", "whole building", "my area", "the block",
    "next door", "my neighbours", "my neighbors", "neighbourhood", "neighborhood",
)

ERROR_CODE_RE = re.compile(r"\b(?:err(?:or)?[\s:_-]*)?([A-Z]{1,4}[-_]?\d{2,5})\b")


# ---------------------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------------------

#: First rule to match wins, so the order is the priority between competing readings. An
#: outage phrase outranks a router phrase, because "no internet in the whole area" is a
#: network problem whatever equipment the customer mentions.
ROUTING_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "network_operations",
        ("outage", "no internet", "no service", "whole area", "entire area", "regional",
         "nationwide", "everyone in", "my neighbours", "my neighbors", "whole street",
         "our building", "whole building", "all our offices", "the whole city"),
    ),
    (
        "field_service",
        ("technician", "engineer visit", "site visit", "cable cut", "damaged cable",
         "installation appointment", "come and fix", "send someone"),
    ),
    (
        "billing",
        ("invoice", "bill", "billing", "refund", "charge", "charged", "payment", "paid",
         "overcharged", "direct debit", "subscription fee", "outstanding", "balance"),
    ),
    (
        "retention",
        ("cancel my subscription", "cancel my account", "close my account",
         "switch provider", "leave your service", "terminate my"),
    ),
    (
        "sales",
        ("upgrade my plan", "new plan", "buy", "purchase", "pricing", "place an order",
         "quote", "faster plan", "change my plan", "upgrade", "faster package",
         "faster internet", "better package", "more data", "add on"),
    ),
    (
        "technical_support",
        # "internet" and "broadband" last in this list on purpose: they appear in billing
        # and sales messages too, and those rules are evaluated before this one, so a bill
        # about an internet package still reaches billing.
        ("router", "wifi", "wi-fi", "modem", "connection", "password", "reset",
         "not working", "error", "slow", "dropping", "broken", "speed", "offline",
         "disconnected", "no dial tone", "keeps cutting", "cannot open", "can't open",
         "nothing loads", "no access", "internet", "broadband", "line"),
    ),
)

DEPARTMENTS = tuple(name for name, _ in ROUTING_RULES) + ("general",)

#: How much the customer's commercial standing lifts the priority.
SEGMENT_SCORES: dict[str, float] = {
    "enterprise": 1.0,
    "business": 0.7,
    "premium": 0.6,
    "consumer": 0.2,
    "standard": 0.2,
    "trial": 0.0,
}

OUTAGE_SCOPE_SCORES: dict[str, float] = {"single": 0.3, "local": 0.7, "regional": 1.0}

#: The weighted terms. The first six are v1's and the MVP's, kept in the same proportion to
#: each other because that ratio is the part that was actually calibrated.
#:
#: service_impact is new, and it fixes a real defect in the inherited equation. Those six
#: terms measure how heated a message is, not how much is broken, so a calm factual "my
#: router is broken" scored one out of ten while an irritable question about a bill scored
#: higher. Urgency and impact are different things and a queue needs both. The others were
#: scaled down proportionally to make room, so their relative weighting is unchanged.
WEIGHTS: dict[str, int] = {
    "sentiment": 20,
    "urgency_keywords": 15,
    "customer_segment": 10,
    "outage_scope": 15,
    "prior_contacts": 10,
    "sla_age": 10,
    "service_impact": 20,
}

#: What each term means in a sentence, for the screen that shows why a level was reached.
WEIGHT_REASONS: dict[str, str] = {
    "sentiment": "How upset the message reads.",
    "urgency_keywords": "The customer asked for this urgently.",
    "customer_segment": "What the account is worth to us.",
    "outage_scope": "How widely the fault reaches.",
    "prior_contacts": "They have contacted us about this before.",
    "sla_age": "How close the service level is to breach.",
    "service_impact": "They are reporting something that is not working.",
}


@dataclass
class ExtractedSignals:
    """What the words themselves say, before any record is read."""

    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    urgency_keywords: list[str] = field(default_factory=list)
    service_down: bool = False
    payment_related: bool = False
    repeat_contact: bool = False
    outage_scope: str = "single"
    error_codes: list[str] = field(default_factory=list)
    interrogative: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "urgency_keywords": self.urgency_keywords,
            "service_down": self.service_down,
            "payment_related": self.payment_related,
            "repeat_contact": self.repeat_contact,
            "outage_scope": self.outage_scope,
            "error_codes": self.error_codes,
        }


@dataclass
class TriageOutcome:
    """Where the ticket goes, how urgent it is, and why."""

    department: str
    level: int
    signals: ExtractedSignals
    reasons: list[dict[str, Any]]
    routed_by: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "department": self.department,
            "level": self.level,
            "routed_by": self.routed_by,
            "signals": self.signals.as_dict(),
            "reasons": self.reasons,
        }


def _hits(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in text]


def _sentiment(text: str) -> tuple[str, float]:
    """A nought to one anger scale.

    Typography carries as much heat as vocabulary. "no internet AGAIN!!" is a plain sentence
    by word count and an angry one by any other reading, so exclamation marks and shouting
    count alongside the lexicons.
    """
    lowered = text.lower()
    angry = len(_hits(lowered, ANGRY_TERMS))
    frustrated = len(_hits(lowered, FRUSTRATED_TERMS))
    satisfied = len(_hits(lowered, SATISFIED_TERMS))
    exclamations = min(text.count("!"), 4)
    shouting = min(sum(1 for word in text.split() if len(word) > 2 and word.isupper()), 4)

    raw = (
        angry * 0.35
        + frustrated * 0.20
        + exclamations * 0.12
        + shouting * 0.18
        - satisfied * 0.25
    )
    score = max(0.0, min(1.0, raw))

    if angry or score >= 0.6:
        label = "angry"
    elif frustrated or score >= 0.3:
        label = "frustrated"
    elif satisfied and score == 0.0:
        label = "satisfied"
    else:
        label = "neutral"
    return label, round(score, 3)


def _outage_scope(lowered: str) -> str:
    if _hits(lowered, REGIONAL_TERMS):
        return "regional"
    if _hits(lowered, LOCAL_TERMS):
        return "local"
    return "single"


def error_codes(text: str) -> list[str]:
    """Codes like ERR-503 or E102. Bare numbers and years are not codes."""
    found: list[str] = []
    for match in ERROR_CODE_RE.finditer(text):
        code = match.group(1)
        if code.isdigit() or code.upper() in found:
            continue
        found.append(code.upper())
    return found


def extract_signals(text: str) -> ExtractedSignals:
    lowered = text.lower()
    sentiment, score = _sentiment(text)
    return ExtractedSignals(
        sentiment=sentiment,
        sentiment_score=score,
        urgency_keywords=_hits(lowered, URGENCY_TERMS),
        service_down=bool(_hits(lowered, SERVICE_DOWN_TERMS)),
        payment_related=bool(_hits(lowered, PAYMENT_TERMS)),
        repeat_contact=bool(_hits(lowered, REPEAT_TERMS)),
        outage_scope=_outage_scope(lowered),
        error_codes=error_codes(text),
        interrogative="?" in text,
    )


def department_for(text: str, *, category: str | None = None) -> tuple[str, str]:
    """(department, how it was decided). The category the customer picked is the fallback.

    The text wins over the category because people pick the first plausible option on a form
    and then describe something else. Somebody who selects "Connection" and writes about a
    duplicate charge has told us twice, and the second telling is the reliable one.
    """
    lowered = text.lower()
    for department, keywords in ROUTING_RULES:
        if any(keyword in lowered for keyword in keywords):
            return department, "what they wrote"

    fallback = {
        "connection": "technical_support",
        "equipment": "technical_support",
        "billing": "billing",
        "plan": "sales",
        "other": "general",
    }.get(category or "", "general")
    return fallback, "the category they chose"


def _level_from_terms(contributions: dict[str, float]) -> int:
    """The six weighted terms onto one to ten.

    The weights total a hundred, so the weighted sum is already a percentage of the worst
    case. Mapping it so that nothing lands on one and everything lands on ten keeps both
    ends of the scale reachable, which a simple division by ten does not.
    """
    total = sum(WEIGHTS[name] * value for name, value in contributions.items())
    return max(1, min(10, 1 + round(total * 9 / 100)))


def triage(
    text: str,
    *,
    category: str | None = None,
    customer_segment: str = "consumer",
    sla_age_score: float = 0.0,
    repeat_contact: bool = False,
) -> TriageOutcome:
    """Route the ticket and set its priority, from the words plus what the account is worth."""
    signals = extract_signals(text)
    department, routed_by = department_for(text, category=category)

    contributions = {
        "sentiment": signals.sentiment_score,
        "urgency_keywords": 1.0 if signals.urgency_keywords else 0.0,
        "customer_segment": SEGMENT_SCORES.get(customer_segment.lower(), 0.2),
        "outage_scope": (
            OUTAGE_SCOPE_SCORES.get(signals.outage_scope, 0.3) if signals.service_down else 0.0
        ),
        "prior_contacts": 1.0 if (signals.repeat_contact or repeat_contact) else 0.0,
        "sla_age": sla_age_score,
        "service_impact": 1.0 if signals.service_down else 0.0,
    }

    level = _level_from_terms(contributions)
    reasons = [
        {
            "signal": name,
            "weight": WEIGHTS[name],
            "matched": value > 0,
            "detail": WEIGHT_REASONS[name],
        }
        for name, value in contributions.items()
        if value > 0
    ]

    return TriageOutcome(
        department=department,
        level=level,
        signals=signals,
        reasons=reasons,
        routed_by=routed_by,
    )
