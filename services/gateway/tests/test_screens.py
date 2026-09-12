from app.screens import billing_summary, health_sentence, service_summary

UP = {"found": True, "line_state": "up", "line_down": False, "suspended_at_network_level": False}


def test_outage_explains_before_suspension():
    circuit = {**UP, "line_down": True, "suspended_at_network_level": True}
    outages = {"incidents": [{"customer_message": "Repairing a cable.", "eta_display": "Sat 2:00 pm"}]}
    assert service_summary(circuit, outages)["state"] == "outage"
    assert service_summary(circuit, {})["state"] == "suspended"


def test_states_in_plain_words():
    assert service_summary({**UP, "line_state": "syncing"}, {})["state"] == "setting_up"
    assert service_summary(UP, {})["headline"] == "Your service is running normally"
    assert service_summary({"found": False}, {})["state"] == "unknown"


def test_billing_and_health_never_leak_numbers_beyond_money():
    assert billing_summary({"found": True, "outstanding_balance": 0})["state"] == "clear"
    s = billing_summary({"found": True, "suspended_for_nonpayment": True, "outstanding_balance_display": "LKR 9.00"})
    assert s["state"] == "suspended" and "LKR 9.00" in s["headline"]
    sentence = health_sentence({"found": True, "line_healthy": True, "evening_congestion": True})
    assert "evening" in sentence and "dB" not in sentence
