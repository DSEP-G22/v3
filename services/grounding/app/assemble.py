"""Building the ContextBundle, the only place one is ever constructed. Ported from v2.

v3 differences:
- Facts come from the prefetch the orchestrator ran in parallel with translation and ASR,
  filtered to the plan: no extra I/O on the hot path. Prefetched facts the plan did not ask
  for are reported back as unused and never reach the bundle.
- The department is the v2/v3 routing everywhere, including action filtering. (v2 passed
  v1's triage department to filter_actions at assemble.py:400, so actions were narrowed for
  a different department than the facts were fetched for.)
- LED meaning is looked up for the device model in the CPE fact, with the colour the image
  service saw, so a light is read on the customer's actual hardware.
"""

from __future__ import annotations

from typing import Any

from app import actions as action_policy
from app import priority as priority_policy
from app.plan import FetchPlan, PlanResolver
from lanka_common.contracts import (
    FACT_GROUP_ORDER,
    ActionEntry,
    Completeness,
    ContextBundle,
    Diagnosis,
    OrgFact,
    Payload,
    SlaPosition,
    SopPassage,
    Triage,
)

#: A lit colour that explains a complaint outranks a healthy green.
_LED_RANK = {"off": 0, "red": 1, "amber": 2, "blue": 3, "green": 4}


def led_query(payload: Payload, cpe: dict[str, Any] | None) -> dict[str, Any] | None:
    """(model, colour) for get_device_led_semantics, or None when there is nothing to read."""
    model = next((v.device_model for v in payload.visual_summaries if v.device_model), None)
    model = model or (cpe or {}).get("model")
    leds = [led for v in payload.visual_summaries for led in v.led_states]
    if not model or not leds:
        return None
    best = min(leds, key=lambda led: _LED_RANK.get(led.colour, 9))
    return {"model": model, "colour": best.colour}


def facts_from_prefetch(plan: FetchPlan, prefetch: dict[str, dict[str, Any]],
                        extra: dict[str, dict[str, Any]]) -> tuple[list[OrgFact], list[str]]:
    """Planned facts in group order (stable within a group), and the unused prefetched tools."""
    facts = []
    for tool in plan.tools:
        if tool in extra:
            result, prefetched = extra[tool], False
        elif tool in prefetch:
            result, prefetched = prefetch[tool], True
        else:
            result, prefetched = {"found": False, "error": "This fact was not fetched."}, False
        facts.append(OrgFact(tool=tool, group=plan.group_of(tool), result=result, ok="error" not in result or
                             result.get("found") is False, prefetched=prefetched))
    order = {g: i for i, g in enumerate(FACT_GROUP_ORDER)}
    facts.sort(key=lambda f: (order[f.group], plan.tools.index(f.tool)))
    unused = sorted(set(prefetch) - set(plan.tools))
    return facts, unused


def completeness(plan: FetchPlan, facts: list[OrgFact], payload: Payload,
                 diagnosis: Diagnosis | None) -> Completeness:
    found = {f.tool for f in facts if f.found}
    present, missing = [], []
    for section in plan.required_sections:
        candidates = plan.section_tools.get(section, ())
        if not candidates or found.intersection(candidates):
            present.append(section)
        else:
            missing.append(section)
    degraded = [f"tool {f.tool}" for f in facts if not f.ok]
    flags = list(payload.flags)
    if payload.partial:
        degraded.append("evidence")
        flags.append("partial_payload")
    if diagnosis is None:
        degraded.append("diagnosis")
    elif diagnosis.needs_human_diagnosis:
        degraded.append("diagnosis confidence")
    if any(t.low_confidence for t in payload.transcripts):
        degraded.append("transcript confidence")
        flags.append("low_asr_confidence")
    return Completeness(required=list(plan.required_sections), present=present, missing=missing,
                        degraded=sorted(set(degraded)), flags=sorted(set(flags)))


def sla_from(r: dict[str, Any] | None) -> SlaPosition:
    """SLA is case metadata (priority, the held notice), not an LLM fact, so it is read from
    the prefetch whether or not the department's plan shows it to the model. v2 only read it
    when planned, so network cases never saw their enterprise tier."""
    if not r or not r.get("found"):
        return SlaPosition()
    return SlaPosition(tier=str(r.get("tier", "standard")), tier_display=str(r.get("tier_display", "Standard care")),
                       minutes_remaining=r.get("minutes_remaining"), response_due_display=r.get("response_due_display"),
                       breached=bool(r.get("sla_breached")), at_risk=bool(r.get("sla_at_risk")))


def build(*, case_id: str, revision: int, payload: Payload, triage: Triage, diagnosis: Diagnosis | None,
          sop_passages: list[SopPassage], prefetch: dict[str, dict[str, Any]], extra: dict[str, dict[str, Any]],
          registry: list[ActionEntry], resolver: PlanResolver, build_ms: int = 0,
          ) -> tuple[ContextBundle, FetchPlan, list[str]]:
    department = triage.department
    plan = resolver.resolve(department, diagnosis.fault if diagnosis else None)
    if extra.get("get_device_led_semantics") and "get_device_led_semantics" not in plan.tools:
        plan = FetchPlan(plan.department, plan.fault, (*plan.tools, "get_device_led_semantics"),
                         plan.required_sections, plan.section_tools)
    facts, unused = facts_from_prefetch(plan, prefetch, extra)
    done = completeness(plan, facts, payload, diagnosis)
    sla = sla_from(prefetch.get("get_sla_position"))
    base_reason = f"Sent to {department.replace('_', ' ')} because of what they wrote ({triage.routed_by or 'rules'})."
    bundle = ContextBundle(
        case_id=case_id, revision=revision, build_ms=build_ms, payload=payload, department=department,
        triage=triage, diagnosis=diagnosis, sop_passages=sop_passages, org_facts=facts, sla=sla,
        permitted_actions=action_policy.filter_actions(registry, department, plan.fault, facts),
        completeness=done,
        priority=priority_policy.assign(triage.base_level, base_reason, facts, sla, done),
        customer_priority=priority_policy.customer(triage),
        provider_priority=priority_policy.provider(facts, sla),
    )
    return bundle, plan, unused
