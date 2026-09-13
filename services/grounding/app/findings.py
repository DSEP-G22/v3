"""Causal booleans as sentences an agent reads, most consequential first. Ported from v2.

The console's "What we found" shows the top three. Tool names, latencies and payloads are
not here; they belong to the trace.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lanka_common.contracts import CUSTOMER_FAULTS, CUSTOMER_SIDE_SIGNALS, ContextBundle

SEVERITY_ORDER = ("cause", "risk", "context")


def _v(b: ContextBundle, tool: str, key: str, fallback: str) -> str:
    f = b.fact(tool)
    return str(f.result.get(key) or fallback) if f and f.found else fallback


def _outage(b: ContextBundle) -> str:
    f = b.fact("get_active_outages_for")
    if not f or not f.found:
        return "Engineers are working on it."
    eta, msg = f.result.get("primary_eta_display"), f.result.get("primary_message") or "Engineers are working on it."
    return f"{msg} Expected back {eta}." if eta else msg


RULES: tuple[tuple[str, str, Callable[[ContextBundle], tuple[str, str]]], ...] = (
    ("suspended_for_nonpayment", "cause", lambda b: (
        "The service is barred for non payment",
        f"{_v(b, 'get_payment_status', 'outstanding_balance_display', 'A balance')} is outstanding. "
        "Service resumes once it is settled.")),
    ("outage_explains_symptom", "cause", lambda b: ("An open outage covers this address", _outage(b))),
    ("in_active_outage", "cause", lambda b: ("The address is inside an open incident", _outage(b))),
    ("line_down", "cause", lambda b: ("The line has no carrier", "Our own equipment cannot see the connection.")),
    ("cpe_offline", "cause", lambda b: (
        "The router has not reported in",
        f"Last seen {_v(b, 'get_cpe_diagnostics', 'last_seen_display', 'some time ago')}.")),
    ("usage_explains_slow_speed", "cause", lambda b: (
        "They are over the fair use allowance",
        f"{_v(b, 'get_usage_summary', 'allowance_display', 'The allowance')} used, so the line is shaped "
        "rather than faulty.")),
    ("has_unusual_charge", "cause", lambda b: (
        "There is a charge on the bill that does not fit the pattern",
        f"{_v(b, 'get_last_invoice_breakdown', 'unusual_total_display', 'An amount')} is out of pattern.")),
    ("evening_congestion", "cause", lambda b: (
        "The area is congested in the evenings", "The line itself measures healthy, so a diagnostic will come back clean.")),
    ("signal_degraded", "risk", lambda b: (
        "Optical signal is outside its normal range", f"Measured {_v(b, 'get_line_quality', 'signal_display', 'below normal')}.")),
    ("high_error_rate", "risk", lambda b: ("The line is running a high error rate", "This usually precedes a drop out.")),
    ("near_cap", "risk", lambda b: (
        "Close to the data allowance", f"{_v(b, 'get_usage_summary', 'allowance_display', 'Most of it')} used.")),
    ("is_overdue", "risk", lambda b: (
        "The account is overdue",
        f"{_v(b, 'get_payment_status', 'outstanding_balance_display', 'A balance')} outstanding, still inside the grace period.")),
    ("contract_in_notice_period", "risk", lambda b: ("The contract is inside its notice period", "They can leave without a fee.")),
    ("visit_already_booked", "context", lambda b: ("An engineer is already booked", "Do not offer another appointment.")),
    ("work_in_progress_now", "context", lambda b: ("Planned work is running at this address", "It was notified in advance.")),
    ("known_issue_applies", "context", lambda b: ("A known issue covers this", "There is a published answer for it.")),
    ("upgrade_available", "context", lambda b: ("A faster plan is available", "Only offer it if they ask.")),
    ("at_top_of_catalogue", "context", lambda b: ("Already on the fastest plan", "There is nothing to upgrade to.")),
    ("is_long_standing_customer", "context", lambda b: (
        "A long standing customer", f"With us {_v(b, 'get_subscriber_profile', 'tenure_years_display', 'for years')}.")),
)

#: A stronger finding hides the weaker one that says the same thing.
SUPERSEDES: dict[str, tuple[str, ...]] = {
    "outage_explains_symptom": ("in_active_outage",),
    "suspended_for_nonpayment": ("is_overdue",),
    "usage_explains_slow_speed": ("near_cap",),
}


def summarise(bundle: ContextBundle) -> list[dict[str, Any]]:
    """Findings, each tagged with its side. Within a severity the customer's own side comes
    first: the draft answers what they reported before what our records add."""
    active = bundle.active_signals()
    hidden = {w for s, weaker in SUPERSEDES.items() if s in active for w in weaker}
    out = []
    if (d := bundle.diagnosis) and d.fault in CUSTOMER_FAULTS:
        words = CUSTOMER_FAULTS[d.fault]
        out.append({"signal": d.fault, "severity": "cause", "side": "customer",
                    "headline": "They report a problem with their own equipment",
                    "detail": words[0].upper() + words[1:] + "."})
    for signal, severity, phrase in RULES:
        if signal in active and signal not in hidden:
            headline, detail = phrase(bundle)
            out.append({"signal": signal, "severity": severity, "headline": headline, "detail": detail,
                        "side": "customer" if signal in CUSTOMER_SIDE_SIGNALS else "provider"})
    return sorted(out, key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["side"] != "customer"))


def headline(bundle: ContextBundle) -> str:
    causes = [f for f in summarise(bundle) if f["severity"] == "cause"]
    if not causes:
        return "Nothing in the record explains this. Read what they wrote."
    if len(causes) == 1:
        return causes[0]["headline"] + "."
    return f"{causes[0]['headline']}, and {causes[1]['headline'].lower()}."
