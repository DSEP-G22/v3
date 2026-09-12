"""One confidence scale for ASR, used everywhere (v2 had two thresholds that disagreed).

Ported from v1 FasterWhisperTranscriber: each segment's avg_logprob becomes exp(avg_logprob)
in [0, 1], averaged by segment duration.
"""

from __future__ import annotations

import math

LOW_CONFIDENCE = 0.60


def weighted(segments: list[tuple[float, float, float]]) -> float:
    """segments: (start_s, end_s, avg_logprob)."""
    total = weighted_sum = 0.0
    for start, end, logprob in segments:
        d = max(end - start, 1e-6)
        weighted_sum += math.exp(logprob) * d
        total += d
    return round(weighted_sum / total, 4) if total else 0.0


if __name__ == "__main__":
    assert weighted([]) == 0.0
    assert abs(weighted([(0, 1, 0.0)]) - 1.0) < 1e-9
    mix = weighted([(0, 9, math.log(0.9)), (9, 10, math.log(0.1))])
    assert abs(mix - 0.82) < 1e-6 and mix >= LOW_CONFIDENCE
    print("confidence ok")
