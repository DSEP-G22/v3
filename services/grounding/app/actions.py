"""The action registry, what may be offered, and which one to recommend. Ported from v2
grounding/actions.py and assemble.filter_actions.

Narrowing happens against the customer's real entitlement rows and the measured signals,
so everything left is something the operator can deliver to this customer. Parameters come
from org facts, never from a model: an action with an invented amount is worse than none.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from lanka_common.contracts import ActionEntry, OrgFact

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")

#: Facts that make an action pointless (restarting a router that is not on the network).
ACTION_BLOCKERS: dict[str, tuple[str, ...]] = {
    "restart_router": ("cpe_offline", "suspended_for_nonpayment", "outage_explains_symptom"),
    "push_cpe_firmware": ("cpe_offline",),
    "reprovision_circuit": ("outage_explains_symptom",),
    "run_line_diagnostic": ("suspended_for_nonpayment", "outage_explains_symptom", "evening_congestion"),
    "schedule_technician_visit": ("visit_already_booked", "outage_explains_symptom", "suspended_for_nonpayment"),
    "swap_cpe": ("visit_already_booked", "outage_explains_symptom", "suspended_for_nonpayment"),
    "change_plan": ("at_top_of_catalogue",),
}

#: Measurements an action needs before it may be offered (a diagnosis is only a prediction).
ACTION_REQUIRES: dict[str, tuple[str, ...]] = {
    "restart_router": ("line_down", "speed_below_provisioned", "high_error_rate"),
    "run_line_diagnostic": ("line_down", "line_dead_in_window", "signal_degraded", "high_error_rate",
                            "speed_below_provisioned"),
    "reprovision_circuit": ("line_down", "suspended_at_network_level", "no_telemetry"),
    "escalate_to_noc": ("evening_congestion", "uplink_congested", "upstream_equipment_degraded", "in_active_outage"),
    "push_cpe_firmware": ("firmware_behind", "reboot_loop_suspected", "known_issue_applies"),
    "swap_cpe": ("cpe_offline", "reboot_loop_suspected", "known_issue_applies"),
    "schedule_technician_visit": ("premises_fault_likely", "cpe_offline", "signal_degraded", "high_error_rate",
                                  "line_dead_in_window"),
    "apply_outage_credit": ("outage_qualifies_for_credit",),
    "waive_late_fee": ("is_overdue", "suspended_for_nonpayment"),
    "issue_billing_credit": ("has_unusual_charge",),
    "change_plan": ("upgrade_available",),
    "pause_contract": ("contract_in_notice_period",),
}


def load_registry(doc: dict[str, Any] | None = None) -> list[ActionEntry]:
    if doc is None:
        path = CONFIG_DIR / "action_registry.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [
        ActionEntry(
            action_id=a["action_id"], department=a.get("department"),
            description=(a.get("description") or "").strip(), mapped_faults=list(a.get("mapped_faults") or []),
            requires_fields=list(a.get("requires_fields") or []),
            impact_limits={k: float(v) for k, v in (a.get("impact_limits") or {}).items()},
            requires_entitlement=a.get("requires_entitlement"),
            requires_supervisor=bool(a.get("requires_supervisor", False)), enabled=bool(a.get("enabled", True)),
        )
        for a in (doc or {}).get("actions", [])
    ]


def filter_actions(registry: list[ActionEntry], department: str, fault: str | None,
                   facts: list[OrgFact]) -> list[ActionEntry]:
    """Enabled, in scope, entitled, not futile, and supported by a measurement.

    Entitlements fail open when never fetched and closed when fetched and absent: those are
    different states, and conflating them silently withheld every gated action.
    """
    ent = next((f for f in facts if f.tool == "get_plan_and_entitlements"), None)
    known = bool(ent and ent.found)
    granted = set(ent.result.get("granted_entitlement_codes") or []) if known else set()
    signals = {n for f in facts for n, v in f.signals().items() if v}

    allowed = []
    for entry in registry:
        if not entry.enabled:
            continue
        if entry.mapped_faults:
            if not fault or fault not in entry.mapped_faults:
                continue
        elif entry.department not in (department, None):
            continue
        if entry.requires_entitlement and known and entry.requires_entitlement not in granted:
            continue
        if signals.intersection(ACTION_BLOCKERS.get(entry.action_id, ())):
            continue
        needs = ACTION_REQUIRES.get(entry.action_id)
        if needs and not signals.intersection(needs):
            continue
        allowed.append(entry)
    return allowed


def _money(display: str) -> float:
    digits = "".join(ch for ch in display if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


def derive_parameters(facts: dict[str, OrgFact], case_id: str, action_id: str) -> dict[str, Any]:
    def res(tool: str) -> dict[str, Any]:
        f = facts.get(tool)
        return f.result if f and f.found else {}

    profile, circuit, cpe = res("get_subscriber_profile"), res("get_circuit_status"), res("get_cpe_diagnostics")
    outage, invoice, plan = res("get_active_outages_for"), res("get_last_invoice_breakdown"), res("get_plan_and_entitlements")
    slots, payment = res("get_next_appointment_slots"), res("get_payment_status")
    p: dict[str, Any] = {
        "case_id": case_id, "circuit_id": circuit.get("circuit_id"), "device_serial": cpe.get("serial"),
        "target_firmware": cpe.get("latest_firmware"), "replacement_model": cpe.get("replacement_model"),
        "subscription_id": profile.get("subscription_id"), "account_id": profile.get("account_id"),
        "invoice_no": invoice.get("invoice_no"),
    }
    if action_id == "apply_outage_credit":
        incident = next((i for i in outage.get("incidents") or [] if i.get("credit_policy")), None)
        if incident:
            p["incident_id"] = incident.get("incident_id")
            for e in plan.get("entitlements") or []:
                if e.get("code") == "OUTAGE_CREDIT" and e.get("limit_display"):
                    p["amount_lkr"] = _money(e["limit_display"])
    if action_id == "waive_late_fee" and payment:
        p["amount_lkr"] = min(float(payment.get("outstanding_balance") or 0.0), 2500.0)
    if action_id == "issue_billing_credit" and invoice.get("unusual_charges"):
        p["amount_lkr"] = _money(invoice["unusual_charges"][0].get("amount_display", ""))
        p["reason_code"] = "duplicate_charge"
    if action_id == "schedule_technician_visit" and slots.get("slots"):
        p["slot_id"] = slots["slots"][0].get("slot_id")
    if action_id == "change_plan" and plan.get("upgrade_options"):
        p["target_plan_code"] = plan["upgrade_options"][0].get("plan_code")
    if action_id == "pause_contract":
        p["months"] = 3
    return {k: v for k, v in p.items() if v is not None}


def select(permitted: list[ActionEntry], facts: list[OrgFact], case_id: str) -> dict[str, Any] | None:
    """The first permitted action whose parameters can all be filled, in registry order."""
    by_tool = {f.tool: f for f in facts}
    for entry in permitted:
        params = derive_parameters(by_tool, case_id, entry.action_id)
        if entry.permits(params):
            return {"action_id": entry.action_id, "description": entry.description, "parameters": params,
                    "requires_supervisor": entry.requires_supervisor}
    return None
