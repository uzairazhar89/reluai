"""Run the benchmark suite: every model × variant × thread count, each in its own process.

For each combination a fresh child process loads the variant and measures, over the same
photos and with the same preprocessing:

* latency per photo at batch size 1, split into preprocessing (decode, resize, normalise),
  inference and postprocessing (softmax, top 5), after a warm-up: median, 95th
  percentile, mean and minimum;
* CPU use during those runs (CPU time over wall time: 200% means two cores busy);
* throughput at a fixed batch size;
* memory: resident set after importing the runtime, after loading the model, and peak;
* start-up: time to import the runtime and to load the model.

At the highest thread count each variant also classifies the agreement photos, and its
answers are compared with PyTorch FP32's: same top class (on every photo, and on the photos
where PyTorch is at least 50% sure), overlap of the top five, and the largest difference in
any class probability.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import PIL

from reluai_bench.hardware import fingerprint
from reluai_bench.quantize import CONFIDENT
from reluai_bench.registry import REFERENCE_VARIANT
from reluai_bench.runner import ChildLimits, command, run_child
from reluai_bench.settings import BenchSettings

Progress = Callable[[str], None]


class NotBuiltError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _load_json(path: Path, mtime: float) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json(path: Path) -> Any:
    if not path.exists():
        raise NotBuiltError(f"{path} is missing; run `reluai-bench build` first")
    return _load_json(path, path.stat().st_mtime)


def registry(settings: BenchSettings) -> dict[str, Any]:
    reg: dict[str, Any] = _json(settings.registry_path)
    return reg


def photos(settings: BenchSettings) -> dict[str, Any]:
    index: dict[str, Any] = _json(settings.data_dir / "images.json")
    return index


def labels(settings: BenchSettings) -> list[str]:
    names: list[str] = _json(settings.data_dir / "labels.json")
    return names


def limits(settings: BenchSettings, runtime: str) -> ChildLimits:
    return ChildLimits(
        timeout_seconds=settings.child_timeout_seconds,
        cpu_seconds=settings.child_cpu_seconds,
        memory_mb=None if runtime == "pytorch" else settings.child_memory_mb,
        file_mb=1 if runtime == "pytorch" else 0,
    )


def variant_options(settings: BenchSettings, model: dict[str, Any], variant: dict[str, Any]) -> (
    dict[str, Any]
):  # fmt: skip
    path = settings.data_dir / model["files"][variant["id"]]["path"]
    return {"id": variant["id"], "runtime": variant["runtime"], "path": str(path)}


def _agreement(ref: np.ndarray, other: np.ndarray) -> dict[str, float]:
    top1_ref, top1 = ref.argmax(axis=1), other.argmax(axis=1)
    top5_ref = np.argsort(-ref, axis=1)[:, :5]
    top5 = np.argsort(-other, axis=1)[:, :5]
    overlap = [len(set(a) & set(b)) / 5 for a, b in zip(top5_ref, top5, strict=True)]
    rows = np.arange(len(ref))
    confident = ref.max(axis=1) >= CONFIDENT
    same = top1_ref == top1
    return {
        "photos": len(ref),
        "top1_agreement": round(100 * float(np.mean(same)), 2),
        "confident_photos": int(confident.sum()),
        "top1_agreement_confident": round(100 * float(np.mean(same[confident])), 2)
        if confident.any()
        else 0.0,
        "top5_overlap": round(100 * float(np.mean(overlap)), 2),
        "reference_top1_in_top5": round(
            100 * float(np.mean([t in row for t, row in zip(top1_ref, top5, strict=True)])), 2
        ),
        "max_probability_difference": float(np.max(np.abs(ref - other))),
        "mean_top1_probability_difference": float(
            np.mean(np.abs(ref[rows, top1_ref] - other[rows, top1_ref]))
        ),
    }


def run_suite(
    settings: BenchSettings,
    *,
    models: list[str] | None = None,
    threads: tuple[int, ...] | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    reg = registry(settings)
    index = photos(settings)
    image_dir = settings.data_dir / "images"
    agreement_photos = [str(image_dir / f) for f in index["agreement"][: settings.agreement_images]]
    latency_photos = agreement_photos[: settings.latency_images]
    thread_counts = tuple(sorted(threads or settings.threads))
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []
    agreement: list[dict[str, Any]] = []
    versions: dict[str, str] = {"numpy": np.__version__, "pillow": PIL.__version__}
    for model in reg["models"]:
        if models and model["id"] not in models:
            continue
        probs: dict[str, np.ndarray] = {}
        for variant in reg["variants"]:
            for n in thread_counts:
                if progress:
                    progress(f"{model['id']} {variant['id']} threads={n}")
                last = n == thread_counts[-1]
                opts = {
                    "mode": "benchmark",
                    "model": model,
                    "variant": variant_options(settings, model, variant),
                    "threads": n,
                    "warmup": settings.warmup,
                    "iterations": settings.iterations,
                    "latency_images": latency_photos,
                    "throughput_batch": settings.throughput_batch,
                    "throughput_seconds": settings.throughput_seconds,
                    "agreement_images": agreement_photos if last else [],
                }
                answer = run_child(
                    command(variant["runtime"], settings.torch_python),
                    opts,
                    limits(settings, variant["runtime"]),
                    threads=n,
                )
                versions |= answer["versions"]
                agree = answer.pop("agreement")
                if agree["count"]:
                    raw = np.frombuffer(base64.b64decode(agree["probs_f32"]), dtype=np.float32)
                    probs[variant["id"]] = raw.reshape(agree["count"], agree["classes"])
                results.append(
                    {
                        "model": model["id"],
                        "variant": variant["id"],
                        "threads": n,
                        "size_bytes": model["files"][variant["id"]]["bytes"],
                        **{
                            k: answer[k]
                            for k in (
                                "import_ms",
                                "load_ms",
                                "latency_ms",
                                "iterations",
                                "warmup",
                                "cpu_percent",
                                "throughput",
                                "memory_mb",
                            )
                        },
                    }
                )
        ref = probs.get(REFERENCE_VARIANT)
        for vid, p in probs.items():
            if ref is not None and vid != REFERENCE_VARIANT:
                row = {"model": model["id"], "variant": vid, "reference": REFERENCE_VARIANT}
                agreement.append(row | _agreement(ref, p))
    return {
        "started_at": started.isoformat(),
        "duration_seconds": round(time.perf_counter() - t0, 1),
        "hardware": fingerprint(versions),
        "protocol": {
            "threads": list(thread_counts),
            "warmup": settings.warmup,
            "iterations": settings.iterations,
            "latency_photos": len(latency_photos),
            "throughput_batch": settings.throughput_batch,
            "throughput_seconds": settings.throughput_seconds,
            "agreement_photos": len(agreement_photos),
            "process": "one fresh isolated process per model, variant and thread count",
        },
        "build": {
            "tools": reg["tools"],
            "quantisation": reg["quantisation"],
            "photos": reg["photos"],
        },
        "results": results,
        "agreement": agreement,
    }
