"""Routing and level checks for the ported v2 rules, on machine-translated English."""

from app.rules import triage


def test_singlish_headline_routes_to_technical_support():
    # "mata internet eka wada karanne naha" after translation to English.
    out = triage("[CUSTOMER_TEXT] My internet is not working")
    assert out.department == "technical_support"
    assert out.signals.service_down is True
    assert out.level >= 4


def test_area_outage_outranks_equipment_and_bills_route_to_billing():
    assert triage("No internet in the whole area, my router is fine").department == "network_operations"
    assert triage("Why was I charged twice on this bill?").department == "billing"


def test_heat_and_segment_raise_the_level():
    calm = triage("My router is broken").level
    angry = triage("My router is broken AGAIN!! This is unacceptable, third time", customer_segment="enterprise").level
    assert 1 <= calm < angry <= 10
