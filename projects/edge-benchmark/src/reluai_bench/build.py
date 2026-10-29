"""Build the lab's data directory at image build time (``reluai-bench build``).

1. Photos: the coco-cc bundle (pinned by SHA-256) is split into calibration, agreement and
   sample photos, and only those are kept (``images.json`` records licence and source).
2. Weights: each model's PyTorch weights, pinned by SHA-256.
3. Export: each model to ONNX, in the PyTorch environment (a child process).
4. Quantise: each ONNX model to 8 bits, calibrated on the calibration photos.
5. ``models.json``: what was built, with the size and SHA-256 of every file and the
   versions of the tools that built it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from reluai_bench import images as image_set
from reluai_bench.quantize import config as quant_config
from reluai_bench.quantize import quantize
from reluai_bench.registry import MODELS, VARIANTS, ModelSpec
from reluai_bench.runner import command
from reluai_core.logging import get_logger
from reluai_datasets.fetch import download, sha256_file

log = get_logger(__name__)
CALIBRATION_METHOD = "MinMax"


def _file(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def fetch_weights(model: ModelSpec, out: Path) -> Path:
    target = out / "weights" / model.weights.filename
    if not (target.exists() and sha256_file(target) == model.weights.sha256):
        download(
            model.weights.url,
            target,
            max_bytes=model.weights.bytes + 1,
            expected_sha256=model.weights.sha256,
        )
    return target


def export(
    model: ModelSpec, weights: Path, out: Path, torch_python: Path, labels: Path | None
) -> dict[str, Any]:
    cmd = [
        *command("pytorch", torch_python, "reluai_bench.export_torch"),
        "--model",
        json.dumps(model.to_json()),
        "--weights",
        str(weights),
        "--out",
        str(out),
    ]
    if labels is not None:
        cmd += ["--labels-out", str(labels)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        raise RuntimeError(f"export of {model.id} failed: {done.stderr.strip()[-2000:]}")
    info: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return info


def build(
    out: Path,
    *,
    torch_python: Path,
    bundle: Path | None = None,
    photo_dir: Path | None = None,
    method: str = CALIBRATION_METHOD,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    if photo_dir is not None:
        index = image_set.from_directory(photo_dir, out)
    else:
        if bundle is None:
            bundle = out / "source" / f"{image_set.BUNDLE}.tar"
            download(
                image_set.BUNDLE_URL,
                bundle,
                max_bytes=image_set.BUNDLE_MAX_BYTES,
                expected_sha256=image_set.BUNDLE_SHA256,
            )
        index = image_set.extract(bundle, out)
    calibration = [out / "images" / f for f in index["calibration"]]

    import onnxruntime

    built: list[dict[str, Any]] = []
    tools: dict[str, Any] = {"onnxruntime": onnxruntime.__version__}
    for i, model in enumerate(MODELS):
        weights = fetch_weights(model, out)
        fp32 = out / "models" / f"{model.id}-fp32.onnx"
        int8 = out / "models" / f"{model.id}-int8.onnx"
        tools |= export(model, weights, fp32, torch_python, out / "labels.json" if i == 0 else None)
        report = quantize(model, fp32, int8, calibration, method)
        files = {"pytorch-fp32": weights, "onnx-fp32": fp32, "onnx-int8": int8}
        built.append(
            {
                **model.to_json(),
                "files": {v.id: _file(files[v.id], out) for v in VARIANTS},
                "quantisation": report,
            }
        )
        log.info("bench.model_built", model=model.id, kept_fp32=len(report["kept_fp32"]),
                 agreement=report["final"]["agreement"])  # fmt: skip

    import onnx

    tools["onnx"] = onnx.__version__
    registry = {
        "models": built,
        "variants": [
            {"id": v.id, "title": v.title, "runtime": v.runtime, "precision": v.precision,
             "summary": v.summary}
            for v in VARIANTS
        ],
        "tools": tools,
        "quantisation": quant_config(method) | {"calibration_photos": len(calibration)},
        "photos": {k: len(index[k]) for k in ("calibration", "agreement", "samples")}
        | {"bundle": index["bundle"]},
    }  # fmt: skip
    (out / "models.json").write_text(json.dumps(registry, indent=1), encoding="utf-8")
    return registry
