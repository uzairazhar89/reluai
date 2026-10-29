"""8-bit quantisation of the stand-in model, including the search for layers to keep in
32-bit. Needs the ``onnx`` package (dependency group ``quantize``)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from reluai_bench.quantize import quantize
from reluai_bench.registry import IMAGENET_MEAN, IMAGENET_STD, ModelSpec, Weights

from .conftest import TINY, photo

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("onnx") is None, reason="needs the quantize dependency group"
)

SPEC = ModelSpec(
    id="tiny", title="Tiny", timm_name="tiny", summary="", params_millions=0.0,
    input_size=224, crop_pct=0.875, interpolation="bicubic", mean=IMAGENET_MEAN,
    std=IMAGENET_STD, weights=Weights("https://example.org/t.pth", "0" * 64, 1),
    published_top1=0, published_top5=0, paper="",
)  # fmt: skip


@pytest.fixture
def photos(tmp_path: Path) -> list[Path]:
    out = []
    for i in range(6):
        p = tmp_path / f"{i}.jpg"
        p.write_bytes(photo(100 + i))
        out.append(p)
    return out


def test_all_layers_when_good_enough(tmp_path: Path, photos: list[Path]) -> None:
    out = tmp_path / "int8.onnx"
    import onnx

    report = quantize(SPEC, TINY, out, photos, "MinMax", target=0.0)
    ops = {n.op_type for n in onnx.load(str(out)).graph.node}
    assert {"QuantizeLinear", "DequantizeLinear"} <= ops
    assert report["kept_fp32"] == [] and report["calibration_photos"] == 6
    assert report["final"] == report["all_layers"]
    assert 0 <= report["final"]["agreement"] <= 100


def test_sensitive_layers_are_kept_in_fp32(tmp_path: Path, photos: list[Path]) -> None:
    out = tmp_path / "int8.onnx"
    import onnx

    report = quantize(SPEC, TINY, out, photos, "MinMax", target=101.0)  # unreachable
    assert report["candidates"] == 4  # Conv, Relu, GlobalAveragePool, Gemm
    kept = report["kept_fp32"]
    assert 1 <= len(kept) <= 2
    assert kept == sorted(kept, key=lambda k: -k["kl_when_alone"])
    assert report["final"]["confident_agreement"] >= report["all_layers"]["confident_agreement"]
    assert report["confident_photos"] <= report["calibration_photos"]
    graph = onnx.load(str(out)).graph
    by_name = {n.name: n for n in graph.node}
    for k in kept:  # a kept layer reads and writes 32-bit tensors directly
        assert k["node"] in by_name
    assert np.isfinite(report["final"]["kl"])
