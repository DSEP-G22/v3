"""Compliance (v1 policy/compliance.py plus v2's additions) and the auto-reply release rule
(v2 policy/release.py). Pure functions: every rule is testable without a model or a DB.

Compliance runs per sentence while the reply streams, so one bad sentence stops the stream
before it reaches a customer; then once more over the whole draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lanka_common.contracts import ContextBundle
from lanka_common.punctuation import contains_banned_dash

DRAFT_MAX_CHARS = 1400

_REFUND_PROMISE = re.compile(
    r"\b(we will|we'll|you will receive|you'll get)\b[^.]{0,40}\b(refund|credit|compensation)\b", re.I)
_GUARANTEE = re.compile(r"\b(guarantee(d)?|100%|never fail|always works|no matter what)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|dear|good (morning|afternoon|evening))\b", re.I)
# A phone is ten or more digits standing alone: an incident id (INC-2026-0418) or a date is not one.
_PII = ((re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "email"), (re.compile(r"(?<![\w-])\+?(?:\d[\s-]?){9,13}\d(?![\w-])"), "phone"),
        (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "card"), (re.compile(r"\b\d{9}[vVxX]\b|\b\d{12}\b"), "nic"))

_OFFER_VERBS = ("arrange", "arranging", "book", "booking", "schedule", "scheduling", "send you", "send an",
                "send a", "dispatch", "we will apply", "we will issue", "we will credit", "i will apply",
                "i will issue", "i will arrange", "i will book")
_OFFER_SUBJECTS = {
    "schedule_technician_visit": ("engineer", "technician", "site visit"),
    "swap_cpe": ("replacement router", "new router", "replacement unit", "swap"),
    "issue_billing_credit": ("credit", "refund", "goodwill"),
    "apply_outage_credit": ("service credit", "outage credit"),
    "waive_late_fee": ("waive", "late fee"),
}

CONSEQUENTIAL_ACTIONS = frozenset({"apply_outage_credit", "waive_late_fee", "issue_billing_credit",
                                   "schedule_technician_visit", "swap_cpe", "change_plan", "pause_contract",
                                   "reprovision_circuit"})


def check_sentence(text: str, permitted: set[str]) -> list[dict[str, Any]]:
    """Rules that can fail on one sentence. Any finding here holds the reply."""
    f: list[dict[str, Any]] = []
    if _REFUND_PROMISE.search(text):
        f.append({"rule": "no_refund_promise", "severity": "error", "message": "Promises a refund or credit."})
    if _GUARANTEE.search(text):
        f.append({"rule": "no_absolute_guarantee", "severity": "error", "message": "Makes an absolute guarantee."})
    for pattern, label in _PII:
        if pattern.search(text):
            f.append({"rule": "no_pii_echo", "severity": "error", "message": f"Echoes what looks like a {label}."})
    if contains_banned_dash(text):
        f.append({"rule": "no_em_dash", "severity": "error", "message": "Contains a banned dash."})
    low = text.lower()
    for action, subjects in _OFFER_SUBJECTS.items():
        if action in permitted:
            continue
        for s in subjects:
            pos = low.find(s)
            if pos != -1 and any(v in low[max(0, pos - 60): pos] for v in _OFFER_VERBS):
                f.append({"rule": f"unpermitted_{action}", "severity": "error",
                          "message": f"Offers {s}, which this customer is not permitted."})
                break
    return f


def check_draft(text: str, bundle: ContextBundle) -> list[dict[str, Any]]:
    permitted = {a.action_id for a in bundle.permitted_actions}
    f = check_sentence(text, permitted)
    if not _GREETING.match(text.strip()):
        f.append({"rule": "requires_greeting", "severity": "low", "message": "Missing an opening greeting."})
    if len(text) > DRAFT_MAX_CHARS:
        f.append({"rule": "length", "severity": "low", "message": f"{len(text)} characters, over the guideline."})
    return f


DEFAULT_POLICY: dict[str, Any] = {"enabled": False, "min_completeness": 1.0, "max_priority_level": 3,
                                  "require_clean_compliance": True, "allow_with_action": False}


@dataclass
class Decision:
    auto: bool
    reasons: list[str] = field(default_factory=list)


def eligibility(policy: dict[str, Any], department: str, level: int, completeness: float,
                action: str | None, refused: bool) -> Decision:
    """Everything decidable before drafting. Fails closed: a fresh install releases nothing."""
    reasons = []
    if refused:
        reasons.append("No reply was drafted, so there is nothing to release.")
    if not policy.get("enabled"):
        reasons.append(f"Auto reply is switched off for {department.replace('_', ' ')}.")
    if completeness < float(policy.get("min_completeness", 1.0)):
        reasons.append(f"Grounding is {completeness:.0%} complete, below the "
                       f"{float(policy.get('min_completeness', 1.0)):.0%} this department requires.")
    if level > int(policy.get("max_priority_level", 3)):
        reasons.append(f"Priority {level} is above the ceiling of {policy.get('max_priority_level', 3)} "
                       "for unattended replies.")
    if action in CONSEQUENTIAL_ACTIONS and not policy.get("allow_with_action"):
        reasons.append(f"The reply offers {action.replace('_', ' ')}, which is not released without approval.")
    return Decision(not reasons, reasons)


def finalise(pre: Decision, policy: dict[str, Any], findings: list[dict[str, Any]]) -> Decision:
    reasons = list(pre.reasons)
    if policy.get("require_clean_compliance", True) and any(f["severity"] == "error" for f in findings):
        reasons.append("The compliance check raised something that needs a person.")
    return Decision(not reasons, reasons)


if __name__ == "__main__":
    fresh = eligibility(DEFAULT_POLICY, "billing", 2, 1.0, None, False)
    assert not fresh.auto and "switched off" in fresh.reasons[0]
    on = {**DEFAULT_POLICY, "enabled": True}
    assert eligibility(on, "billing", 2, 1.0, None, False).auto
    assert not eligibility(on, "billing", 8, 1.0, None, False).auto
    assert not eligibility(on, "billing", 2, 1.0, "swap_cpe", False).auto
    assert eligibility({**on, "allow_with_action": True}, "billing", 2, 1.0, "swap_cpe", False).auto
    multi = eligibility(on, "billing", 9, 0.4, None, True)
    assert len(multi.reasons) >= 3
    assert check_sentence("We guarantee it will never fail.", set())
    assert check_sentence("I will arrange an engineer for you.", set())
    assert not check_sentence("I will arrange an engineer for you.", {"schedule_technician_visit"})
    assert not check_sentence("Our engineers are working on it.", set())
    assert not check_sentence("Incident INC-2026-0418 started on 2026-09-20.", set())
    assert check_sentence("Call us on 077 123 4567.", set()) and check_sentence("Or +94 77 123 4567.", set())
    print("policy ok")
