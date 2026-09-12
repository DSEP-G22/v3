"""ContextBundle to prompt text. Ported from v2 grounding/render.py.

Confirmed causes come first and in plain language, display fields only (a raw number is a
number the model can quote), facts grouped identity, commercial, network, history.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lanka_common.contracts import FACT_GROUP_ORDER, ContextBundle, OrgFact
from lanka_common.punctuation import normalise

CONFIG_DIR = Path(os.environ.get("LANKA_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")
OPERATOR_NAME = "Lanka Link"
TEMPLATE = (CONFIG_DIR / "prompts" / "draft.txt").read_text(encoding="utf-8")

CAUSE_LANGUAGE: dict[str, str] = {
    "suspended_for_nonpayment": "The service is barred because of an unpaid balance. This is the reason the line "
                                "is not working. Restarting equipment will not restore it.",
    "service_resumes_on_payment": "Service resumes automatically once the outstanding balance is paid.",
    "outage_explains_symptom": "An incident on shared network equipment is affecting this customer right now, and "
                               "it explains the loss of service. Do not offer troubleshooting steps for it.",
    "in_active_outage": "There is an open incident affecting this customer's area.",
    "work_in_progress_now": "Scheduled maintenance is running in this customer's area at the moment.",
    "cpe_offline": "The router at the premises has not reported in to the network, which points at the equipment "
                   "rather than the line.",
    "reboot_loop_suspected": "The equipment has restarted an unusual number of times this week.",
    "firmware_behind": "The equipment is running firmware older than the current release.",
    "known_issue_applies": "There is a documented known issue affecting this equipment model.",
    "evening_congestion": "The line itself measures healthy. The slowdown is congestion on shared equipment in the "
                          "evenings, not a fault at the premises. An engineer visit would not help.",
    "premises_fault_likely": "The measurements point at a fault at or near the premises.",
    "signal_degraded": "The optical or line signal is measurably outside its normal range.",
    "high_error_rate": "The line is logging an abnormal number of errors.",
    "over_cap": "The customer has used their entire data allowance for this cycle.",
    "near_cap": "The customer is close to their data allowance and speeds may be shaped.",
    "usage_explains_slow_speed": "Usage past the fair use threshold explains the reduced speed. This is policy, not a fault.",
    "has_unusual_charge": "The latest invoice carries a charge that has been flagged as unusual.",
    "bill_increased": "This month's bill is higher than the previous one.",
    "at_top_of_catalogue": "This customer is already on the fastest plan available. There is no upgrade to offer. "
                           "Say so plainly rather than inventing one.",
    "contract_in_notice_period": "The contract ends within thirty days.",
    "visit_already_booked": "An engineer visit is already booked. Do not offer to arrange one, confirm the existing appointment.",
    "engineer_on_the_way": "An engineer is already dispatched or on site.",
    "is_frequent_contact": "This customer has contacted us three or more times in the last thirty days. Do not repeat "
                           "first line advice that has already failed.",
    "has_recurring_fault": "The same fault has been raised more than once before.",
    "sla_breached": "The service level target for a first response has already passed.",
    "payment_failed_recently": "A payment attempt failed in the last thirty days.",
    "line_down": "The line is currently not carrying service.",
}

_RAW_SUFFIXES = ("_gb", "_lkr", "_pct", "_mbps")
_RAW_FIELDS = {"outstanding_balance", "data_used_gb", "total", "amount", "minutes_remaining", "used_percent",
               "repair_steps", "escalate_if", "port_layout", "port_layout_display"}


def _readable(result: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in result.items():
        if k in ("found", "error", "reference") or isinstance(v, bool) or k in _RAW_FIELDS or k.endswith(_RAW_SUFFIXES):
            continue
        if v in (None, "", []) or (isinstance(v, (int, float)) and not k.endswith(("_count", "_total", "_left"))):
            continue
        out[k] = v[:4] + [f"and {len(v) - 4} more"] if isinstance(v, list) and len(v) > 4 else v
    return out


def render_fact(f: OrgFact) -> str:
    if not f.ok or not f.found:
        return f"  {f.tool}: {f.result.get('error', 'no record found')}"
    lines = [f"  {f.tool}:"]
    for k, v in _readable(f.result).items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"    {k}:")
            lines += [f"      - {', '.join(f'{a} {b}' for a, b in e.items() if b not in (None, '', [], False))}"
                      for e in v[:4] if isinstance(e, dict)]
        elif isinstance(v, list):
            lines.append(f"    {k}: {', '.join(str(x) for x in v)}")
        else:
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def render_org_facts(b: ContextBundle) -> str:
    heads = {"identity": "WHO THIS CUSTOMER IS", "commercial": "THEIR COMMERCIAL POSITION",
             "network": "THE STATE OF THEIR SERVICE", "history": "THEIR HISTORY WITH US"}
    blocks = []
    for g in FACT_GROUP_ORDER:
        if facts := b.facts_in_group(g):
            blocks += [heads[g], *(render_fact(f) for f in facts), ""]
    return "\n".join(blocks).rstrip() or "  No organisational data was retrieved."


def render_causes(b: ContextBundle) -> str:
    lines = [f"  - {CAUSE_LANGUAGE[n]} (established by {t})" for n, t in sorted(b.active_signals().items())
             if n in CAUSE_LANGUAGE]
    return "\n".join(lines) or "  Nothing in the operator records explains this on its own. Diagnose from the evidence."


def render_evidence(b: ContextBundle) -> str:
    p = b.payload
    lines = []
    if p.language not in ("en", "und"):
        lines += [f"  Written message, in {p.language}:", f"    what they wrote: {p.original_text}"]
        if p.native_text and p.native_text != p.original_text:
            lines.append(f"    in native script: {p.native_text}")
        lines.append(f"    translated: {p.text_en}")
    elif p.original_text:
        lines.append(f"  Written message: {p.original_text}")
    for t in p.transcripts:
        lines.append(f"  Voice message ({t.language}): {t.text}" + (f"\n    translated: {t.text_en}" if t.text_en != t.text else ""))
        if t.low_confidence:
            lines.append("    caution: the recording was hard to hear, so treat the wording as approximate")
    for v in p.visual_summaries:
        lines.append(f"  Image analysis: {v.summary_text}")
    return "\n".join(lines) or f"  {p.fused_text}"


def render_device_guidance(b: ContextBundle) -> str:
    f = b.fact("get_device_led_semantics")
    if f is None or not f.found:
        return "  No device image was supplied."
    r = f.result
    steps, ports = r.get("repair_steps") or [], r.get("port_layout") or []
    if not steps and not ports:
        return "  No device image was supplied."
    lines = [f"  Device: {r.get('model')} ({r.get('kind_display')})"]
    if r.get("primary_meaning"):
        lines.append(f"  What the light means: {r['primary_meaning']}")
    if ports:
        lines += ["  Sockets on the unit, left to right:"] + [
            f"    - {p.get('port')}, {p.get('colour')}, {p.get('position')}: {p.get('accepts')}" for p in ports]
    if steps:
        lines += ["  Steps the customer can safely follow, in this order:"] + [f"    {i}. {s}" for i, s in enumerate(steps, 1)]
    if r.get("escalate_if"):
        lines.append(f"  Book an engineer instead if: {r['escalate_if']}")
    return "\n".join(lines)


def render_actions(b: ContextBundle) -> str:
    if not b.permitted_actions:
        return "  None. Do not offer to take any automated action on this account."
    return "\n".join(f"  - {a.action_id}" + (", requires supervisor approval" if a.requires_supervisor else "")
                     for a in b.permitted_actions)


def render_completeness(b: ContextBundle) -> str:
    c = b.completeness
    if c.sufficient and not c.degraded:
        return "  Everything needed to answer this is present."
    parts = []
    if c.missing:
        parts.append(f"  Missing: {', '.join(c.missing)}. Do not answer as though you have this information.")
    if c.degraded:
        parts.append(f"  Degraded: {', '.join(c.degraded)}.")
    return "\n".join(parts)


def _hints(b: ContextBundle) -> str:
    """Machine readable block the offline stub reads and a real model ignores."""
    def get(tool: str, key: str) -> Any:
        f = b.fact(tool)
        return f.result.get(key) if f and f.found else None

    hints = {
        "preferred_name": get("get_subscriber_profile", "preferred_name"),
        "signals": sorted(b.active_signals()),
        "outstanding_balance_display": get("get_payment_status", "outstanding_balance_display"),
        "primary_eta_display": get("get_active_outages_for", "primary_eta_display"),
        "allowance_display": get("get_usage_summary", "allowance_display"),
        "unusual_total_display": get("get_last_invoice_breakdown", "unusual_total_display"),
        "next_appointment_display": get("get_open_work_orders", "next_appointment_display"),
    }
    return f"<!--grounding-hints {json.dumps({k: v for k, v in hints.items() if v}, ensure_ascii=False)} -->"


def render_prompt(b: ContextBundle, template: str = TEMPLATE) -> str:
    d = b.diagnosis
    return normalise(template.format(
        operator_name=OPERATOR_NAME, ticket_ref=b.case_id, department=b.department.replace("_", " ").capitalize(),
        priority_band=b.priority.band, priority_level=b.priority.level, sentiment=b.triage.sentiment,
        sla_display=b.sla.display, fault=(d.fault if d and d.fault else "not identified"),
        confidence=(f"{d.confidence:.2f}" if d else "not available"),
        rationale=(d.rationale if d else "no diagnosis was produced"), evidence=render_evidence(b),
        confirmed_causes=render_causes(b), org_facts=render_org_facts(b), device_guidance=render_device_guidance(b),
        procedures="\n".join(f"  [{s.chunk_id}] {s.text.strip()}" for s in b.sop_passages)
        or "  No procedure passage was retrieved for this case.",
        permitted_actions=render_actions(b), completeness=render_completeness(b), hints=_hints(b),
    ))
