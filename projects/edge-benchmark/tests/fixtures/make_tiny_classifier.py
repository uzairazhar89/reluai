"""Writes tiny_classifier.onnx, a stand-in model for tests (needs the ``onnx`` package).

A 3×3 convolution (stride 8) with ReLU, global average pooling and a linear layer to ten
classes, with fixed pseudo-random weights and a dynamic batch size. It takes the same
input as the real models (N×3×224×224), so the whole measuring path runs without them.

    uv run --group quantize python projects/edge-benchmark/tests/fixtures/make_tiny_classifier.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

rng = np.random.default_rng(0)
w = numpy_helper.from_array(rng.normal(0, 0.5, (8, 3, 3, 3)).astype(np.float32), "w")
b = numpy_helper.from_array(rng.normal(0, 0.1, (8,)).astype(np.float32), "b")
fc = numpy_helper.from_array(rng.normal(0, 1.0, (10, 8)).astype(np.float32), "fc")
fcb = numpy_helper.from_array(rng.normal(0, 0.1, (10,)).astype(np.float32), "fcb")
nodes = [
    helper.make_node("Conv", ["input", "w", "b"], ["c"], strides=[8, 8], pads=[1, 1, 1, 1]),
    helper.make_node("Relu", ["c"], ["r"]),
    helper.make_node("GlobalAveragePool", ["r"], ["p"]),
    helper.make_node("Flatten", ["p"], ["f"]),
    helper.make_node("Gemm", ["f", "fc", "fcb"], ["logits"], transB=1),
]
graph = helper.make_graph(
    nodes,
    "tiny",
    [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["batch", 3, 224, 224])],
    [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch", 10])],
    [w, b, fc, fcb],
)
model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], producer_name="tests")
model.ir_version = 9
onnx.checker.check_model(model)
onnx.save(model, Path(__file__).with_name("tiny_classifier.onnx"))
