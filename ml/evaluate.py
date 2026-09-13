"""Reduce the trainer's score table to the one candidate record the promotion gate reads.

    python ml/evaluate.py      (the DVC `evaluate` stage)

Writes metrics/candidate.json: macro-F1 over the three heads, per-head F1, score MAE and
single-ticket latency, plus whether it clears the latency budget in params.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def main() -> None:
    rows = json.loads((HERE / "triage" / "artifacts" / "score_table.json").read_text(encoding="utf-8"))
    gate = yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8"))["gate"]
    c = next(r for r in rows if r["model"] == "distilled_multitask")
    heads = ("intent", "department", "urgency")
    out = {
        "f1_mean": round(sum(c[f"f1_{h}"] for h in heads) / len(heads), 4),
        **{f"f1_{h}": c[f"f1_{h}"] for h in heads},
        "score_mae": c["score_mae"],
        "latency_ms": c["latency_ms"],
        "within_latency": c["latency_ms"] < gate["max_latency_ms"],
    }
    (HERE / "metrics").mkdir(exist_ok=True)
    (HERE / "metrics" / "candidate.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
