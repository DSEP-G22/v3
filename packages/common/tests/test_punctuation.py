import json

from lanka_common.punctuation import contains_banned_dash, normalise, normalise_deep


def test_scrub_is_idempotent_and_json_safe():
    raw = f"Hi{chr(0x2014)}there {chr(0x201C)}ok{chr(0x201D)}{chr(0x2026)}"
    once = normalise(raw)
    assert once == normalise(once)
    assert not contains_banned_dash(once)
    payload = json.dumps({"a": raw})
    assert json.loads(json.dumps(normalise_deep(json.loads(payload))))["a"] == once


def test_markdown_never_reaches_the_customer():
    from lanka_common.punctuation import plain_text

    assert plain_text("**LKR 8,450.00** is due") == "LKR 8,450.00 is due"
    assert plain_text("**Next step:** pay `now`") == "Next step: pay now"
    assert plain_text("## Heading\nbody") == "Heading\nbody"
    assert plain_text("see [our plans](https://x.lk/plans)") == "see our plans"
    # Left alone: ordinary text, and a lone star or underscore in a word.
    assert plain_text("2 * 3 and snake_case stay") == "2 * 3 and snake_case stay"
    assert plain_text("රුපියල් 8,450.00") == "රුපියල් 8,450.00"
