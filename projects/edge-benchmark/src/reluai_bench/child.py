"""Entry point of the isolated benchmark process (``python -m reluai_bench.child``).

Every measurement runs in a fresh process of its own, so one variant's memory, threads
and caches never colour another's numbers, and an uploaded photo is only ever decoded
in a process with no secrets and capped resources. The same file runs under the
application's Python (ONNX Runtime) and under the separate PyTorch environment, so it
imports only the standard library, NumPy and Pillow at module level.

Protocol: stdin carries one line of JSON options followed by ``payload_bytes`` bytes
(an image, for ``sanitise`` and ``classify``); stdout carries one JSON line, either
``{"ok": true, ...}`` or ``{"ok": false, "code": ..., "message": ...}``. Anything a
library prints goes to stderr, so it cannot corrupt the protocol.

Modes:

* ``sanitise``: decode an uploaded image defensively and return it re-encoded as JPEG;
* ``benchmark``: load one variant and measure latency (preprocessing, inference and
  postprocessing separately), CPU use, batch throughput, memory, and the probabilities it
  gives each photo of the agreement set;
* ``classify``: run one photo through one or more variants of a model, with timings.
"""

from __future__ import annotations

import base64
import json
import os
import resource
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from reluai_bench.preprocess import (
    ImageRejectedError,
    decode,
    sanitise,
    softmax,
    to_input,
    top_k,
)

Infer = Callable[[np.ndarray], np.ndarray]


def _limit(kind: int, value: int) -> None:
    _soft, hard = resource.getrlimit(kind)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    resource.setrlimit(kind, (value, value if hard == resource.RLIM_INFINITY else hard))


def _memory() -> dict[str, float]:
    """Current and peak resident memory of this process, in MB."""
    out: dict[str, float] = {}
    try:
        status = Path("/proc/self/status").read_text()
    except OSError:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        return {"rss": round(peak, 1), "peak": round(peak, 1)}
    for line in status.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key = "rss" if line.startswith("VmRSS") else "peak"
            out[key] = round(int(line.split()[1]) / 1024, 1)
    return out


def _ms(ns: int) -> float:
    return ns / 1e6


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "p50": round(statistics.median(ordered), 3),
        "p95": round(p95, 3),
        "mean": round(statistics.fmean(ordered), 3),
        "min": round(ordered[0], 3),
    }


# --------------------------------------------------------------------------- engines
def _import_runtime(runtime: str) -> dict[str, str]:
    if runtime == "pytorch":
        import timm
        import torch

        return {"torch": torch.__version__.split("+")[0], "timm": timm.__version__}
    import onnxruntime

    return {"onnxruntime": onnxruntime.__version__}


def _load(runtime: str, model: dict[str, Any], path: str, threads: int) -> Infer:
    if runtime == "pytorch":
        import timm
        import torch

        torch.set_num_threads(threads)
        net = timm.create_model(model["timm_name"], pretrained=False)
        net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        net.eval()

        def infer_torch(x: np.ndarray) -> np.ndarray:
            with torch.inference_mode():
                out: np.ndarray = net(torch.from_numpy(x)).numpy()
            return out

        return infer_torch

    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name

    def infer_ort(x: np.ndarray) -> np.ndarray:
        out: np.ndarray = session.run(None, {name: x})[0]
        return out

    return infer_ort


def _prepare(model: dict[str, Any]) -> Callable[[bytes], np.ndarray]:
    def prepare(blob: bytes) -> np.ndarray:
        return to_input(
            decode(blob),
            size=int(model["input_size"]),
            crop_pct=float(model["crop_pct"]),
            interpolation=str(model["interpolation"]),
            mean=tuple(model["mean"]),
            std=tuple(model["std"]),
        )

    return prepare


def _once(prepare: Callable[[bytes], np.ndarray], infer: Infer, blob: bytes) -> tuple[
    float, float, float, list[tuple[int, float]]
]:  # fmt: skip
    t0 = time.perf_counter_ns()
    x = prepare(blob)
    t1 = time.perf_counter_ns()
    logits = infer(x)
    t2 = time.perf_counter_ns()
    top = top_k(softmax(logits[0].astype(np.float32)))
    t3 = time.perf_counter_ns()
    return _ms(t1 - t0), _ms(t2 - t1), _ms(t3 - t2), top


