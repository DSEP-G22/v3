"""Numbers around the MT call.

A support reply that quotes the wrong balance or the wrong appointment time is worse than one
that quotes neither. NLLB keeps digits as written, so the text goes in unmasked (placeholders
came back as "0"), and any translated sentence that lost or changed a number is replaced by its
source sentence.
"""

from app.translate import _prepare, numbers_kept


def test_rupees_are_written_the_way_the_model_localises():
    assert _prepare("Your balance is LKR 8,450.00 today.") == "Your balance is Rs. 8,450.00 today."
    assert _prepare("LKR8450 due") == "Rs. 8450 due"
    assert _prepare("No numbers here at all.") == "No numbers here at all."


def test_a_translation_that_keeps_every_number_passes():
    assert numbers_kept("Wait 30 seconds, then 2 minutes.", "තත්පර 30ක් ඉන්න, පසුව විනාඩි 2ක්.")
    assert numbers_kept("Call at 7:30 pm about Rs. 1,758.20", "7.30 ට රු. 1,758.20 ගැන අමතන්න")
    assert numbers_kept("No numbers here at all.", "මෙහි අංක නැත.")


def test_a_lost_or_changed_number_fails():
    assert not numbers_kept("Wait 30 seconds.", "තත්පර 0ක් ඉන්න.")
    assert not numbers_kept("Pay Rs. 8,450.00", "රු. 8,500 ගෙවන්න")
    assert not numbers_kept("Wait 2 minutes.", "විනාඩි කිහිපයක් ඉන්න.")


def test_sinhala_conjuncts_are_rejoined():
    """NLLB returns "ප් රශ්න"; the letters belong together as "ප්‍රශ්න"."""
    from app.translate import fix_sinhala

    assert fix_sinhala("ප් රශ්න තියෙනවා") == "ප්‍රශ්න තියෙනවා"
    assert fix_sinhala("සංඛ් යාවක්") == "සංඛ්‍යාවක්"
    assert fix_sinhala("ක්රියාත්මක") == "ක්‍රියාත්මක"  # the same break without the space
    assert fix_sinhala("සාමාන් ය ගෙවීම්") == "සාමාන්‍ය ගෙවීම්"  # a bare "ය" is never a word


def test_two_words_are_never_run_together():
    """A word that ends in a virama is a whole word. Joining it to the next one changed the
    meaning of a real reply: "නමුත් රේඛාව" (but the line) came out as one nonsense word."""
    from app.translate import fix_sinhala

    for two_words in ("නමුත් රේඛාව", "පැත්තෙන් රේඛාව", "රූපයක් නොමැති", "රූපයක් රතුයි", "වැඩ කරන්නේ නැහැ"):
        assert fix_sinhala(two_words) == two_words


def test_a_step_number_is_not_treated_as_a_fact():
    """The model may drop or move "1." in a list; that must not force the English through."""
    assert numbers_kept("1. Unplug the router.", "திசைவியைத் துண்டிக்கவும்.")
    assert not numbers_kept("1. Wait 30 seconds.", "30 அல்ல, 40 வினாடிகள்.")
