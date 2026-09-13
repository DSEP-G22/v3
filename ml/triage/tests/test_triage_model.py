"""Contract tests for the trained artifact in `artifacts/triage_multitask.pt`.

These test the saved checkpoint as a deployable object: that it loads, that its recorded
feature contract still matches `Signals.as_features()`, that a forward pass produces
well-formed predictions, and that the split it was scored on was honest. They deliberately
do NOT assert accuracy thresholds -- the corpus is 734 rows with 76 intent classes, so an
accuracy gate here would encode this run's noise as a requirement. The gates that do have
thresholds are the ones the runbook names: latency, split disjointness, and band/score
agreement.

Skipped rather than failed when the artifact or the splits are absent, so a fresh clone that
has not run the pipeline still gets a green suite.

    python -m pytest TriageModel/tests/test_triage_model.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

TRIAGE_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = TRIAGE_ROOT / "artifacts" / "triage_multitask.pt"
SCORE_TABLE = TRIAGE_ROOT / "artifacts" / "score_table.json"
TRAIN_JSONL = TRIAGE_ROOT / "data" / "train.jsonl"
GOLD_JSONL = TRIAGE_ROOT / "data" / "gold.jsonl"

# Same file-path import trick as `test_schema.py`: `MVP/api/schema.py` is a re-export shim
# that is also importable as `schema`, so importing by name gives whichever directory won
# the race to `sys.path`.
_SCHEMA_FILE = TRIAGE_ROOT / "schema.py"
_spec = importlib.util.spec_from_file_location("triage_schema_under_test", _SCHEMA_FILE)
schema = importlib.util.module_from_spec(_spec)
sys.modules["triage_schema_under_test"] = schema
_spec.loader.exec_module(schema)

from triage_schema_under_test import PriorityBand, Signals  # noqa: E402

# Mirrors `run_labelling.BAND_RANGES`. Duplicated rather than imported because importing the
# runner pulls in the LLM provider stack, which a model test has no business requiring.
BAND_RANGES = {
    "critical": (80, 100),
    "high": (60, 79),
    "normal": (35, 59),
    "low": (0, 34),
}

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def checkpoint() -> dict:
    if not ARTIFACT.exists():
        pytest.skip(f"no artifact at {ARTIFACT}; run train/train_triage.py first")
    torch = pytest.importorskip("torch")
    return torch.load(ARTIFACT, weights_only=False)


@pytest.fixture(scope="module")
def rebuilt(checkpoint):
    """The checkpoint reassembled into a runnable module, the way a server would load it."""
    torch = pytest.importorskip("torch")
    import torch.nn as nn

    hidden = checkpoint["state_dict"]["net"]["0.weight"].shape[0]
    net = nn.Sequential(
        nn.Linear(checkpoint["input_dim"], hidden),
        nn.ReLU(),
        nn.Dropout(0.2),
    )
    net.load_state_dict(checkpoint["state_dict"]["net"])
    heads = nn.ModuleDict(
        {target: nn.Linear(hidden, len(labels)) for target, labels in checkpoint["label_maps"].items()}
    )
    heads.load_state_dict(checkpoint["state_dict"]["heads"])
    score_head = nn.Linear(hidden, 1)
    score_head.load_state_dict(checkpoint["state_dict"]["score_head"])

    net.eval()
    heads.eval()
    score_head.eval()

    def predict(x):
        with torch.no_grad():
            shared = net(x)
            return (
                {target: head(shared) for target, head in heads.items()},
                score_head(shared).squeeze(-1),
            )

    return predict


# --------------------------------------------------------------------------- #
# The checkpoint is self-describing
# --------------------------------------------------------------------------- #
def test_checkpoint_carries_everything_needed_to_serve(checkpoint):
    """A checkpoint missing any of these cannot be loaded without guessing."""
    for key in ("state_dict", "label_maps", "signal_names", "embedding_model", "input_dim"):
        assert key in checkpoint, f"checkpoint is missing {key!r}"


def test_signal_names_still_match_the_schema(checkpoint):
    """The recorded feature order must equal `Signals.as_features()`.

    This is the test that catches a renamed or reordered signal field. The trainer builds its
    tensor from `as_features()` insertion order, so a schema edit silently shifts every column
    and the saved weights start reading the wrong feature -- with no error anywhere.
    """
    assert list(checkpoint["signal_names"]) == list(Signals().as_features())


def test_input_dim_equals_embedding_plus_signals(checkpoint):
    """384 MiniLM dimensions + the signal vector. A mismatch means the artifact and the
    feature builder disagree about the tensor width."""
    assert checkpoint["input_dim"] == 384 + len(checkpoint["signal_names"])


def test_urgency_head_covers_exactly_the_four_bands(checkpoint):
    assert set(map(str, checkpoint["label_maps"]["urgency"])) == {b.value for b in PriorityBand}


def test_department_head_covers_only_real_departments(checkpoint):
    from triage_schema_under_test import Department

    predicted = set(map(str, checkpoint["label_maps"]["department"]))
    assert predicted <= {d.value for d in Department}
    assert predicted, "department head has no classes"


def test_embedding_model_is_recorded_and_pinned(checkpoint):
    """Serving with a different encoder than training used produces garbage silently."""
    assert checkpoint["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"


def test_head_widths_match_their_label_maps(checkpoint):
    """A head wider or narrower than its label map means argmax can index a nonexistent
    label, or that a class can never be predicted at all."""
    heads = checkpoint["state_dict"]["heads"]
    for target, labels in checkpoint["label_maps"].items():
        assert heads[f"{target}.weight"].shape[0] == len(labels), f"{target} head width"


# --------------------------------------------------------------------------- #
# A forward pass behaves
# --------------------------------------------------------------------------- #
def test_forward_pass_emits_one_prediction_per_row(checkpoint, rebuilt):
    torch = pytest.importorskip("torch")

    batch = torch.zeros((5, checkpoint["input_dim"]), dtype=torch.float32)
    logits, scores = rebuilt(batch)

    for target, labels in checkpoint["label_maps"].items():
        assert logits[target].shape == (5, len(labels))
    assert scores.shape == (5,)


def test_predictions_are_finite(checkpoint, rebuilt):
    """NaN weights load without complaint and only surface as garbage predictions."""
    torch = pytest.importorskip("torch")

    rng = np.random.default_rng(0)
    batch = torch.tensor(rng.normal(size=(8, checkpoint["input_dim"])), dtype=torch.float32)
    logits, scores = rebuilt(batch)

    for target, tensor in logits.items():
        assert torch.isfinite(tensor).all(), f"{target} logits contain NaN/inf"
    assert torch.isfinite(scores).all()


def test_inference_is_deterministic(checkpoint, rebuilt):
    """Dropout must be inactive in eval mode. If it is not, two identical calls disagree and
    the same ticket gets two different departments on two page loads."""
    torch = pytest.importorskip("torch")

    batch = torch.tensor(
        np.random.default_rng(1).normal(size=(4, checkpoint["input_dim"])), dtype=torch.float32
    )
    first_logits, first_scores = rebuilt(batch)
    second_logits, second_scores = rebuilt(batch)

    for target in first_logits:
        assert torch.equal(first_logits[target], second_logits[target]), f"{target} not stable"
    assert torch.equal(first_scores, second_scores)


def test_argmax_maps_back_to_a_real_label(checkpoint, rebuilt):
    torch = pytest.importorskip("torch")

    batch = torch.tensor(
        np.random.default_rng(2).normal(size=(16, checkpoint["input_dim"])), dtype=torch.float32
    )
    logits, _ = rebuilt(batch)

    for target, labels in checkpoint["label_maps"].items():
        for index in logits[target].argmax(dim=1).tolist():
            assert 0 <= index < len(labels)
            assert str(labels[index])


def test_predicted_score_lands_in_zero_to_one_hundred(checkpoint, rebuilt):
    """The head trains on a 0..1 scale and the trainer multiplies by 100 for reporting. A
    prediction far outside 0..100 means the scaling convention drifted.

    The input must be scaled like a real feature row. MiniLM embeddings are L2-normalised, so
    a real row's values sit inside roughly +/-0.25; `score_head` is an unbounded `nn.Linear`,
    and feeding it standard-normal noise (30x that magnitude) makes it extrapolate to -81 and
    +260 while the scale is perfectly correct. That measures the test's input, not the model.
    """
    torch = pytest.importorskip("torch")

    rng = np.random.default_rng(3)
    embedding_dim = 384
    # Unit-norm rows, as `features.embed(normalize_embeddings=True)` produces.
    embeddings = rng.normal(size=(32, embedding_dim))
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    # Signals are 0/1 flags plus a few 0..1 scores and small counts.
    signals = rng.integers(0, 2, size=(32, len(checkpoint["signal_names"]))).astype(float)

    batch = torch.tensor(np.hstack([embeddings, signals]), dtype=torch.float32)
    _, scores = rebuilt(batch)
    as_reported = scores.numpy() * 100

    # Generous bounds: a regression head is not clamped, so ordinary error may cross the
    # boundary slightly. The assertion is against a broken scale (0..1 left unmultiplied, or
    # 0..10000), not against regression error.
    assert as_reported.min() > -25, f"score scale looks wrong: min {as_reported.min()}"
    assert as_reported.max() < 125, f"score scale looks wrong: max {as_reported.max()}"


def test_latency_is_inside_the_ten_millisecond_budget(checkpoint, rebuilt):
    """The plan's gate. Single-ticket, not batch -- what a live request actually pays."""
    torch = pytest.importorskip("torch")

    single = torch.zeros((1, checkpoint["input_dim"]), dtype=torch.float32)
    rebuilt(single)  # warm up

    started = time.perf_counter()
    for _ in range(50):
        rebuilt(single)
    per_call_ms = (time.perf_counter() - started) * 1000 / 50

    assert per_call_ms < 10, f"{per_call_ms:.2f} ms/ticket exceeds the 10 ms budget"