# --------------------------------------------------------------------------- modes
def benchmark(opts: dict[str, Any]) -> dict[str, Any]:
    model, var, threads = opts["model"], opts["variant"], int(opts["threads"])
    memory = {"start": _memory()["rss"]}
    t = time.perf_counter_ns()
    versions = _import_runtime(var["runtime"])
    import_ms = _ms(time.perf_counter_ns() - t)
    memory["after_import"] = _memory()["rss"]
    t = time.perf_counter_ns()
    infer = _load(var["runtime"], model, var["path"], threads)
    load_ms = _ms(time.perf_counter_ns() - t)
    memory["after_load"] = _memory()["rss"]
    prepare = _prepare(model)

    blobs = [Path(p).read_bytes() for p in opts["latency_images"]]
    for i in range(int(opts["warmup"])):
        _once(prepare, infer, blobs[i % len(blobs)])
    pre: list[float] = []
    inf: list[float] = []
    post: list[float] = []
    total: list[float] = []
    cpu0, wall0 = os.times(), time.perf_counter()
    for i in range(int(opts["iterations"])):
        a, b, c, _ = _once(prepare, infer, blobs[i % len(blobs)])
        pre.append(a)
        inf.append(b)
        post.append(c)
        total.append(a + b + c)
    cpu1, wall1 = os.times(), time.perf_counter()
    cpu_seconds = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)

    batch = int(opts["throughput_batch"])
    xb = np.concatenate([prepare(blobs[i % len(blobs)]) for i in range(batch)])
    infer(xb)
    infer(xb)
    runs, started = 0, time.perf_counter()
    while runs < 3 or time.perf_counter() - started < float(opts["throughput_seconds"]):
        infer(xb)
        runs += 1
    elapsed = time.perf_counter() - started

    probs = []
    for p in opts.get("agreement_images", []):
        x = prepare(Path(p).read_bytes())
        probs.append(softmax(infer(x)[0].astype(np.float32)).astype(np.float32))
    encoded = base64.b64encode(np.stack(probs).tobytes()).decode() if probs else ""

    memory |= {"end": _memory()["rss"], "peak": _memory()["peak"]}
    return {
        "versions": versions,
        "import_ms": round(import_ms, 1),
        "load_ms": round(load_ms, 1),
        "latency_ms": {
            "total": _stats(total),
            "preprocess": _stats(pre),
            "inference": _stats(inf),
            "postprocess": _stats(post),
        },
        "iterations": len(total),
        "warmup": int(opts["warmup"]),
        "cpu_percent": round(100 * cpu_seconds / (wall1 - wall0), 1),
        "throughput": {
            "batch": batch,
            "runs": runs,
            "images_per_second": round(batch * runs / elapsed, 2),
        },
        "memory_mb": memory,
        "agreement": {"count": len(probs), "classes": int(probs[0].shape[0]) if probs else 0,
                      "probs_f32": encoded},
    }  # fmt: skip


def classify(opts: dict[str, Any], payload: bytes) -> dict[str, Any]:
    model, threads, runs = opts["model"], int(opts["threads"]), int(opts.get("runs", 5))
    variants = opts["variants"]
    t = time.perf_counter_ns()
    versions = _import_runtime(variants[0]["runtime"])
    import_ms = _ms(time.perf_counter_ns() - t)
    prepare = _prepare(model)
    results = []
    for var in variants:
        t = time.perf_counter_ns()
        infer = _load(var["runtime"], model, var["path"], threads)
        load_ms = _ms(time.perf_counter_ns() - t)
        first = _once(prepare, infer, payload)
        warm = [_once(prepare, infer, payload) for _ in range(runs)]
        results.append(
            {
                "variant": var["id"],
                "load_ms": round(load_ms, 1),
                "first": {
                    "preprocess": round(first[0], 2),
                    "inference": round(first[1], 2),
                    "postprocess": round(first[2], 2),
                },
                "warm": {
                    "preprocess": round(statistics.median(w[0] for w in warm), 2),
                    "inference": round(statistics.median(w[1] for w in warm), 2),
                    "postprocess": round(statistics.median(w[2] for w in warm), 2),
                },
                "top5": [{"index": i, "probability": round(p, 5)} for i, p in warm[-1][3]],
            }
        )
    return {
        "versions": versions,
        "import_ms": round(import_ms, 1),
        "results": results,
        "memory_mb": _memory(),
    }


def main() -> int:
    out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)  # stray prints from libraries go to stderr

    def emit(event: dict[str, Any]) -> None:
        out.write(json.dumps(event, separators=(",", ":")) + "\n")

    stdin = sys.stdin.buffer
    opts = json.loads(stdin.readline(1 << 20) or b"{}")
    if opts.get("memory_mb"):
        _limit(resource.RLIMIT_AS, int(opts["memory_mb"]) * 1024 * 1024)
    _limit(resource.RLIMIT_CPU, int(opts.get("cpu_seconds", 120)))
    # No files may be written, beyond PyTorch's probe of its private temporary directory.
    _limit(resource.RLIMIT_FSIZE, int(opts.get("file_mb", 0)) * 1024 * 1024)
    payload = stdin.read(int(opts.get("payload_bytes", 0)))
    mode = opts.get("mode")
    try:
        if mode == "sanitise":
            clean, info = sanitise(
                payload, max_pixels=int(opts["max_pixels"]), side=int(opts["side"])
            )
            emit({"ok": True, "jpeg": base64.b64encode(clean).decode(), "info": info})
        elif mode == "benchmark":
            emit({"ok": True, **benchmark(opts)})
        elif mode == "classify":
            emit({"ok": True, **classify(opts, payload)})
        else:
            emit({"ok": False, "code": "bad_request", "message": f"unknown mode {mode!r}"})
    except ImageRejectedError as exc:
        emit({"ok": False, "code": exc.code, "message": exc.message})
    except MemoryError:
        emit({"ok": False, "code": "out_of_memory", "message": "Ran out of memory."})
    return 0


if __name__ == "__main__":
    sys.exit(main())
