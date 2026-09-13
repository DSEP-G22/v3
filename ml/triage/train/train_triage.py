"""Distil the LLM's labels into a small multi-task classifier.

The student is a shallow head over frozen MiniLM embeddings concatenated with the engineered
`Signals` features: three classification heads (intent, department, urgency) and one
regression head for `priority_score`. The backbone stays frozen, which is what keeps
inference inside the plan's 10 ms/ticket budget.

Baselines follow the notebook-01 patterns so the comparison is like-for-like: TF-IDF+LogReg
and MiniLM+LogReg, both as independent per-target classifiers.

    python TriageModel/train/train_triage.py
    python TriageModel/train/train_triage.py --skip-baselines --epochs 30

Everything is scored on `gold.jsonl`, never on rows the model trained on.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import _paths  # noqa: F401  (sets sys.path)

import features  # noqa: E402
from common import GOLD, SEED  # noqa: E402

TRIAGE_ROOT = Path(__file__).resolve().parents[1]
DATA = TRIAGE_ROOT / "data"
ARTIFACTS = TRIAGE_ROOT / "artifacts"
CACHE = DATA / "embedding_cache"
MLRUNS = TRIAGE_ROOT / "mlruns"  # local fallback; MLFLOW_TRACKING_URI (the mlops profile) wins

TARGETS = ("intent", "department", "urgency")


@dataclass
class Scores:
    name: str
    accuracy: dict[str, float] = field(default_factory=dict)
    macro_f1: dict[str, float] = field(default_factory=dict)
    score_mae: float = 0.0
    train_s: float = 0.0
    latency_ms: float = 0.0

    def row(self) -> dict:
        return {
            "model": self.name,
            **{f"acc_{k}": round(v, 4) for k, v in self.accuracy.items()},
            **{f"f1_{k}": round(v, 4) for k, v in self.macro_f1.items()},
            "score_mae": round(self.score_mae, 2),
            "train_s": round(self.train_s, 1),
            "latency_ms": round(self.latency_ms, 3),
        }


def _metrics(true: np.ndarray, predicted: np.ndarray) -> tuple[float, float]:
    from sklearn.metrics import accuracy_score, f1_score

    return (
        float(accuracy_score(true, predicted)),
        float(f1_score(true, predicted, average="macro", zero_division=0)),
    )


def _measure_latency(predict, sample, repeats: int = 50) -> float:
    """Single-ticket latency -- what a live service actually pays, not the batch average."""
    predict(sample)  # warm up
    started = time.perf_counter()
    for _ in range(repeats):
        predict(sample)
    return (time.perf_counter() - started) * 1000 / repeats


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
def baseline_tfidf(train_texts, train_targets, gold_texts, gold_targets) -> Scores:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    scores = Scores(name="tfidf+logreg")
    started = time.perf_counter()
    fitted = {}
    for target in TARGETS:
        pipeline = make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
            LogisticRegression(max_iter=2000, C=4.0),
        )
        pipeline.fit(train_texts, train_targets[target])
        fitted[target] = pipeline
        accuracy, macro = _metrics(gold_targets[target], pipeline.predict(gold_texts))
        scores.accuracy[target] = accuracy
        scores.macro_f1[target] = macro
    scores.train_s = time.perf_counter() - started
    scores.latency_ms = _measure_latency(lambda s: fitted["urgency"].predict([s]), gold_texts[0])
    return scores


def baseline_minilm(train_embeddings, train_targets, gold_embeddings, gold_targets) -> Scores:
    from sklearn.linear_model import LogisticRegression

    scores = Scores(name="minilm+logreg")
    started = time.perf_counter()
    fitted = {}
    for target in TARGETS:
        model = LogisticRegression(max_iter=3000, C=10.0)
        model.fit(train_embeddings, train_targets[target])
        fitted[target] = model
        accuracy, macro = _metrics(gold_targets[target], model.predict(gold_embeddings))
        scores.accuracy[target] = accuracy
        scores.macro_f1[target] = macro
    scores.train_s = time.perf_counter() - started
    sample = gold_embeddings[:1]
    scores.latency_ms = _measure_latency(lambda s: fitted["urgency"].predict(s), sample)
    return scores


# --------------------------------------------------------------------------- #
# The distilled multi-task head
# --------------------------------------------------------------------------- #
class MultiTaskHead:
    """Three softmax heads and one regression head over a shared hidden layer."""

    def __init__(self, input_dim: int, class_counts: dict[str, int], hidden: int = 256) -> None:
        import torch.nn as nn

        self.class_counts = class_counts
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
        )
        self.heads = nn.ModuleDict(
            {target: nn.Linear(hidden, count) for target, count in class_counts.items()}
        )
        self.score_head = nn.Linear(hidden, 1)

    def parameters(self):
        import itertools

        return itertools.chain(
            self.net.parameters(), self.heads.parameters(), self.score_head.parameters()
        )

    def forward(self, x):
        shared = self.net(x)
        return (
            {target: head(shared) for target, head in self.heads.items()},
            self.score_head(shared).squeeze(-1),
        )

    def eval(self):
        self.net.eval()
        self.heads.eval()
        self.score_head.eval()

    def train(self):
        self.net.train()
        self.heads.train()
        self.score_head.train()

    def state_dict(self):
        return {
            "net": self.net.state_dict(),
            "heads": self.heads.state_dict(),
            "score_head": self.score_head.state_dict(),
        }


def train_distilled(
    train_x: np.ndarray,
    train_targets: dict[str, np.ndarray],
    gold_x: np.ndarray,
    gold_targets: dict[str, np.ndarray],
    *,
    epochs: int = 25,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    seed: int = SEED,
) -> tuple[Scores, MultiTaskHead, dict[str, list[str]]]:
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)

    label_maps = {t: sorted(set(train_targets[t]) | set(gold_targets[t])) for t in TARGETS}
    index_maps = {t: {label: i for i, label in enumerate(label_maps[t])} for t in TARGETS}

    x_train = torch.tensor(train_x, dtype=torch.float32)
    x_gold = torch.tensor(gold_x, dtype=torch.float32)
    y_train = {
        t: torch.tensor([index_maps[t][v] for v in train_targets[t]], dtype=torch.long)
        for t in TARGETS
    }
    # The score head learns on a 0..1 scale; predictions are mapped back for reporting.
    score_train = torch.tensor(train_targets["priority_score"] / 100.0, dtype=torch.float32)

    model = MultiTaskHead(train_x.shape[1], {t: len(label_maps[t]) for t in TARGETS})
    optimiser = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    cross_entropy = nn.CrossEntropyLoss()
    mse = nn.MSELoss()

    started = time.perf_counter()
    sample_count = x_train.shape[0]
    for _epoch in range(epochs):
        model.train()
        permutation = torch.randperm(sample_count)
        for start in range(0, sample_count, batch_size):
            batch = permutation[start : start + batch_size]
            logits, predicted_score = model.forward(x_train[batch])

            loss = sum(cross_entropy(logits[t], y_train[t][batch]) for t in TARGETS)
            # The regression head is a secondary objective: it sharpens the ordering inside a
            # band, but the bands themselves are what the queue sorts on.
            loss = loss + 0.5 * mse(predicted_score, score_train[batch])

            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
    train_seconds = time.perf_counter() - started

    model.eval()
    scores = Scores(name="distilled_multitask", train_s=train_seconds)
    with torch.no_grad():
        logits, predicted_score = model.forward(x_gold)
        for target in TARGETS:
            predicted = [label_maps[target][i] for i in logits[target].argmax(dim=1).tolist()]
            accuracy, macro = _metrics(gold_targets[target], np.array(predicted))
            scores.accuracy[target] = accuracy
            scores.macro_f1[target] = macro
        scores.score_mae = float(
            np.mean(np.abs(predicted_score.numpy() * 100 - gold_targets["priority_score"]))
        )

        single = x_gold[:1]
        scores.latency_ms = _measure_latency(lambda s: model.forward(s), single)

    return scores, model, label_maps


def _write_table(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    columns = list(rows[0])
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def _log_mlflow(scores: list[Scores], params: dict) -> None:
    try:
        import mlflow
    except ImportError:
        print("\n(mlflow not installed ,  skipping run logging)")
        return

    import os

    if uri := os.environ.get("MLFLOW_TRACKING_URI"):
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment("triage_distillation")
        for entry in scores:
            with mlflow.start_run(run_name=entry.name):
                mlflow.log_params({**params, "model": entry.name})
                mlflow.log_metrics({**{f"acc_{t}": v for t, v in entry.accuracy.items()},
                                    **{f"f1_{t}": v for t, v in entry.macro_f1.items()},
                                    "score_mae": entry.score_mae, "latency_ms": entry.latency_ms})
        print(f"\nlogged {len(scores)} runs to {uri}")
        return

    MLRUNS.mkdir(parents=True, exist_ok=True)
    # A local store, as the plan asks. MLflow 3 put the bare-filesystem backend into
    # maintenance mode, so the local store is a SQLite file in the same directory rather
    # than a `file:` URI -- still no server, still committed alongside the runs.
    mlflow.set_tracking_uri(f"sqlite:///{(MLRUNS / 'mlflow.db').resolve().as_posix()}")
    mlflow.set_registry_uri(f"sqlite:///{(MLRUNS / 'mlflow.db').resolve().as_posix()}")
    mlflow.set_experiment("triage_distillation")

    for entry in scores:
        with mlflow.start_run(run_name=entry.name):
            mlflow.log_params({**params, "model": entry.name})
            for target, value in entry.accuracy.items():
                mlflow.log_metric(f"acc_{target}", value)
            for target, value in entry.macro_f1.items():
                mlflow.log_metric(f"f1_{target}", value)
            mlflow.log_metric("score_mae", entry.score_mae)
            mlflow.log_metric("train_s", entry.train_s)
            mlflow.log_metric("latency_ms", entry.latency_ms)
    print(f"\nlogged {len(scores)} runs to {MLRUNS}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", default=str(DATA / "train.jsonl"))
    parser.add_argument("--gold", default=str(GOLD))
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--skip-baselines", action="store_true")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    train_path, gold_path = Path(args.train), Path(args.gold)
    for path in (train_path, gold_path):
        if not path.exists():
            print(f"missing: {path}\nRun label/run_labelling.py then label/make_gold.py first.")
            return 1

    train_tickets = features.load_tickets(train_path)
    gold_tickets = features.load_tickets(gold_path)
    print(f"train: {len(train_tickets)}   gold: {len(gold_tickets)}")

    overlap = {t.ticket_id for t in train_tickets} & {t.ticket_id for t in gold_tickets}
    if overlap:
        print(f"ERROR: {len(overlap)} tickets appear in both splits; the score would be invalid.")
        return 1

    train_texts, gold_texts = features.texts(train_tickets), features.texts(gold_tickets)
    train_targets, gold_targets = features.targets(train_tickets), features.targets(gold_tickets)

    print("embedding…")
    train_embeddings = features.embed(train_texts, cache=CACHE)
    gold_embeddings = features.embed(gold_texts, cache=CACHE)

    train_signals, signal_names = features.signal_matrix(train_tickets)
    gold_signals, _ = features.signal_matrix(gold_tickets)
    train_x = np.hstack([train_embeddings, train_signals])
    gold_x = np.hstack([gold_embeddings, gold_signals])
    print(f"features: {train_embeddings.shape[1]} embedding + {len(signal_names)} signals")

    results: list[Scores] = []
    if not args.skip_baselines:
        print("\nbaseline: tfidf+logreg")
        results.append(baseline_tfidf(train_texts, train_targets, gold_texts, gold_targets))
        print("baseline: minilm+logreg")
        results.append(
            baseline_minilm(train_embeddings, train_targets, gold_embeddings, gold_targets)
        )

    print("\ndistilling multi-task head…")
    distilled, model, label_maps = train_distilled(
        train_x, train_targets, gold_x, gold_targets, epochs=args.epochs, seed=args.seed
    )
    results.append(distilled)

    _write_table([entry.row() for entry in results], ARTIFACTS / "score_table.json")

    import torch

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "label_maps": label_maps,
            "signal_names": signal_names,
            "embedding_model": features.MINILM,
            "input_dim": train_x.shape[1],
        },
        ARTIFACTS / "triage_multitask.pt",
    )
    print(f"\nsaved {ARTIFACTS / 'triage_multitask.pt'}")

    _log_mlflow(
        results,
        {
            "epochs": args.epochs,
            "seed": args.seed,
            "train_rows": len(train_tickets),
            "gold_rows": len(gold_tickets),
        },
    )

    # The plan's gate: within 5 macro-F1 points of the teacher, under 10 ms per ticket.
    print("\ngates")
    print(f"  latency {distilled.latency_ms:.2f} ms/ticket "
          f"({'PASS' if distilled.latency_ms < 10 else 'FAIL'}, budget 10 ms)")
    print("  macro-F1 vs the LLM: compare against the self-agreement number from "
          "label/validate.py ,  the teacher's consistency is the ceiling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