# --------------------------------------------------------------------------- #
# The split it was scored on
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def splits() -> tuple[list[dict], list[dict]]:
    if not (TRAIN_JSONL.exists() and GOLD_JSONL.exists()):
        pytest.skip("no train/gold split; run label/make_gold.py first")
    return _read_jsonl(TRAIN_JSONL), _read_jsonl(GOLD_JSONL)


def test_train_and_gold_are_disjoint(splits):
    """Scoring against rows the model trained on measures memorisation. This is the one
    result-invalidating bug that no accuracy number would reveal."""
    train, gold = splits
    overlap = {r["ticket_id"] for r in train} & {r["ticket_id"] for r in gold}
    assert not overlap, f"{len(overlap)} tickets in both splits"


def test_every_scored_row_actually_has_a_label(splits):
    train, gold = splits
    for name, rows in (("train", train), ("gold", gold)):
        unlabelled = [r["ticket_id"] for r in rows if not r.get("triage")]
        assert not unlabelled, f"{len(unlabelled)} unlabelled rows in {name}"


def test_no_heuristic_labels_reached_training(splits):
    """The failure the runbook was written to prevent: a student distilled from the static
    keyword equation recovers the keyword rules and nothing else."""
    train, gold = splits
    for name, rows in (("train", train), ("gold", gold)):
        heuristic = [
            r["ticket_id"] for r in rows if str(r["metadata"].get("labelled_by", "")).startswith("heuristic:")
        ]
        assert not heuristic, f"{len(heuristic)} heuristic-labelled rows in {name}"


