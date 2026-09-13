"""Export TriageModel's distilled head (.pt) to plain numpy so the triage service needs no torch.

    <python with torch> ml/export_triage.py [src.pt] [dst_dir]

Writes triage_multitask.npz (weights) and triage_multitask.json (label maps, signal order,
embedding model). The Airflow DAG runs this after every retrain.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "TriageModel" / "artifacts" / "triage_multitask.pt"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "services" / "triage" / "models"


def main() -> None:
    ck = torch.load(SRC, map_location="cpu", weights_only=False)
    sd = ck["state_dict"]
    arrays = {
        "w1": sd["net"]["0.weight"].numpy(), "b1": sd["net"]["0.bias"].numpy(),
        "ws": sd["score_head"]["weight"].numpy(), "bs": sd["score_head"]["bias"].numpy(),
    }
    for target in ck["label_maps"]:
        arrays[f"w_{target}"] = sd["heads"][f"{target}.weight"].numpy()
        arrays[f"b_{target}"] = sd["heads"][f"{target}.bias"].numpy()
    DST.mkdir(parents=True, exist_ok=True)
    np.savez(DST / "triage_multitask.npz", **arrays)
    (DST / "triage_multitask.json").write_text(json.dumps({
        "label_maps": ck["label_maps"], "signal_names": ck["signal_names"],
        "embedding_model": ck["embedding_model"], "input_dim": ck["input_dim"], "source": SRC.name,
    }, indent=2), encoding="utf-8")
    print(f"exported {SRC.name} -> {DST} ({ck['input_dim']} inputs, heads {list(ck['label_maps'])})")


if __name__ == "__main__":
    main()
