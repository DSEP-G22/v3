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