def test_labels_span_all_four_urgency_bands(splits):
    """A corpus missing a band cannot teach it, and a headline accuracy computed over three
    bands reads as if it covered four."""
    train, _ = splits
    present = {r["triage"]["urgency"] for r in train}
    assert present == {b.value for b in PriorityBand}, f"train covers only {sorted(present)}"


def test_band_and_score_agree_on_every_row(splits):
    """`run_labelling` clamps the score into its band, so a violation here means the corpus
    is internally inconsistent and the regression target contradicts the class target."""
    train, gold = splits
    for name, rows in (("train", train), ("gold", gold)):
        for row in rows:
            band = row["triage"]["urgency"]
            score = row["triage"]["priority_score"]
            low, high = BAND_RANGES[band]
            assert low <= score <= high, f"{name} {row['ticket_id']}: {band} with score {score}"


def test_gold_review_flag_is_present_and_honest(splits):
    """Not an assertion that review happened -- an assertion that the flag exists, so the
    score table can never be read as human-verified when it is not."""
    _, gold = splits
    for row in gold:
        assert "human_reviewed" in row["metadata"], f"{row['ticket_id']} lacks the review flag"
        assert isinstance(row["metadata"]["human_reviewed"], bool)


# --------------------------------------------------------------------------- #
# The score table
# --------------------------------------------------------------------------- #
def test_score_table_is_present_and_shaped(checkpoint):
    if not SCORE_TABLE.exists():
        pytest.skip("no score_table.json")
    rows = json.loads(SCORE_TABLE.read_text(encoding="utf-8"))
    assert rows, "score table is empty"
    for row in rows:
        assert "model" in row
        for metric in ("acc_urgency", "acc_department", "f1_urgency"):
            assert 0.0 <= row[metric] <= 1.0, f"{row['model']}.{metric} out of range"


def test_score_table_includes_the_distilled_model(checkpoint):
    """The artifact and the table must describe the same run."""
    if not SCORE_TABLE.exists():
        pytest.skip("no score_table.json")
    rows = json.loads(SCORE_TABLE.read_text(encoding="utf-8"))
    assert any(r["model"] == "distilled_multitask" for r in rows)


def test_distilled_model_beats_a_constant_predictor(splits):
    """The bar the old `acc_urgency = 0.9333` artifact failed: that number was a model that
    answered `low` every time, on a corpus that was 98.4% `low`. Compare against the actual
    majority-class rate on the set that was scored, not against a fixed number.
    """
    if not SCORE_TABLE.exists():
        pytest.skip("no score_table.json")
    _, gold = splits
    rows = json.loads(SCORE_TABLE.read_text(encoding="utf-8"))
    distilled = next((r for r in rows if r["model"] == "distilled_multitask"), None)
    if distilled is None:
        pytest.skip("no distilled row in the score table")

    counts: dict[str, int] = {}
    for row in gold:
        band = row["triage"]["urgency"]
        counts[band] = counts.get(band, 0) + 1
    majority_rate = max(counts.values()) / len(gold)

    assert distilled["acc_urgency"] > majority_rate, (
        f"acc_urgency {distilled['acc_urgency']} does not beat always predicting the "
        f"majority band ({majority_rate:.4f}) -- the model learned nothing"
    )
