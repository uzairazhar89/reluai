"""Static 8-bit quantisation of an exported ONNX classifier (image build time only).

Weights are quantised per output channel to signed 8-bit; activations to unsigned 8-bit
with ranges observed while the model runs on the calibration photos (QDQ format, which
ONNX Runtime fuses into integer kernels). This runs under the same ONNX Runtime version
that later serves the model; it needs the ``onnx`` package (dependency group ``quantize``).

Quantising every layer can ruin a model: an activation whose channels span very different
ranges gets one 8-bit range for all of them, and the small channels keep only a few distinct
values. So the result is checked on the calibration photos: on those where the 32-bit model is
confident (top class at least 50%), does the 8-bit model pick the same top class? (On photos
showing nothing in ImageNet's classes the top answer is a near-tie that any change flips, so
they say little about damage.) When it falls short of ``target`` the layers that hurt most
are found and kept in 32-bit:

1. sensitivity: quantise one layer at a time, everything else in 32-bit, and measure how
   far the output moves (KL divergence from the 32-bit probabilities);
2. keep the most sensitive 1, 2, 3, 4, 6, 8, … layers in 32-bit until the agreement on the
   confident calibration photos reaches the target.

The report records the all-layers result, the layers kept in 32-bit and why. Agreement on
the calibration photos chose the layers, so the published agreement is measured separately,
on the agreement photos, by the benchmark.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from reluai_bench.preprocess import decode, softmax, to_input
from reluai_bench.registry import ModelSpec

METHODS = ("MinMax", "Entropy", "Percentile")
STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64)
CONFIDENT = 0.5  # a photo counts towards the check if the 32-bit top class has this probability
# Operators ONNX Runtime can run on 8-bit tensors; each is a candidate for staying 32-bit.
CANDIDATE_OPS = {
    "Conv", "Gemm", "MatMul", "Add", "Mul", "Relu", "Clip", "HardSigmoid", "HardSwish",
    "Sigmoid", "GlobalAveragePool", "AveragePool", "MaxPool", "ReduceMean", "Concat",
}  # fmt: skip


def config(method: str) -> dict[str, Any]:
    return {
        "format": "QDQ",
        "weights": "int8, per channel",
        "activations": "uint8, per tensor",
        "calibration_method": method,
    }


def _inputs(model: ModelSpec, photos: list[Path]) -> list[np.ndarray]:
    return [
        to_input(
            decode(p.read_bytes()),
            size=model.input_size,
            crop_pct=model.crop_pct,
            interpolation=model.interpolation,
            mean=model.mean,
            std=model.std,
        )
        for p in photos
    ]


def _probs(path: Path, xs: list[np.ndarray]) -> np.ndarray:
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    session = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    return np.stack([softmax(session.run(None, {name: x})[0][0]) for x in xs])


def _score(ref: np.ndarray, probs: np.ndarray) -> dict[str, float]:
    """Top-1 agreement % on all photos and on the confident ones, and the mean KL divergence
    of the probabilities from the reference."""
    same = ref.argmax(1) == probs.argmax(1)
    confident = ref.max(1) >= CONFIDENT
    kl = float(np.mean(np.sum(ref * (np.log(ref + 1e-9) - np.log(probs + 1e-9)), axis=1)))
    return {
        "agreement": round(float(np.mean(same)) * 100, 2),
        "confident_agreement": round(float(np.mean(same[confident])) * 100, 2)
        if confident.any()
        else 0.0,
        "kl": round(kl, 5),
    }


def _rank(score: dict[str, float]) -> tuple[float, float, float]:
    return (score["confident_agreement"], score["agreement"], -score["kl"])


def quantize(
    model: ModelSpec,
    fp32: Path,
    out: Path,
    photos: list[Path],
    method: str,
    *,
    target: float = 99.0,
) -> dict[str, Any]:
    import onnx
    from onnxruntime.quantization import (
        CalibrationDataReader,
        CalibrationMethod,
        QuantFormat,
        QuantType,
        quantize_static,
    )
    from onnxruntime.quantization.shape_inference import quant_pre_process

    xs = _inputs(model, photos)

    class Reader(CalibrationDataReader):  # type: ignore[misc]
        def __init__(self) -> None:
            self._it: Iterator[dict[str, np.ndarray]] = ({"input": x} for x in xs)

        def get_next(self) -> dict[str, np.ndarray] | None:
            return next(self._it, None)

    with tempfile.TemporaryDirectory() as tmp:
        prepared = Path(tmp) / "prepared.onnx"
        cache = Path(tmp) / "calibration.json"
        trial = Path(tmp) / "trial.onnx"
        quant_pre_process(str(fp32), str(prepared), skip_symbolic_shape=True)
        graph = onnx.load(str(prepared))
        names: set[str] = set()
        for i, node in enumerate(graph.graph.node):  # the exporter leaves some nodes unnamed
            if not node.name or node.name in names:
                node.name = f"{node.op_type}_{i}"
            names.add(node.name)
        onnx.save(graph, str(prepared))
        ref = _probs(prepared, xs)

        def build(path: Path, **kwargs: Any) -> dict[str, float]:
            quantize_static(
                str(prepared),
                str(path),
                Reader(),
                quant_format=QuantFormat.QDQ,
                per_channel=True,
                activation_type=QuantType.QUInt8,
                weight_type=QuantType.QInt8,
                calibrate_method=getattr(CalibrationMethod, method),
                calibration_cache_path=cache,  # observed once, reused by every trial
                **kwargs,
            )
            return _score(ref, _probs(path, xs))

        out.parent.mkdir(parents=True, exist_ok=True)
        naive = build(out)
        report: dict[str, Any] = {
            **config(method),
            "calibration_photos": len(xs),
            "confident_photos": int(np.sum(ref.max(1) >= CONFIDENT)),
            "confident_threshold": CONFIDENT,
            "target_agreement": target,
            "all_layers": naive,
            "kept_fp32": [],
            "final": naive,
        }
        if naive["confident_agreement"] >= target:
            return report

        nodes = [n for n in graph.graph.node if n.op_type in CANDIDATE_OPS]
        sensitivity = []
        for node in nodes:
            alone = build(trial, nodes_to_quantize=[node.name])
            sensitivity.append((alone["kl"], node.name, node.op_type))
        sensitivity.sort(reverse=True)
        best, chosen = naive, 0
        steps = []
        for k in (s for s in STEPS if s <= len(nodes) // 2):
            score = build(trial, nodes_to_exclude=[name for _, name, _ in sensitivity[:k]])
            steps.append({"kept_fp32": k, **score})
            if _rank(score) > _rank(best):
                best, chosen = score, k
            if score["confident_agreement"] >= target:
                break
        if chosen:
            excluded = [name for _, name, _ in sensitivity[:chosen]]
            build(out, nodes_to_exclude=excluded)
        report |= {
            "candidates": len(nodes),
            "kept_fp32": [
                {"node": name, "op": op, "kl_when_alone": round(kl, 5)}
                for kl, name, op in sensitivity[:chosen]
            ],
            "steps": steps,
            "final": best,
        }
        return report
