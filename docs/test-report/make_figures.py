"""Redraws the benchmark figures the report embeds, with labels that cannot overlap.

    uv run --with matplotlib python docs/test-report/make_figures.py [path to "model testing/results"]

The notebooks' own figure put a text label at each point, and the MiniLM variants share an
inference latency, so a dozen labels landed on top of each other. Here every label sits in a
column beside the plot, ordered by score, joined to its point by a leader line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
DEFAULT_RESULTS = HERE.parents[2] / "model testing" / "results"
FAMILY_COLOUR = {"traditional": "#3B6FD4", "embedding": "#E2732E", "deep": "#2E9E6B"}


def rows(results: Path) -> list[dict]:
    data = json.loads((results / "intent_classification.json").read_text(encoding="utf-8"))
    out = []
    for r in data:
        f1, ms = r["metrics"].get("macro_f1"), r.get("infer_ms_per_item")
        if f1 is None or ms is None or r["model"].startswith("dummy"):
            continue  # the dummy baselines sit at 0.003 and would flatten everything else
        out.append({"model": r["model"], "family": r["family"], "f1": f1, "ms": ms,
                    "mb": r.get("model_size_mb")})
    return sorted(out, key=lambda r: r["f1"], reverse=True)


def accuracy_vs_latency(data: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 6.6), dpi=170)
    fig.subplots_adjust(left=0.065, right=0.545, top=0.90, bottom=0.13)
    for r in data:
        ax.scatter(r["ms"], r["f1"], s=52, color=FAMILY_COLOUR.get(r["family"], "#777"),
                   edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_xscale("log")
    ax.set_xlabel("Inference latency, milliseconds per utterance (log scale)")
    ax.set_ylabel("Macro F1")
    ax.set_title("Intent classification: accuracy against the latency it costs", pad=12)
    ax.grid(True, which="both", axis="both", color="#E6E6E6", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    lo, hi = min(r["f1"] for r in data), max(r["f1"] for r in data)
    pad = (hi - lo) * 0.08
    ax.set_ylim(lo - pad, hi + pad)

    # Labels in one column to the right of the axes, evenly spaced in the drawing order, so two
    # models with the same latency cannot collide. A leader line joins each label to its point.
    n = len(data)
    top, bottom = 0.965, 0.045
    step = (top - bottom) / max(n - 1, 1)
    for i, r in enumerate(data):
        y = top - i * step
        size = f", {r['mb']:.2f} MB" if r.get("mb") else ""
        fig.text(0.565, y, f"{r['model']}  ({r['f1']:.4f}{size})", fontsize=8.2, va="center",
                 color="#222", family="DejaVu Sans")
        ax.annotate("", xy=(r["ms"], r["f1"]), xycoords="data",
                    xytext=(0.558, y), textcoords="figure fraction",
                    arrowprops={"arrowstyle": "-", "color": FAMILY_COLOUR.get(r["family"], "#777"),
                                "linewidth": 0.6, "alpha": 0.3,
                                "connectionstyle": "arc3,rad=0.06"}, zorder=2)
    handles = [plt.Line2D([], [], marker="o", linestyle="", markersize=7, color=c, label=f)
               for f, c in FAMILY_COLOUR.items()]
    ax.legend(handles=handles, title="Family", loc="lower left", frameon=False, fontsize=9)
    fig.text(0.065, 0.015, "The two dummy baselines are left out: at 0.003 macro F1 they flatten the rest.",
             fontsize=7.5, color="#666")
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    results = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RESULTS
    if not results.exists():
        raise SystemExit(f"no results directory at {results}; pass the path to 'model testing/results'")
    EV.mkdir(exist_ok=True)
    accuracy_vs_latency(rows(results), EV / "intent_accuracy_vs_latency.png")
