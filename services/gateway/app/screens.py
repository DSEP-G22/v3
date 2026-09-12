"""Shaping tool results into screens. Ported from v2 services/bff/app.py.

Customers get sentences, never scores, SNR, CRC or internal ids they did not ask for.
"""

from __future__ import annotations

from typing import Any

OVERVIEW_TOOLS = ["get_subscriber_profile", "get_payment_status", "get_circuit_status",
                  "get_active_outages_for", "get_plan_and_entitlements", "get_usage_summary"]
BILLING_TOOLS = ["get_payment_status", "get_account_balance", "get_billing_history", "get_last_invoice_breakdown"]
USAGE_TOOLS = ["get_usage_summary", "get_line_quality", "get_circuit_status"]


def service_summary(circuit: dict[str, Any], outages: dict[str, Any]) -> dict[str, Any]:
    """One sentence about the line. An open outage is read first: it explains a dead line."""
    incidents = (outages or {}).get("incidents") or []
    if incidents:
        first = incidents[0]
        return {"state": "outage", "headline": "We have a fault in your area",
                "detail": first.get("customer_message") or "Engineers are working on it now.",
                "expected": first.get("eta_display")}
    if not (circuit or {}).get("found"):
        return {"state": "unknown", "headline": "We cannot read your line right now",
                "detail": "This is on our side. Your service may still be working."}
    if circuit.get("suspended_at_network_level"):
        return {"state": "suspended", "headline": "Your service is paused",
                "detail": "This is about the account, not the line. Paying the balance brings it back."}
    if circuit.get("line_state") == "syncing":
        return {"state": "setting_up", "headline": "Your line is being set up",
                "detail": "This usually takes a few minutes."}
    if circuit.get("line_down"):
        return {"state": "down", "headline": "Your line is not connecting",
                "detail": "We can see it from our side and we are looking into it."}
    if circuit.get("line_shaped"):
        return {"state": "shaped", "headline": "Your speed is reduced for the rest of this cycle",
                "detail": "You have used this month's allowance."}
    if circuit.get("upstream_equipment_degraded") or circuit.get("uplink_congested"):
        return {"state": "busy", "headline": "Your area is busy right now",
                "detail": "The line is up, but speeds may dip at peak times."}
    return {"state": "up", "headline": "Your service is running normally",
            "detail": circuit.get("provisioned_speed_display") or ""}


def billing_summary(payment: dict[str, Any]) -> dict[str, Any]:
    if not (payment or {}).get("found"):
        return {"state": "unknown", "headline": "We could not read your balance"}
    owed = payment.get("outstanding_balance_display") or "LKR 0.00"
    if payment.get("suspended_for_nonpayment"):
        state, headline = "suspended", f"{owed} to pay to restore service"
    elif payment.get("is_overdue"):
        state, headline = "overdue", f"{owed} is overdue"
    elif (payment.get("outstanding_balance") or 0) > 0:
        state, headline = "due", f"{owed} due"
    else:
        state, headline = "clear", "Nothing to pay"
    return {"state": state, "headline": headline, "outstanding_display": owed,
            "due_display": payment.get("oldest_due_date_display"),
            "last_payment_display": payment.get("last_payment_at_display"),
            "autopay": bool(payment.get("autopay_enabled"))}


def plan_summary(plan: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    if not (plan or {}).get("found"):
        return {"found": False}
    usage = usage or {}
    pct = usage.get("used_percent_display")
    try:
        used_fraction = min(1.0, float(pct.rstrip("%")) / 100) if pct and pct.endswith("%") else None
    except ValueError:
        used_fraction = None
    return {"found": True, "name": plan.get("plan_name"), "code": plan.get("plan_code"),
            "speed_display": plan.get("download_speed_display"), "price_display": plan.get("monthly_price_display"),
            "allowance_display": usage.get("allowance_display"), "used_fraction": used_fraction,
            "unlimited": bool(usage.get("is_uncapped")), "days_left": usage.get("days_left_in_cycle"),
            "renews_display": plan.get("renewal_date_display"), "upgrade_options": plan.get("upgrade_options", [])}


def health_sentence(quality: dict[str, Any]) -> str:
    """One plain sentence about connection health. No numbers a customer did not ask for."""
    if not (quality or {}).get("found") or quality.get("no_telemetry"):
        return "We do not have enough readings from your line yet."
    if quality.get("line_dead_in_window"):
        return "Your line dropped out at times in the last two days."
    if quality.get("evening_congestion"):
        return "Your line is healthy, but it slows down in the evenings when the area is busy."
    if quality.get("line_healthy"):
        return "Your connection has been steady over the last two days."
    return "Your connection has been less steady than usual. We are keeping an eye on it."
