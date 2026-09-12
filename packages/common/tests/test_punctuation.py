import json

from lanka_common.punctuation import contains_banned_dash, normalise, normalise_deep


def test_scrub_is_idempotent_and_json_safe():
    raw = f"Hi{chr(0x2014)}there {chr(0x201C)}ok{chr(0x201D)}{chr(0x2026)}"
    once = normalise(raw)
    assert once == normalise(once)
    assert not contains_banned_dash(once)
    payload = json.dumps({"a": raw})
    assert json.loads(json.dumps(normalise_deep(json.loads(payload))))["a"] == once
