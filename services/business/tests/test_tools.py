"""Ported from v2 tests/unit/test_orgdata_tools.py.

Runs entirely in memory: the deterministic seeder builds the world at a fixed sim instant and
the tools are pure functions over it, so no database is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.seed import SandboxSeeder, SeedClock
from app.tools import REGISTRY, available_tools, call
from app.world import build, resolve
from lanka_common.punctuation import contains_banned_dash

NOW = datetime(2026, 9, 11, 6, 30, tzinfo=timezone.utc)
PERSONAS = [f"SUB-10000{i}" for i in range(1, 9)]


@pytest.fixture(scope="module")
def env():
    seeder = SandboxSeeder(SeedClock(NOW))
    seeder.run(subscriber_count=24)
    return build(seeder.rows)


def run(env, name, ref="SUB-100001", **kw):
    world, snaps = env
    return call(name, resolve(snaps, ref), world, NOW, subscriber_ref=ref, **kw)


def test_every_tool_is_registered_with_a_group_and_a_description():
    assert len(available_tools()) == 18
    for name in available_tools():
        spec = REGISTRY[name]
        assert spec.group in ("identity", "commercial", "network", "history")
        assert len(spec.description) > 40, f"{name} needs a description a model can act on"


def test_unknown_tool_raises_but_a_missing_customer_does_not(env):
    with pytest.raises(KeyError):
        run(env, "get_something_invented")
    miss = run(env, "get_subscriber_profile", ref="NOT-A-CUSTOMER")
    assert miss["found"] is False and "error" in miss


@pytest.mark.parametrize("ref", PERSONAS)
def test_every_tool_answers_with_a_found_flag_for_every_persona(env, ref):
    world, snaps = env
    for name in available_tools():
        if name == "get_device_led_semantics":
            result = call(name, None, world, NOW, model="LL-ONT-2400")
        else:
            result = run(env, name, ref=ref)
        assert "found" in result, f"{name} returned no found flag for {ref}"
        assert not contains_banned_dash(str(result))


def test_money_and_data_ship_formatted_siblings(env):
    payment = run(env, "get_payment_status", ref="SUB-100002")
    assert payment["outstanding_balance_display"].startswith("LKR ")
    assert payment["outstanding_balance_display"] != str(payment["outstanding_balance"])
    usage = run(env, "get_usage_summary", ref="SUB-100003")
    assert usage["data_used_display"].endswith(("GB", "TB", "MB"))
    assert "of" in usage["allowance_display"]


def test_suspension_and_outage_are_computed_not_inferred(env):
    """The headline case: SUB-100002 is suspended AND in an outage."""
    payment = run(env, "get_payment_status", ref="SUB-100002")
    circuit = run(env, "get_circuit_status", ref="SUB-100002")
    outage = run(env, "get_active_outages_for", ref="SUB-100002")
    assert payment["suspended_for_nonpayment"] is True
    assert payment["service_resumes_on_payment"] is True
    assert circuit["line_down"] is True
    assert outage["in_active_outage"] is True
    assert outage["outage_explains_symptom"] is True


def test_a_healthy_customer_produces_no_cause_signals(env):
    assert run(env, "get_payment_status")["suspended_for_nonpayment"] is False
    assert run(env, "get_payment_status")["balance_settled"] is True
    assert run(env, "get_circuit_status")["service_live"] is True
    assert run(env, "get_active_outages_for")["outage_explains_symptom"] is False
    assert run(env, "get_line_quality")["line_healthy"] is True


def test_top_of_catalogue_is_stated(env):
    top = run(env, "get_plan_and_entitlements", ref="SUB-100005")
    assert top["at_top_of_catalogue"] is True and top["upgrade_options"] == []
    room = run(env, "get_plan_and_entitlements", ref="SUB-100004")
    assert room["upgrade_available"] is True and room["upgrade_options"]


def test_near_cap_is_distinguished_from_over_cap(env):
    near = run(env, "get_usage_summary", ref="SUB-100003")
    assert near["near_cap"] is True
    assert near["over_cap"] is False
    assert near["usage_explains_slow_speed"] is True


def test_congestion_is_distinguished_from_a_premises_fault(env):
    quality = run(env, "get_line_quality", ref="SUB-100007", hours=72)
    assert quality["line_healthy"] is True
    assert quality["evening_congestion"] is True
    assert quality["premises_fault_likely"] is False


def test_led_meaning_is_looked_up_per_model(env):
    world, _ = env
    result = call("get_device_led_semantics", None, world, NOW,
                  model="ZY-VMG-3625", led="internet", colour="amber", behaviour="solid")
    assert result["indicates_suspension"] is True
    assert call("get_device_led_semantics", None, world, NOW, model="NOPE")["found"] is False


def test_a_physical_fault_returns_repair_steps_and_the_socket_layout(env):
    world, _ = env
    result = call("get_device_led_semantics", None, world, NOW,
                  model="LL-ONT-2400", led="pon", colour="off", behaviour="off")
    assert "fault_cabling" in result["indicated_faults"]
    assert result["customer_can_self_serve"] is True
    assert len(result["repair_steps"]) >= 3 and result["escalate_if"]
    pon = next(p for p in result["port_layout"] if p["port"] == "PON")
    assert pon["colour"] == "green"
    assert "PON (green" in result["port_layout_display"]


def test_guidance_stays_out_of_a_ticket_it_cannot_help(env):
    world, _ = env
    barred = call("get_device_led_semantics", None, world, NOW,
                  model="LL-ONT-2400", led="internet", colour="amber", behaviour="solid")
    assert barred["port_layout"] == [] and barred["customer_can_self_serve"] is False
    unmatched = call("get_device_led_semantics", None, world, NOW,
                     model="LL-ONT-2400", led="usb", colour="purple")
    assert len(unmatched["all_indicators"]) > 4


def test_subscriber_resolves_by_any_identifier(env):
    by_id = run(env, "get_subscriber_profile")
    for key in ("msisdn", "email", "account_id"):
        again = run(env, "get_subscriber_profile", ref=str(by_id[key]))
        assert again["subscriber_id"] == "SUB-100001", f"resolution by {key} failed"
