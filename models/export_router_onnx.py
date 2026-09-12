"""Export the fine-tuned EfficientNet-B0 router classifier (.pt, LFS) to ONNX.

The checkpoint carries state_dict, classes, img_size, mean and std (model testing,
notebook 02), so preprocessing is rebuilt from it rather than hard-coded. Runs in the image
build (and CI) with CPU torch; the runtime image ships only onnxruntime.

Usage: python models/export_router_onnx.py <checkpoint.pt> <out_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
import torchvision
from torch import nn


def main(src: str, out: str) -> None:
    ckpt = torch.load(src, map_location="cpu", weights_only=False)
    classes = [str(c) for c in ckpt["classes"]]
    size = int(ckpt.get("img_size", 224))
    model = torchvision.models.efficientnet_b0(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, torch.randn(1, 3, size, size), out_dir / "router.onnx", input_names=["input"],
                      output_names=["logits"], dynamic_axes={"input": {0: "batch"}}, opset_version=17)
    meta = {"classes": classes, "img_size": size,
            "mean": list(ckpt.get("mean", [0.485, 0.456, 0.406])), "std": list(ckpt.get("std", [0.229, 0.224, 0.225]))}
    (out_dir / "router_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"exported {len(classes)} classes at {size}px to {out_dir}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
