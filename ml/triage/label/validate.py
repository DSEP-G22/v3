"""Validate the corpus before and after labelling.

    python TriageModel/label/validate.py --dry     # schema conformance, before spending tokens
    python TriageModel/label/validate.py           # full report on labelled.jsonl

`--dry` is the cheap gate: it checks the unlabelled corpus validates against `schema.json`
and that the prompt renders for every record, so a malformed corpus fails in seconds rather
than halfway through a paid run.

The self-agreement number is the important one. It is the ceiling on the distilled model:
a student cannot be more consistent than its teacher, so if agreement is below 0.80 the
prompt is the thing to fix, not the model.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import _paths  # noqa: F401  (sets sys.path)

import prompt as prompt_module  # noqa: E402
from common import GOLD, LABELLED, UNLABELLED, read_jsonl  # noqa: E402

from schema import (  # noqa: E402
    Department,
    PriorityBand,
    TriageSource,
    UnifiedTicket,
    validate_ticket,
)

# Intent -> plausible departments. A label outside this map is not automatically wrong (the
# text can justify it), but a high rate of them means the taxonomy and the routing disagree.
INTENT_DEPARTMENTS: dict[str, set[Department]] = {
    "get_invoice": {Department.billing},
    "check_invoice": {Department.billing},
    "payment_issue": {Department.billing},
    "get_refund": {Department.billing},
    "track_refund": {Department.billing},
    "check_refund_policy": {Department.billing},
    "check_payment_methods": {Department.billing},
    "check_cancellation_fee": {Department.billing, Department.retention},
    "cancel_order": {Department.sales, Department.retention},
    "change_order": {Department.sales},
    "place_order": {Department.sales},
    "track_order": {Department.sales},
    "delivery_options": {Department.sales},
    "delivery_period": {Department.sales},
    "change_shipping_address": {Department.sales},
    "set_up_shipping_address": {Department.sales},
    "delete_account": {Department.retention, Department.technical_support},
    "complaint": {Department.retention, Department.general},
    "create_account": {Department.technical_support},
    "edit_account": {Department.technical_support},
    "switch_account": {Department.technical_support},
    "recover_password": {Department.technical_support},
    "registration_problems": {Department.technical_support},
    "newsletter_subscription": {Department.general},
    "review": {Department.general},
    "contact_customer_service": {Department.general},
    "contact_human_agent": {Department.general},
}

BAND_RANGES = {
    PriorityBand.critical: (80, 100),
    PriorityBand.high: (60, 79),
    PriorityBand.normal: (35, 59),
    PriorityBand.low: (0, 34),
}


def _load(path: Path) -> list[UnifiedTicket]:
    return [UnifiedTicket.model_validate(row) for row in read_jsonl(path)]


def _percent(count: int, total: int) -> str:
    return f"{count:>5}  ({100 * count / total:5.1f}%)" if total else "    0"


def dry_run(path: Path) -> int:
    """Cheap pre-flight: does every record validate, and does the prompt render for it?"""
    print(f",  dry run over {path.name} , \n")
    if not path.exists():
        print(f"missing: {path}")
        return 1

    tickets = _load(path)
    problems: list[str] = []
    for ticket in tickets:
        try:
            validate_ticket(ticket)
        except Exception as exc:
            problems.append(f"{ticket.ticket_id}: {exc}")
        if ticket.triage is not None:
            problems.append(f"{ticket.ticket_id}: already has a triage label")

    rendered = 0
    for ticket in tickets:
        try:
            messages = prompt_module.build_messages(ticket)
            assert messages[-1]["content"].strip()
            rendered += 1
        except Exception as exc:
            problems.append(f"{ticket.ticket_id}: prompt render failed: {exc}")

    modalities = Counter(t.request.modality.value for t in tickets)
    with_images = sum(1 for t in tickets if t.images)
    characters = sum(len(prompt_module.user_message(t)) for t in tickets)

    print(f"records:            {len(tickets)}")
    print(f"schema valid:       {len(tickets) - len(problems)}")
    print(f"prompt renders:     {rendered}")
    print(f"modalities:         {dict(modalities)}")
    print(f"with image evidence:{with_images:>5}")
    print(f"prompt characters:  {characters:,} (~{characters // 4:,} tokens of ticket text)")

    if problems:
        print(f"\n{len(problems)} problems:")
        for line in problems[:20]:
            print(f"  {line}")
        return 1

    print("\nOK ,  safe to spend tokens.")
    return 0


def report(path: Path, repeat_path: Path | None, gold_path: Path | None) -> int:
    print(f",  report over {path.name} , \n")
    if not path.exists():
        print(f"missing: {path} (run run_labelling.py first)")
        return 1

    tickets = _load(path)
    total = len(tickets)
    labelled = [t for t in tickets if t.triage is not None]

    problems: list[str] = []
    for ticket in tickets:
        try:
            validate_ticket(ticket)
        except Exception as exc:
            problems.append(f"{ticket.ticket_id}: {exc}")

    print(f"records:        {total}")
    print(f"with triage:    {len(labelled)}")
    print(f"schema invalid: {len(problems)}")

    if not labelled:
        return 1

    # -- distributions ----------------------------------------------------------------- #
    departments = Counter(t.triage.department.value for t in labelled)
    urgencies = Counter(t.triage.urgency.value for t in labelled)
    intents = Counter(t.triage.intent for t in labelled)
    sources = Counter(t.triage.source.value for t in labelled)

    print("\nurgency distribution")
    for band in (b.value for b in PriorityBand):
        print(f"  {band:<9}{_percent(urgencies.get(band, 0), len(labelled))}")

    print("\ndepartment distribution")
    for name, count in departments.most_common():
        print(f"  {name:<20}{_percent(count, len(labelled))}")

    print(f"\nintents: {len(intents)} distinct; top 10")
    for name, count in intents.most_common(10):
        print(f"  {name:<30}{_percent(count, len(labelled))}")
    print(f"sources: {dict(sources)}")
    by_source(labelled)

    # -- sanity checks ------------------------------------------------------------------ #
    band_violations = [
        t for t in labelled
        if not (
            BAND_RANGES[t.triage.urgency][0]
            <= t.triage.priority_score
            <= BAND_RANGES[t.triage.urgency][1]
        )
    ]
    inconsistent = [
        t for t in labelled
        if t.triage.intent in INTENT_DEPARTMENTS
        and t.triage.department not in INTENT_DEPARTMENTS[t.triage.intent]
    ]
    scored = [t for t in labelled if t.triage.intent in INTENT_DEPARTMENTS]

    print("\nconsistency")
    print(f"  band vs score violations:      {len(band_violations)}")
    print(
        f"  intent/department mismatches:  {len(inconsistent)}"
        f" of {len(scored)} checkable"
        + (f" ({100 * len(inconsistent) / len(scored):.1f}%)" if scored else "")
    )

    # How often did the teacher override the keyword prefill? A prefill it never contradicts
    # taught it nothing, and distilling that just recovers the rules.
    overrides = Counter()
    comparable = 0
    for ticket in labelled:
        prefilled = ticket.metadata.get("prefilled_signals")
        if not prefilled:
            continue
        comparable += 1
        for field in ("service_down", "payment_related", "repeat_contact", "offensive", "polite"):
            if bool(prefilled.get(field)) != bool(getattr(ticket.signals, field)):
                overrides[field] += 1
    if comparable:
        print(f"\nsignal overrides by the labeller (of {comparable} records)")
        for field, count in overrides.most_common():
            print(f"  {field:<20}{_percent(count, comparable)}")
        if not overrides:
            print("  none ,  the teacher only ever agreed with the keyword rules.")

    # -- self-agreement ------------------------------------------------------------------ #
    exit_code = 0
    if repeat_path and repeat_path.exists():
        agreement = self_agreement(labelled, _load(repeat_path))
        print("\nself-agreement on the repeat subset")
        for name, value in agreement.items():
            print(f"  {name:<20}{value:.3f}")
        if agreement["department"] < 0.80 or agreement["urgency"] < 0.80:
            print(
                "\n  Below the 0.80 gate. Fix the prompt before training ,  the labels, not "
                "the model, are the bottleneck."
            )
            exit_code = 1
    else:
        print("\nself-agreement: no repeat file (run with --repeat-subset 200)")

    if gold_path and gold_path.exists():
        print(f"\ngold slice: {sum(1 for _ in read_jsonl(gold_path))} records at {gold_path.name}")

    if problems:
        print(f"\n{len(problems)} schema problems:")
        for line in problems[:10]:
            print(f"  {line}")
        exit_code = 1

    return exit_code


def by_source(labelled: list[UnifiedTicket]) -> None:
    """Urgency and department per `metadata.source`.

    The two halves of the corpus are different distributions on purpose -- Bitext is
    e-commerce and legitimately low-urgency, the synthetic half carries the faults -- so a
    single combined table hides whether either half landed.
    """
    sources = sorted({str(t.metadata.get("source", "?")) for t in labelled})
    for source in sources:
        rows = [t for t in labelled if str(t.metadata.get("source", "?")) == source]
        urgencies = Counter(t.triage.urgency.value for t in rows)
        departments = Counter(t.triage.department.value for t in rows)
        print(f"\nsource: {source}  ({len(rows)} records)")
        for band in (b.value for b in PriorityBand):
            print(f"  {band:<9}{_percent(urgencies.get(band, 0), len(rows))}")
        print("  departments: " + ", ".join(f"{k}={v}" for k, v in departments.most_common()))


def self_agreement(first: list[UnifiedTicket], second: list[UnifiedTicket]) -> dict[str, float]:
    """Agreement between two independent labelling passes over the same tickets."""
    by_id = {t.ticket_id: t for t in second if t.triage is not None}
    pairs = [(t, by_id[t.ticket_id]) for t in first if t.ticket_id in by_id]
    if not pairs:
        return {"n": 0.0, "intent": 0.0, "department": 0.0, "urgency": 0.0, "score_within_10": 0.0}

    return {
        "n": float(len(pairs)),
        "intent": sum(a.triage.intent == b.triage.intent for a, b in pairs) / len(pairs),
        "department": sum(a.triage.department == b.triage.department for a, b in pairs) / len(pairs),
        "urgency": sum(a.triage.urgency == b.triage.urgency for a, b in pairs) / len(pairs),
        "score_within_10": sum(
            abs(a.triage.priority_score - b.triage.priority_score) <= 10 for a, b in pairs
        )
        / len(pairs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="pre-flight the unlabelled corpus")
    parser.add_argument("--input", default=None)
    args = parser.parse_args()

    if args.dry:
        return dry_run(Path(args.input) if args.input else UNLABELLED)

    path = Path(args.input) if args.input else LABELLED
    return report(path, path.with_name("labelled_repeat.jsonl"), GOLD)


if __name__ == "__main__":
    raise SystemExit(main())
