"""Synthetic telecom requests, to give the corpus something escalatable.

Bitext is an e-commerce taxonomy: it has no outage, no line fault, no dead service and no
safety hazard, so a corpus built from it alone cannot produce a `high` or `critical` label no
matter how good the teacher is. This module supplies the missing half of the urgency range.

Every record is marked `metadata.source="synthetic_telecom"` with its `template_id`, so any
score can be reported per source and nobody can mistake generated text for real traffic. The
templates deliberately carry NO triage label -- they shape the wording, and the labelling pass
still assigns intent, department, urgency and priority score. A template that shipped its own
band would make the dataset circular.

Vocabulary is lifted from `MVP/knowledge/sop_*.md` so the synthetic text uses the same terms
the SOPs and the RAG index cover.

    python TriageModel/extract/extract_synthetic.py --count 700
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from dataclasses import dataclass

from common import SEED


@dataclass(frozen=True)
class SyntheticRequest:
    template_id: str
    text: str
    device_relevant: bool     # whether a photograph of the hardware would plausibly be attached


SLOTS: dict[str, tuple[str, ...]] = {
    "hours": ("since 6am", "since yesterday evening", "for the last four hours",
              "since Friday night", "for two days now", "since about 11pm",
              "since the storm on Tuesday", "since early this morning"),
    # Phrased to hit `pipeline.signals.LOCAL_TERMS` / `REGIONAL_TERMS`, so the rule prefill
    # produces a sensible `outage_scope` hint. The teacher can still override it.
    "place": ("our whole street", "our whole building", "my neighbourhood",
              "all our offices", "the whole block", "everyone in my area",
              "my neighbours and me", "the whole area"),
    "area": ("this street", "the block", "my area", "the estate", "the village"),
    "device": ("router", "modem", "ONT", "fibre box", "home hub", "wall box"),
    # Every option must read grammatically after a leading "The " -- the templates use it
    # that way, so an option like "no LEDs are lit" would produce "The no LEDs are lit".
    "led": ("power LED is solid red", "internet LED is amber and never turns green",
            "internet LED is completely off", "power LED blinks red and it keeps rebooting",
            "power LED is completely dark", "internet LED flashes and then goes out"),
    "code": ("ERR-503", "E102", "WAN-0x21", "SYNC-14", "ERR 900", "E-455"),
    "amount": ("49.90", "112.40", "27.00", "230.15", "18.75", "64.20", "89.99"),
    "days": ("three days", "a week", "ten days", "two weeks", "nearly a month"),
    "count": ("twice", "three times", "four times"),
    "nth": ("second time", "third time", "fourth time"),
    "plan": ("100 Mbps fibre plan", "500 Mbps plan", "business fibre line", "ADSL plan",
             "family broadband bundle"),
    "speed": ("3 Mbps", "just under 8 Mbps", "less than 1 Mbps", "about 12 Mbps"),
}

# Openers and closers, applied independently at random. Without them 700 records collapse
# into ~26 sentences with the nouns swapped, and the encoder would see the template rather
# than the complaint. The empty entries keep plenty of records bare.
OPENERS: tuple[str, ...] = (
    # Each ends a sentence, so the template's own capital letter still starts one.
    "", "", "", "Hello. ", "Hi there. ", "Good morning. ", "Please help. ",
    "Sorry to bother you. ", "I need some help. ", "URGENT: ",
)
CLOSERS: tuple[str, ...] = (
    "", "", "", " Please advise.", " Can someone call me back today?",
    " I would appreciate a quick reply.", " What can you do about this?",
    " Please let me know what happens next.", " Thanks.",
)

# (template_id, device_relevant, text)
#
# Coverage is deliberate: outages and hazards for the top of the band, single-line faults and
# repeat contacts for the middle, disputes and routine questions for the bottom. Do not prune
# the routine ones -- a corpus of nothing but emergencies teaches the opposite bias.
TEMPLATES: tuple[tuple[str, bool, str], ...] = (
    # --- wide-scope outages ------------------------------------------------------------ #
    ("outage_area", False,
     "There has been no internet {hours} for {place}. Nobody here can get online at all."),
    ("outage_area_business", False,
     "The line has been down for {place} {hours}. We run a business from these premises and "
     "cannot take card payments while it is out."),
    ("outage_repeat", False,
     "The connection has gone down across {place} {count} this week. It is down again now, "
     "{hours}. I have already reported it and nothing has changed."),
    ("outage_phone_and_net", False,
     "Both the internet and the phone line are dead {hours} for {place}. There is no dial "
     "tone at all."),
    # --- safety / on-site --------------------------------------------------------------- #
    ("hazard_cable", False,
     "The drop cable from the pole to my house has come down and is lying across the "
     "pavement where children walk. Service has been out {hours}."),
    ("hazard_burning", True,
     "My {device} started smelling of burning and there are scorch marks on the casing. I "
     "have unplugged it at the wall. Nothing is working now."),
    ("hazard_box_open", False,
     "The street cabinet on my corner has been left open with the cables exposed since the "
     "engineers were here. Half of {area} lost service afterwards."),
    # --- single-line hard faults --------------------------------------------------------- #
    ("dead_line", True,
     "My {device} has been dead {hours}. The {led}. I have power-cycled it twice and it "
     "makes no difference."),
    ("dead_line_repeat", True,
     "I have called {count} about this and nobody has called back. The {led} and I have had "
     "no service for {days}."),
    ("no_sync", True,
     "The {led} on my {device}. I reseated the WAN cable at both ends as your support page "
     "says and it still will not sync."),
    ("error_code", True,
     "My {device} shows {code} on the status page and there is no connection. It has been "
     "like this {hours}."),
    ("wfh_blocked", False,
     "I work from home and have had no connection {hours}. I have missed two client calls "
     "already and I have a deadline today."),
    # --- degraded but working ------------------------------------------------------------ #
    ("intermittent", True,
     "The connection keeps dropping every few minutes and comes back on its own. It has "
     "been doing this for {days}. The {led} when it drops."),
    ("slow_speed", False,
     "I pay for the {plan} but I am only getting {speed} on a wired connection at any time "
     "of day. Can you check the line?"),
    ("wifi_range", True,
     "The wifi does not reach the back of the house since you replaced my {device}. The "
     "connection itself works fine next to the box."),
    ("evening_drops", False,
     "Every evening between 7 and 10 the connection becomes unusable, then it is fine again "
     "in the morning. This has happened for {days}."),
    # --- billing -------------------------------------------------------------------------- #
    ("double_charge", False,
     "I have been charged {amount} twice this month for the same {plan}. Please refund the "
     "duplicate payment."),
    ("unknown_debit", False,
     "There is a direct debit of {amount} on my account that I did not authorise. I want it "
     "cancelled and explained."),
    ("bill_after_cancel", False,
     "I cancelled {days} ago and you have billed me {amount} again. This is the {nth} this "
     "has happened."),
    ("charged_while_down", False,
     "You have billed me the full {amount} for a month in which the service was out for "
     "{days}. I want that period credited."),
    # --- churn / complaint ---------------------------------------------------------------- #
    ("cancel_threat", False,
     "This is the {nth} I have had to contact you about the same fault. If it is not fixed "
     "today I am cancelling the {plan} and moving to another provider."),
    ("regulator", False,
     "I have had no working service for {days} and no engineer has been sent. I am filing a "
     "formal complaint with the regulator unless someone contacts me today."),
    # --- routine (keeps the low band populated) -------------------------------------------- #
    ("routine_upgrade", False,
     "Could you tell me what it would cost to move from my current {plan} to a faster one? "
     "No rush, just planning ahead."),
    ("routine_appointment", False,
     "I have an engineer visit booked for next week. Could you confirm the time window and "
     "whether I need to be home for it?"),
    ("routine_move", False,
     "I am moving house in {days} and would like to take my {plan} with me. What is the "
     "process?"),
    ("routine_password", True,
     "I would like to change the wifi password on my {device}. Where do I find the current "
     "one?"),
)


def _fill(text: str, rng: random.Random) -> str:
    """Fill every `{slot}` from SLOTS. An unknown slot is a typo in a template, not input."""
    out = text
    for name, options in SLOTS.items():
        token = "{" + name + "}"
        while token in out:
            out = out.replace(token, rng.choice(options), 1)
    if "{" in out:
        raise KeyError(f"unfilled slot in template: {out}")
    return out


def extract(count: int = 700, seed: int = SEED) -> list[SyntheticRequest]:
    """`count` requests spread evenly over the template bank, deterministic under `seed`."""
    rng = random.Random(seed)
    records: list[SyntheticRequest] = []
    for index in range(count):
        template_id, device_relevant, text = TEMPLATES[index % len(TEMPLATES)]
        body = rng.choice(OPENERS) + _fill(text, rng) + rng.choice(CLOSERS)
        records.append(
            SyntheticRequest(
                template_id=template_id,
                text=body,
                device_relevant=device_relevant,
            )
        )
    rng.shuffle(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=700)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--show", type=int, default=5, help="print N filled examples")
    args = parser.parse_args()

    records = extract(args.count, args.seed)
    counts = Counter(r.template_id for r in records)
    print(f"synthetic requests: {len(records)} from {len(TEMPLATES)} templates")
    print(f"per template: min {min(counts.values())}, max {max(counts.values())}")
    print(f"device-relevant: {sum(1 for r in records if r.device_relevant)}")
    unique = len({r.text for r in records})
    print(f"unique texts: {unique} ({100 * unique / len(records):.1f}%)")
    for record in records[: args.show]:
        print(f"\n[{record.template_id}] {record.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
