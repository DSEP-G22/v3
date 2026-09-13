"""Run the LLM labelling pass over `unlabelled.jsonl`.

Batched, concurrent and resumable: every answer is cached by content hash, so an interrupted
run resumes for free and a re-run costs nothing. The LLM provider is the MVP's own swappable
interface, so the labeller and the runtime speak to the same models.

    python TriageModel/label/run_labelling.py --limit 50    # small run first, inspect by hand
    python TriageModel/label/run_labelling.py               # full corpus
    python TriageModel/label/run_labelling.py --repeat-subset 200 --temperature 0.3
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import _paths  # noqa: F401  (sets sys.path)

import prompt as prompt_module
from cache import LabelCache

from common import LABELLED, UNLABELLED, read_jsonl  # noqa: E402

from schema import (  # noqa: E402
    Department,
    OutageScope,
    PriorityBand,
    Sentiment,
    Signals,
    Triage,
    TriageSource,
    UnifiedTicket,
)

PROMPT_VERSION = 1
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "label_cache.json"

# Bands and scores must agree; the prompt says so, but a teacher still drifts occasionally.
BAND_RANGES = {
    PriorityBand.critical: (80, 100),
    PriorityBand.high: (60, 79),
    PriorityBand.normal: (35, 59),
    PriorityBand.low: (0, 34),
}


def _clamp_to_band(band: PriorityBand, score: int) -> int:
    low, high = BAND_RANGES[band]
    return max(low, min(high, score))


def apply_label(ticket: UnifiedTicket, answer: dict, model_id: str) -> UnifiedTicket:
    """Merge one labelling answer into a ticket, keeping the record self-consistent."""
    labelled = ticket.model_copy(deep=True)

    raw_triage = answer["triage"]
    band = PriorityBand(raw_triage["urgency"])
    labelled.triage = Triage(
        intent=str(raw_triage["intent"]).strip().lower().replace(" ", "_"),
        department=Department(raw_triage["department"]),
        urgency=band,
        priority_score=_clamp_to_band(band, int(raw_triage["priority_score"])),
        confidence=float(raw_triage["confidence"]),
        source=TriageSource.llm,
        rationale=raw_triage.get("rationale"),
        model_version=model_id,
    )

    # The corrected signals replace the rule-prefilled ones, but only for the fields the
    # labeller is actually asked about -- account context it cannot see is preserved.
    corrected = answer.get("signals") or {}
    signals = labelled.signals
    for field in (
        "colloquial", "noisy_text", "offensive", "polite", "interrogative",
        "service_down", "payment_related", "repeat_contact", "device_visible",
    ):
        if field in corrected:
            setattr(signals, field, bool(corrected[field]))
    if "sentiment" in corrected:
        signals.sentiment = Sentiment(corrected["sentiment"])
    if "sentiment_score" in corrected:
        signals.sentiment_score = max(0.0, min(1.0, float(corrected["sentiment_score"])))
    if "outage_scope" in corrected:
        signals.outage_scope = OutageScope(corrected["outage_scope"])
    for field in ("urgency_keywords", "fault_leds", "error_codes"):
        if field in corrected and isinstance(corrected[field], list):
            setattr(signals, field, [str(v) for v in corrected[field]])

    labelled.metadata = {
        **labelled.metadata,
        "labelled_by": model_id,
        "prompt_version": PROMPT_VERSION,
        # The rule prefill is kept so `validate.py` can measure how often the teacher
        # overrode the keywords -- a prefill the LLM never contradicts is a prefill that
        # taught it nothing.
        "prefilled_signals": ticket.signals.model_dump(mode="json"),
    }
    return labelled


def label_one(
    ticket: UnifiedTicket,
    provider,
    cache: LabelCache,
    *,
    taxonomy: list[str] | None,
    temperature: float,
    model_id: str,
    cache_salt: str = "",
) -> tuple[UnifiedTicket, bool]:
    """Label one ticket. Returns `(ticket, came_from_cache)`."""
    messages = prompt_module.build_messages(ticket, taxonomy)
    payload = json.dumps(messages, sort_keys=True) + cache_salt
    key = LabelCache.key(
        model=model_id, temperature=temperature, prompt_version=PROMPT_VERSION, payload=payload
    )

    cached = cache.get(key)
    if cached is not None:
        return apply_label(ticket, cached, model_id), True

    # Ollama's `format` constraint is not always enforced by the model (a missing required
    # key, or an enum value outside the schema, both still parse as valid JSON, so the
    # provider's own parse-failure retry never sees them). Validate the shape before caching
    # -- caching a broken answer would make every future run replay the same failure from the
    # cache forever -- and give the model up to two corrective retries.
    request_messages = messages
    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        answer = provider.chat(
            request_messages,
            json_schema=prompt_module.response_schema(),
            temperature=temperature,
            schema_name="triage_label",
        )
        if not isinstance(answer, dict):
            raise ValueError(f"provider returned {type(answer).__name__}, expected a JSON object")

        try:
            labelled = apply_label(ticket, answer, model_id)
        except (KeyError, ValueError, TypeError) as exc:
            last_exc = exc
            request_messages = messages + [
                {"role": "assistant", "content": json.dumps(answer)},
                {
                    "role": "user",
                    "content": f"That answer was invalid ({exc}). Reply again with the JSON "
                    "object only, filling every required field with a value from its "
                    "allowed set.",
                },
            ]
            continue
        cache.put(key, answer)
        return labelled, False

    raise last_exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(UNLABELLED))
    parser.add_argument("--output", default=str(LABELLED))
    parser.add_argument("--limit", type=int, default=None, help="label only the first N records")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--provider", default=None, help="overrides LLM_PROVIDER")
    parser.add_argument(
        "--repeat-subset",
        type=int,
        default=0,
        help="also label the first N records a second time, for the self-agreement report",
    )
    args = parser.parse_args()

    if args.provider == "heuristic":
        # Offline stand-in: exercises the whole chain without a key. Its labels are the
        # keyword rules, so anything distilled from them only recovers the rules.
        from heuristic_provider import HeuristicProvider

        provider = HeuristicProvider()
    else:
        from llm.provider import get_provider

        provider = get_provider(args.provider)
    model_id = f"{provider.name}:{provider.model_id()}"

    tickets = [UnifiedTicket.model_validate(row) for row in read_jsonl(Path(args.input))]
    if args.limit:
        tickets = tickets[: args.limit]

    taxonomy = sorted(
        {str(t.metadata["bitext_intent"]) for t in tickets if t.metadata.get("bitext_intent")}
    )
    cache = LabelCache(CACHE_PATH)

    print(f"labelling {len(tickets)} tickets with {model_id} (T={args.temperature})")
    print(f"cache: {len(cache)} entries at {CACHE_PATH}")

    results: dict[str, UnifiedTicket] = {}
    failures: list[tuple[str, str]] = []
    hits = 0
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                label_one,
                ticket,
                provider,
                cache,
                taxonomy=taxonomy,
                temperature=args.temperature,
                model_id=model_id,
            ): ticket
            for ticket in tickets
        }
        for done, future in enumerate(as_completed(futures), start=1):
            ticket = futures[future]
            try:
                labelled, from_cache = future.result()
                results[labelled.ticket_id] = labelled
                hits += int(from_cache)
            except Exception as exc:
                failures.append((ticket.ticket_id, f"{type(exc).__name__}: {exc}"))
            if done % 50 == 0 or done == len(tickets):
                elapsed = time.perf_counter() - started
                print(
                    f"  {done}/{len(tickets)}  cached={hits}  failed={len(failures)}  "
                    f"{elapsed:.0f}s",
                    flush=True,
                )

    cache.flush()

    # Keep the input order so the file is stable across runs and diffs stay readable.
    ordered = [results[t.ticket_id] for t in tickets if t.ticket_id in results]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for ticket in ordered:
            handle.write(json.dumps(ticket.model_dump(mode="json"), ensure_ascii=False) + "\n")

    print(f"\nwrote {len(ordered)} labelled records -> {output}")
    if failures:
        print(f"{len(failures)} failed:")
        for ticket_id, message in failures[:10]:
            print(f"  {ticket_id}: {message}")

    if args.repeat_subset:
        repeat_path = output.with_name("labelled_repeat.jsonl")
        subset = tickets[: args.repeat_subset]
        print(f"\nsecond pass over {len(subset)} records for the self-agreement report")
        repeats: list[UnifiedTicket] = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    label_one,
                    ticket,
                    provider,
                    cache,
                    taxonomy=taxonomy,
                    temperature=args.temperature,
                    model_id=model_id,
                    # A different salt forces a genuinely independent second sample rather
                    # than replaying the first answer out of the cache.
                    cache_salt="|repeat",
                ): ticket
                for ticket in subset
            }
            for future in as_completed(futures):
                try:
                    repeats.append(future.result()[0])
                except Exception as exc:
                    failures.append((futures[future].ticket_id, str(exc)))
        cache.flush()
        with repeat_path.open("w", encoding="utf-8") as handle:
            for ticket in repeats:
                handle.write(json.dumps(ticket.model_dump(mode="json"), ensure_ascii=False) + "\n")
        print(f"wrote {len(repeats)} repeat labels -> {repeat_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
