"""Priority 1 to 10: triage's base level from the words, moved by what the record says.
Ported from v2 grounding/priority.py.

Bounded: no single signal moves it by more than two, and it never leaves 1..10. Two v2 bugs
fixed here: it looked for a "repeat_contact" signal no tool produces (the tool emits
is_repeat_contact), and its tier table named tiers the seed never uses, so it never fired.
"""

from __future__ import annotations

from typing import Any

from lanka_common.contracts import Completeness, OrgFact, Priority, SlaPosition, band_for

SIGNAL_ADJUSTMENTS: tuple[tuple[str, int, str], ...] = (
    ("in_active_outage", 2, "The address is inside an open outage."),
    ("outage_explains_symptom", 1, "The open outage explains what the customer reported."),
    ("line_down", 2, "The line has no carrier."),
    ("cpe_offline", 1, "The router has not reported in."),
    ("line_dead_in_window", 1, "The line measured dead during the reported window."),
    ("signal_degraded", 1, "Optical signal is outside its normal range."),
    ("high_error_rate", 1, "The line is running a high error rate."),
    ("is_repeat_contact", 1, "The customer has contacted us about this before."),
    ("suspended_for_nonpayment", -1, "The service is suspended for non payment."),
    ("has_unusual_charge", 1, "There is a charge on the bill that does not fit the pattern."),
    ("visit_already_booked", -2, "An engineer is already booked to attend."),
    ("work_in_progress_now", -1, "Planned work covers this address and was notified."),
    ("known_issue_applies", -1, "A known issue already covers this, with a published answer."),
)
#: SLA tiers as seeded (config/orgdata_seed.yaml).
TIER_ADJUSTMENTS: dict[str, int] = {"enterprise": 2, "priority": 1, "standard": 0, "basic": 0}
MAX_SINGLE_MOVE = 2


def assign(base_level: int, base_reason: str, facts: list[OrgFact], sla: SlaPosition,
           completeness: Completeness) -> Priority:
    level = base_level
    reasons: list[dict[str, Any]] = [{"signal": "what they wrote", "move": 0, "detail": base_reason}]
    active = {n for f in facts for n, v in f.signals().items() if v}
    for name, move, detail in SIGNAL_ADJUSTMENTS:
        if name in active:
            capped = max(-MAX_SINGLE_MOVE, min(MAX_SINGLE_MOVE, move))
            level += capped
            reasons.append({"signal": name, "move": capped, "detail": detail})
    if tier := TIER_ADJUSTMENTS.get(sla.tier, 0):
        level += tier
        reasons.append({"signal": "sla_tier", "move": tier, "detail": f"The account is on {sla.tier_display}."})
    if sla.breached:
        level += 2
        reasons.append({"signal": "sla_breached", "move": 2, "detail": "The first response target has already passed."})
    elif sla.at_risk:
        level += 1
        reasons.append({"signal": "sla_at_risk", "move": 1, "detail": sla.display})
    if not completeness.sufficient:
        level -= 1
        reasons.append({"signal": "incomplete_grounding", "move": -1,
                        "detail": "Part of the record could not be read, so a person has to look."})
    final = max(1, min(10, level))
    if final != level:
        reasons.append({"signal": "clamped", "move": final - level, "detail": f"Held inside the one to ten scale at {final}."})
    return Priority(level=final, band=band_for(final), base_level=base_level, reasons=reasons)
