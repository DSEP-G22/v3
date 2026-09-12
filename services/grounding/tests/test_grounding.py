"""Ported from v2 tests/unit/test_grounding.py and test_findings.py.

Facts are the business service's real tool payloads for the eight personas, dumped to
tests/fixtures/prefetch.json by `python -m app.fixtures` (the contract fixture), so these
run without a database or another service's code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import findings
from app.actions import filter_actions, load_registry, select
from app.assemble import build
from app.plan import TOOL_GROUPS, PlanResolver
from lanka_common.contracts import Completeness, Diagnosis, OrgFact, Payload, Triage

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "prefetch.json").read_text(encoding="utf-8"))
DEPARTMENTS = ("network_operations", "technical_support", "billing", "field_service", "retention", "sales", "general")
resolver = PlanResolver()
registry = load_registry()


def bundle(sub: str, department: str, fault: str | None = None, text: str = "my internet is not working", level: int = 5):
    payload = Payload(case_id="LL-1", revision=1, original_text=text, text_en=text, fused_text=f"[CUSTOMER_TEXT] {text}")
    return build(case_id="LL-1", revision=1, payload=payload, triage=Triage(department=department, base_level=level),
                 diagnosis=Diagnosis(fault=fault, confidence=0.8), sop_passages=[],
                 prefetch=FIXTURE["subscribers"][sub], extra={}, registry=registry, resolver=resolver)


def fact(tool: str, result: dict) -> OrgFact:
    return OrgFact(tool=tool, group=TOOL_GROUPS[tool], result={"found": True, **result})


class TestPlan:
    def test_connectivity_always_checks_billing(self):
        for d in ("network_operations", "technical_support"):
            assert "get_payment_status" in resolver.resolve(d).tools

    def test_every_service_department_checks_for_an_open_incident(self):
        for d in ("network_operations", "technical_support", "field_service"):
            assert "get_active_outages_for" in resolver.resolve(d).tools

    def test_every_department_reads_entitlements(self):
        for d in DEPARTMENTS:
            assert "get_plan_and_entitlements" in resolver.resolve(d).tools, d

    def test_a_fault_adds_without_reordering(self):
        base, more = resolver.resolve("billing"), resolver.resolve("billing", "fault_billing_dispute")
        assert more.tools[: len(base.tools)] == base.tools and "get_ledger_window" in more.tools

    def test_unknown_department_falls_back(self):
        assert "get_subscriber_profile" in resolver.resolve("nope").tools

    def test_every_planned_tool_exists(self):
        for d in DEPARTMENTS:
            for f in (None, "fault_billing_dispute", "fault_hardware", "fault_line_sync"):
                assert set(resolver.resolve(d, f).tools) <= set(TOOL_GROUPS)


class TestBundle:
    def test_facts_ordered_identity_commercial_network_history(self):
        b, _, _ = bundle("SUB-100002", "network_operations", "fault_service_suspended")
        ranks = [("identity", "commercial", "network", "history").index(f.group) for f in b.org_facts]
        assert ranks == sorted(ranks) and b.org_facts[0].group == "identity"

    def test_signals_name_the_tool_that_established_them(self):
        s = bundle("SUB-100002", "network_operations", "fault_service_suspended")[0].active_signals()
        assert s["suspended_for_nonpayment"] == "get_payment_status"
        assert s["outage_explains_symptom"] == "get_active_outages_for"

    def test_healthy_customer_has_no_alarming_signals(self):
        s = bundle("SUB-100001", "general", text="just checking in")[0].active_signals()
        assert not {"suspended_for_nonpayment", "outage_explains_symptom", "cpe_offline", "over_cap"} & set(s)

    def test_billing_completeness(self):
        b, plan, _ = bundle("SUB-100008", "billing", "fault_billing_dispute", text="charged twice for the router fee")
        assert set(plan.required_sections) == {"identity", "payment", "invoice"}
        assert b.completeness.sufficient and b.completeness.score == 1.0

    def test_missing_section_is_reported(self):
        gap = Completeness(required=["identity", "payment"], present=["identity"], missing=["payment"])
        assert not gap.sufficient and gap.score == 0.5

    def test_unplanned_prefetch_is_reported_as_unused_and_kept_out(self):
        b, plan, unused = bundle("SUB-100005", "sales")
        assert "get_line_quality" in unused
        assert b.fact("get_line_quality") is None

    def test_bundle_is_frozen(self):
        b = bundle("SUB-100001", "general")[0]
        with pytest.raises(Exception):
            b.case_id = "other"  # type: ignore[misc]


class TestActions:
    def test_withheld_without_entitlement(self):
        facts = [fact("get_plan_and_entitlements", {"granted_entitlement_codes": []}),
                 fact("get_cpe_diagnostics", {"cpe_offline": True})]
        assert "swap_cpe" not in {a.action_id for a in filter_actions(registry, "field_service", "fault_hardware", facts)}

    def test_entitlements_fail_open_when_never_fetched(self):
        facts = [fact("get_cpe_diagnostics", {"cpe_offline": True})]
        assert "swap_cpe" in {a.action_id for a in filter_actions(registry, "field_service", "fault_hardware", facts)}

    def test_fault_free_case_sees_only_its_own_department(self):
        ids = {a.action_id for a in filter_actions(registry, "sales", None, [])}
        assert ids <= {"change_plan"} and "restart_router" not in ids

    def test_futile_action_withheld(self):
        down = fact("get_circuit_status", {"line_down": True})
        off = filter_actions(registry, "technical_support", "fault_power_supply",
                             [down, fact("get_cpe_diagnostics", {"cpe_offline": True})])
        on = filter_actions(registry, "technical_support", "fault_power_supply",
                            [down, fact("get_cpe_diagnostics", {"cpe_offline": False})])
        assert "restart_router" not in {a.action_id for a in off}
        assert "restart_router" in {a.action_id for a in on}

    def test_action_needs_a_measurement_not_only_a_fault(self):
        healthy = [fact("get_line_quality", {"line_healthy": True})]
        faulty = [fact("get_circuit_status", {"line_down": True}), fact("get_line_quality", {"high_error_rate": True})]
        assert "run_line_diagnostic" not in {a.action_id for a in filter_actions(registry, "network_operations", "fault_line_sync", healthy)}
        assert "run_line_diagnostic" in {a.action_id for a in filter_actions(registry, "network_operations", "fault_line_sync", faulty)}

    def test_congestion_goes_to_the_network_team(self):
        b, _, _ = bundle("SUB-100007", "network_operations", "fault_intermittent_connection")
        assert b.active_signals().get("evening_congestion")
        assert select(b.permitted_actions, b.org_facts, b.case_id)["action_id"] == "escalate_to_noc"

    def test_no_router_restart_for_a_barred_line(self):
        b, _, _ = bundle("SUB-100002", "network_operations", "fault_service_suspended")
        rec = select(b.permitted_actions, b.org_facts, b.case_id)
        assert rec is None or rec["action_id"] != "restart_router"

    def test_actions_scoped_to_the_routed_department(self):
        """The assemble.py:400 fix: actions narrow on the same department the facts used."""
        b, _, _ = bundle("SUB-100004", "sales", None, text="I want more data")
        assert {a.action_id for a in b.permitted_actions} <= {"change_plan"}


class TestFindingsAndPriority:
    def test_barred_account_is_a_cause_with_the_amount(self):
        items = findings.summarise(bundle("SUB-100002", "technical_support", "fault_line_sync")[0])
        barred = next(i for i in items if i["signal"] == "suspended_for_nonpayment")
        assert barred["severity"] == "cause" and "LKR" in barred["detail"]

    def test_ranked_and_deduplicated(self):
        items = findings.summarise(bundle("SUB-100002", "technical_support", "fault_line_sync")[0])
        order = [findings.SEVERITY_ORDER.index(i["severity"]) for i in items]
        signals = {i["signal"] for i in items}
        assert order == sorted(order)
        assert not ("outage_explains_symptom" in signals and "in_active_outage" in signals)

    def test_headline_names_at_most_two_causes(self):
        assert findings.headline(bundle("SUB-100002", "technical_support")[0]).count(", and ") <= 1

    def test_priority_is_bounded_and_explains_itself(self):
        for sub in FIXTURE["subscribers"]:
            p = bundle(sub, "network_operations", "fault_line_sync", level=9)[0].priority
            assert 1 <= p.level <= 10 and p.reasons[0]["signal"] == "what they wrote"
            assert all(abs(r["move"]) <= 2 for r in p.reasons if r["signal"] not in ("clamped",))

    def test_enterprise_tier_now_counts(self):
        """v2's tier table named tiers the seed never uses, so this never fired."""
        p = bundle("SUB-100007", "network_operations", "fault_intermittent_connection")[0].priority
        assert any(r["signal"] == "sla_tier" and r["move"] == 2 for r in p.reasons)
