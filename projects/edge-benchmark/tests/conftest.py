"""A built-looking data directory around a tiny stand-in model, for tests without the real
models or the PyTorch environment. Its "pytorch-fp32" variant runs on ONNX Runtime, so
the whole path (child processes, agreement, API) runs anywhere."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from reluai_bench.settings import BenchSettings

FIXTURES = Path(__file__).parent / "fixtures"
TINY = FIXTURES / "tiny_classifier.onnx"


def photo(seed: int, size: tuple[int, int] = (320, 240), fmt: str = "JPEG") -> bytes:
    """A deterministic test photo: smooth colour gradients plus noise."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack(
        [
            (xx * rng.uniform(0.2, 1)) % 255,
            (yy * rng.uniform(0.2, 1)) % 255,
            ((xx + yy) * rng.uniform(0.1, 0.5)) % 255,
        ],
        axis=-1,
    )
    arr = np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(arr).save(out, fmt)
    return out.getvalue()


def _file(path: Path, root: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"path": str(path.relative_to(root)), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}  # fmt: skip


def build_fake(root: Path) -> None:
    (root / "images").mkdir(parents=True)
    (root / "models").mkdir()
    names = []
    for i in range(10):
        name = f"{i:012d}.jpg"
        (root / "images" / name).write_bytes(photo(i))
        names.append(name)
    photos = [
        {"id": i, "file": n, "width": 320, "height": 240, "licence": "CC BY 2.0",
         "licence_url": "https://creativecommons.org/licenses/by/2.0/",
         "source_url": f"https://example.org/photo/{i}"}
        for i, n in enumerate(names)
    ]  # fmt: skip
    index = {"bundle": "test", "split_seed": 7, "calibration": names[:3],
             "agreement": names[3:8], "samples": names[8:], "photos": photos}  # fmt: skip
    (root / "images.json").write_text(json.dumps(index))
    (root / "labels.json").write_text(json.dumps([f"class {i}" for i in range(10)]))
    model_path = root / "models" / "tiny.onnx"
    shutil.copyfile(TINY, model_path)
    model = {
        "id": "tiny",
        "title": "Tiny",
        "timm_name": "tiny",
        "summary": "A stand-in.",
        "params_millions": 0.001,
        "input_size": 224,
        "crop_pct": 0.875,
        "interpolation": "bicubic",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "weights": {"url": "https://example.org/tiny.pth", "sha256": "0" * 64, "bytes": 1,
                    "filename": "tiny.pth"},
        "published_top1": 1.0,
        "published_top5": 5.0,
        "paper": "None.",
        "licence": "MIT",
        "homepage": "https://example.org",
        "files": {v: _file(model_path, root) for v in ("pytorch-fp32", "onnx-fp32", "onnx-int8")},
        "quantisation": {"format": "QDQ", "weights": "int8, per channel",
                         "activations": "uint8, per tensor", "calibration_method": "MinMax",
                         "calibration_photos": 3, "confident_photos": 2,
                         "confident_threshold": 0.5, "target_agreement": 99.0,
                         "all_layers": {"agreement": 100.0, "confident_agreement": 100.0,
                                        "kl": 0.001},
                         "kept_fp32": [],
                         "final": {"agreement": 100.0, "confident_agreement": 100.0,
                                   "kl": 0.001}},
    }  # fmt: skip
    variants = [
        {"id": "pytorch-fp32", "title": "PyTorch FP32", "runtime": "onnxruntime",
         "precision": "fp32", "summary": "stand-in"},
        {"id": "onnx-fp32", "title": "ONNX Runtime FP32", "runtime": "onnxruntime",
         "precision": "fp32", "summary": "stand-in"},
        {"id": "onnx-int8", "title": "ONNX Runtime INT8", "runtime": "onnxruntime",
         "precision": "int8", "summary": "stand-in"},
    ]  # fmt: skip
    registry = {
        "models": [model],
        "variants": variants,
        "tools": {"onnxruntime": "test", "opset": 18},
        "quantisation": {"format": "QDQ", "calibration_photos": 3},
        "photos": {"calibration": 3, "agreement": 5, "samples": 2, "bundle": "test"},
    }
    (root / "models.json").write_text(json.dumps(registry))


@pytest.fixture
def fake_settings(tmp_path: Path) -> BenchSettings:
    root = tmp_path / "bench"
    build_fake(root)
    return BenchSettings(
        data_dir=root,
        torch_python=tmp_path / "no-torch" / "python",
        threads=(1,),
        warmup=1,
        iterations=5,
        latency_images=3,
        throughput_batch=2,
        throughput_seconds=0.05,
        agreement_images=5,
        child_timeout_seconds=60,
        try_timeout_seconds=60,
        try_threads=1,
        try_lease_wait_seconds=5,
    )
