"""Number and reference protection around the MT call.

NLLB rewrites digits: an amount comes back rounded, reformatted, or with the
grouping separator moved. A support reply that quotes the wrong balance or the
wrong appointment time is worse than one that quotes neither, so every run that
has to survive translation byte-identical is masked out and put back afterwards.
"""

from app.translate import _protect, _restore

CASES = [
    "Your outstanding balance is LKR 8,450.00 and it is due on 09 Sep.",
    "We measured 42.5 Mbps against your 100 Mbps plan.",
    "An engineer will call 077 123 4567 at 2:30 pm about LL-8KQ2X.",
    "Write to help@lankalink.lk or see https://lankalink.lk/status for updates.",
    "No numbers here at all.",
]


def test_protected_runs_survive_a_round_trip_exactly():
    for text in CASES:
        masked, mapping = _protect(text)
        assert _restore(masked, mapping) == text


def test_the_money_amount_is_hidden_from_the_model():
    masked, mapping = _protect("Your balance is LKR 8,450.00 today.")
    assert "8,450.00" not in masked
    assert mapping
    assert "LKR 8,450.00" in mapping.values()


def test_a_placeholder_mangled_by_the_model_is_still_recovered():
    """The model sometimes puts a space inside the placeholder or moves it.

    Leaking a raw placeholder to a customer is the one outcome worse than a
    slightly reworded sentence, so the restore step is tolerant.
    """
    masked, mapping = _protect("The balance is LKR 8,450.00 now.")
    token = next(iter(mapping))
    damaged = masked.replace(token, f"{token[0]} {token[1:-1]} {token[-1]}")
    restored = _restore(damaged, mapping)
    assert "LKR 8,450.00" in restored
    assert token[0] not in restored


def test_text_with_nothing_to_protect_is_unchanged():
    masked, mapping = _protect("No numbers here at all.")
    assert masked == "No numbers here at all."
    assert mapping == {}
