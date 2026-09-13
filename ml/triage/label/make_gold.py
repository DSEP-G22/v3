"""Carve a 150-record human-review slice out of the labelled corpus.

The slice is stratified over urgency and department so a reviewer sees the rare bands, not
150 routine billing questions, and it is held out of training: scoring the distilled model
against labels it trained on measures memorisation, not accuracy.

    python TriageModel/label/make_gold.py                  # -> data/gold.jsonl
    python TriageModel/label/make_gold.py --review         # print the slice for reading
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import _paths  # noqa: F401  (sets sys.path)

from common import GOLD, LABELLED, SEED, read_jsonl  # noqa: E402

from schema import UnifiedTicket  # noqa: E402


def select(tickets: list[UnifiedTicket], size: int, seed: int = SEED) -> list[UnifiedTicket]:
    """Stratify over (urgency, department) so rare combinations survive into the slice."""
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[UnifiedTicket]] = defaultdict(list)
    for ticket in tickets:
        assert ticket.triage is not None
        buckets[(ticket.triage.urgency.value, ticket.triage.department.value)].append(ticket)

    for bucket in buckets.values():
        rng.shuffle(bucket)

    # Round-robin across buckets: every combination contributes before any contributes twice.
    chosen: list[UnifiedTicket] = []
    keys = sorted(buckets)
    position = 0
    while len(chosen) < size and any(buckets[key] for key in keys):
        key = keys[position % len(keys)]
        if buckets[key]:
            chosen.append(buckets[key].pop())
        position += 1

    return chosen[:size]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(LABELLED))
    parser.add_argument("--output", default=str(GOLD))
    parser.add_argument("--size", type=int, default=150)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--review", action="store_true", help="print the slice for reading")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        print(f"missing: {source} (run run_labelling.py first)")
        return 1

    tickets = [UnifiedTicket.model_validate(row) for row in read_jsonl(source)]
    labelled = [t for t in tickets if t.triage is not None]
    if not labelled:
        print("no labelled records to sample from")
        return 1

    slice_ = select(labelled, args.size, args.seed)
    gold_ids = {t.ticket_id for t in slice_}

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for ticket in slice_:
            ticket.metadata = {**ticket.metadata, "gold": True, "human_reviewed": False}
            handle.write(json.dumps(ticket.model_dump(mode="json"), ensure_ascii=False) + "\n")

    # The training file must not contain the gold rows, or the score is meaningless.
    train_path = output.with_name("train.jsonl")
    with train_path.open("w", encoding="utf-8") as handle:
        kept = 0
        for ticket in labelled:
            if ticket.ticket_id in gold_ids:
                continue
            handle.write(json.dumps(ticket.model_dump(mode="json"), ensure_ascii=False) + "\n")
            kept += 1

    bands = Counter(t.triage.urgency.value for t in slice_)
    departments = Counter(t.triage.department.value for t in slice_)

    print(f"gold slice:  {len(slice_)} records -> {output.name}")
    print(f"train split: {kept} records -> {train_path.name}")
    print(f"urgency:     {dict(bands)}")
    print(f"department:  {dict(departments)}")
    print(
        "\nThe slice is written with human_reviewed=false. Read it, correct what is wrong, "
        "and flip the flag ,  an unreviewed gold set is just more teacher output."
    )

    if args.review:
        print("\n" + "=" * 78)
        for ticket in slice_:
            print(f"\n{ticket.ticket_id}  [{ticket.triage.urgency.value}] "
                  f"{ticket.triage.department.value} / {ticket.triage.intent} "
                  f"({ticket.triage.priority_score})")
            print(f"  {' '.join(ticket.request.text.split())[:200]}")
            print(f"  rationale: {ticket.triage.rationale}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
