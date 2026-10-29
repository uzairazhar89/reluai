"""Checks against the real models and the PyTorch environment.

Skipped unless ``RELUAI_BENCH_DATA_DIR`` points at a built data directory (``reluai-bench
build``) and ``RELUAI_BENCH_TORCH_PYTHON`` at the PyTorch environment's interpreter, as on a
development machine or inside the image.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from reluai_bench.benchmark import photos, run_suite
from reluai_bench.preprocess import decode, to_input
from reluai_bench.registry import MODELS
from reluai_bench.runner import command
from reluai_bench.settings import BenchSettings

DATA = Path(os.environ.get("RELUAI_BENCH_DATA_DIR", "/nonexistent"))
TORCH = Path(os.environ.get("RELUAI_BENCH_TORCH_PYTHON", "/opt/torch/bin/python"))
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (DATA / "models.json").exists() or not TORCH.exists(),
        reason="needs a built data directory and the PyTorch environment",
    ),
]

TIMM_TRANSFORM = """
import json, sys
import numpy as np
from PIL import Image
from timm.data import create_transform, resolve_data_config
import timm
spec = json.loads(sys.argv[1])
model = timm.create_model(spec["timm_name"], pretrained=False)
cfg = resolve_data_config({}, model=model)
x = create_transform(**cfg)(Image.open(sys.argv[2]).convert("RGB")).numpy()
np.save(sys.argv[3], x)
"""


def _settings() -> BenchSettings:
    return BenchSettings(data_dir=DATA, torch_python=TORCH, threads=(1,), warmup=1,
                         iterations=5, latency_images=3, agreement_images=12,
                         throughput_seconds=0.2)  # fmt: skip


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.id)
def test_preprocessing_matches_timm(model, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    photo = DATA / "images" / photos(_settings())["agreement"][0]
    out = tmp_path / "timm.npy"
    cmd = command("pytorch", TORCH, "reluai_bench.child")[:4]  # interpreter and flags
    args = [*cmd, TIMM_TRANSFORM, json.dumps(model.to_json()), str(photo), str(out)]
    subprocess.run(args, check=True, capture_output=True)  # noqa: S603 - our own script
    ours = to_input(decode(photo.read_bytes()), size=model.input_size, crop_pct=model.crop_pct,
                    interpolation=model.interpolation, mean=model.mean, std=model.std)  # fmt: skip
    assert np.abs(ours[0] - np.load(out)).max() < 1e-5


def test_onnx_fp32_gives_pytorchs_answers() -> None:
    run = run_suite(_settings())
    by = {(a["model"], a["variant"]): a for a in run["agreement"]}
    for model in MODELS:
        fp32 = by[(model.id, "onnx-fp32")]
        assert fp32["top1_agreement"] == 100.0
        assert fp32["max_probability_difference"] < 1e-4
