"""Priority 1 to 10: triage's base level from the words, moved by what the record says.
Ported from v2 grounding/priority.py.

Bounded: no single signal moves it by more than two, and it never leaves 1..10. Two v2 bugs
fixed here: it looked for a "repeat_contact" signal no tool produces (the tool emits
is_repeat_contact), and its tier table named tiers the seed never uses, so it never fired.
"""

from __future__ import annotations

from typing import Any

from lanka_common.contracts import Completeness, OrgFact, Priority, SlaPosition, Triage, band_for

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


# -- the two separate priorities ------------------------------------------------------------------

#: Service provider side: what our own records say is wrong on our side. Rules only, and the
#: worst finding sets the level, so a single outage is not diluted by a clean bill.
PROVIDER_RULES: tuple[tuple[str, int, str], ...] = (
    ("outage_explains_symptom", 8, "An open outage on our network explains what they reported."),
    ("in_active_outage", 6, "Their address is inside an open incident."),
    ("line_down", 6, "Our equipment cannot see their line."),
    ("suspended_for_nonpayment", 5, "The service is barred for an unpaid balance."),
    ("has_unusual_charge", 5, "There is an out of pattern charge on the latest bill."),
    ("work_in_progress_now", 4, "Planned maintenance is running at their address."),
    ("evening_congestion", 4, "Shared equipment in their area is congested in the evenings."),
    ("signal_degraded", 4, "The line signal is outside its normal range."),
    ("high_error_rate", 4, "The line is running a high error rate."),
    ("is_overdue", 3, "The account is overdue."),
    ("usage_explains_slow_speed", 3, "They are past the fair use allowance, so the line is shaped."),
    ("contract_in_notice_period", 2, "The contract is inside its notice period."),
)


def provider(facts: list[OrgFact], sla: SlaPosition) -> Priority:
    active = {n for f in facts for n, v in f.signals().items() if v}
    hits = [(level, name, detail) for name, level, detail in PROVIDER_RULES if name in active]
    level = max((h[0] for h in hits), default=1)
    reasons = [{"signal": name, "move": 0, "detail": detail} for _, name, detail in hits] or [
        {"signal": "nothing_on_our_side", "move": 0, "detail": "Nothing in our records is wrong on our side."}]
    if tier := TIER_ADJUSTMENTS.get(sla.tier, 0):
        level += tier
        reasons.append({"signal": "sla_tier", "move": tier, "detail": f"The account is on {sla.tier_display}."})
    if sla.breached:
        level += 2
        reasons.append({"signal": "sla_breached", "move": 2, "detail": "The first response target has already passed."})
    elif sla.at_risk:
        level += 1
        reasons.append({"signal": "sla_at_risk", "move": 1, "detail": sla.display})
    final = max(1, min(10, level))
    return Priority(level=final, band=band_for(final), base_level=max((h[0] for h in hits), default=1),
                    reasons=reasons, side="provider", source="rules")


def customer(triage: Triage) -> Priority:
    """The request itself, as the TriageModel read it. The rules level stands in without it."""
    cp = triage.customer_priority
    if not cp or cp.get("level") is None:
        return Priority(level=triage.base_level, band=band_for(triage.base_level), base_level=triage.base_level,
                        side="customer", source="rules",
                        reasons=[{"signal": "rules", "move": 0, "detail": "Scored by the triage rules."}])
    level = max(1, min(10, int(cp["level"])))
    lead = (f"The triage model reads this as {cp.get('band', band_for(level))} urgency"
            + (f", {float(cp['confidence']):.0%} sure." if cp.get("confidence") is not None else "."))
    return Priority(level=level, band=band_for(level), base_level=level, side="customer",
                    source=str(cp.get("source", "model")), score=cp.get("score"),
                    reasons=[{"signal": "model", "move": 0, "detail": lead}, *cp.get("reasons", [])])


def queue(customer_side: Priority, provider_side: Priority) -> int:
    """The case's place in the queue: the more urgent of the two sides."""
    return max(customer_side.level, provider_side.level)
