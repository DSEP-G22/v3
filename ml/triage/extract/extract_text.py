"""Text-modality tickets from the Bitext corpus.

De-duplicated with the benchmark's own `dedupe` (model testing/src/text_data.py): Bitext is
template-generated, so the same utterance recurs many times and duplicates would both
inflate any score and waste labelling budget on repeats.

The `intent` column is kept as a weak prior in `metadata`, never in `triage` -- the whole
point of the labelling pass is to produce triage labels that do not exist in the corpus.
The `flags` column, by contrast, is real supervision and maps straight onto `Signals`.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

import pandas as pd

from common import BITEXT_CSV, SEED

# Bitext masks entities as `{{Order Number}}`; left literal they leak the intent, so they
# collapse to one token -- the same normalisation the intent classifier was trained under.
PLACEHOLDER_RE = re.compile(r"\{\{[^}]*\}\}")


def load_bitext() -> pd.DataFrame:
    frame = pd.read_csv(BITEXT_CSV)
    frame = frame.rename(columns={"instruction": "text"})
    frame["text"] = frame["text"].astype(str).str.strip()
    frame["raw_text"] = frame["text"]
    frame["text"] = frame["text"].str.replace(PLACEHOLDER_RE, "<ent>", regex=True)
    return frame[["text", "raw_text", "category", "intent", "flags"]]


def dedupe(frame: pd.DataFrame, key: str = "text") -> pd.DataFrame:
    """Drop exact duplicate utterances, case- and whitespace-insensitively."""
    normalised = frame[key].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    return frame.loc[~normalised.duplicated()].reset_index(drop=True)


def balanced_sample(frame: pd.DataFrame, total: int, seed: int = SEED) -> pd.DataFrame:
    """Sample up to `total` rows spread as evenly as possible over the 27 intents.

    Intents with fewer rows than the per-class quota contribute everything they have, and
    the shortfall is redistributed over the classes that still have rows left -- otherwise
    the rare intents would cap the whole corpus.
    """
    intents = sorted(frame["intent"].unique())
    remaining = total
    chunks: list[pd.DataFrame] = []
    pools = {intent: frame[frame["intent"] == intent] for intent in intents}

    for position, intent in enumerate(intents):
        classes_left = len(intents) - position
        quota = min(len(pools[intent]), max(1, remaining // classes_left))
        chunks.append(pools[intent].sample(n=quota, random_state=seed))
        remaining -= quota

    sampled = pd.concat(chunks).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return sampled.head(total)


def extract(limit: int = 3500, seed: int = SEED) -> pd.DataFrame:
    raw = load_bitext()
    deduped = dedupe(raw)
    sampled = balanced_sample(deduped, limit, seed)
    return sampled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3500)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    raw = load_bitext()
    deduped = dedupe(raw)
    sampled = balanced_sample(deduped, args.limit, args.seed)

    print(f"bitext rows:      {len(raw)}")
    print(f"after dedupe:     {len(deduped)}")
    print(f"sampled:          {len(sampled)}")
    print(f"intents covered:  {sampled['intent'].nunique()} / {deduped['intent'].nunique()}")

    counts = Counter(sampled["intent"])
    print("\nper-intent counts (min/median/max): "
          f"{min(counts.values())} / "
          f"{sorted(counts.values())[len(counts) // 2]} / "
          f"{max(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
