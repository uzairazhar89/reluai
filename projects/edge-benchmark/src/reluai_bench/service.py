"""The lab for the API: stored runs, the registry, sample photos and "Try it".

"Try it" runs one photo through the three variants of a model, synchronously and under
the global CPU lease (a few seconds of work, most of it starting PyTorch). An upload is
first decoded and re-encoded as a plain JPEG in an isolated process; the variants then
read only that clean copy, in two more isolated processes (one per runtime). Nothing is
stored.
"""

from __future__ import annotations

import base64
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select

from reluai_bench.benchmark import labels, photos, registry, variant_options
from reluai_bench.hardware import fingerprint
from reluai_bench.models import BenchmarkRun
from reluai_bench.registry import REFERENCE_VARIANT, TIMM_RESULTS
from reluai_bench.runner import ChildError, ChildLimits, command, run_child
from reluai_bench.schemas import (
    BenchHeadlineOut,
    BenchModelOut,
    BenchRegistryOut,
    BenchRunOut,
    BenchRunSummaryOut,
    BenchSampleOut,
    BenchTryOut,
)
from reluai_bench.settings import BenchSettings
from reluai_core.cpu_lease import cpu_lease
from reluai_core.db import Database
from reluai_core.logging import get_logger

log = get_logger(__name__)
SAMPLE_NAME = re.compile(r"^[\w-]{1,40}\.jpg$")
REJECTED = {"not_an_image", "unsupported", "too_many_pixels"}


class BenchError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- runs
def record_run(db: Database, run: dict[str, Any], *, label: str) -> BenchmarkRun:
    row = BenchmarkRun(
        label=label,
        duration_seconds=run["duration_seconds"],
        hardware_id=run["hardware"]["id"],
        hardware=run["hardware"],
        protocol=run["protocol"],
        build=run["build"],
        results=run["results"],
        agreement=run["agreement"],
    )
    with db.session() as s:
        s.add(row)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row


def latest_run(db: Database) -> BenchRunOut | None:
    with db.session() as s:
        row = s.scalars(select(BenchmarkRun).order_by(BenchmarkRun.ran_at.desc()).limit(1)).first()
        return BenchRunOut.model_validate(row, from_attributes=True) if row else None


def history(db: Database, limit: int) -> list[BenchRunSummaryOut]:
    with db.session() as s:
        rows = s.scalars(
            select(BenchmarkRun).order_by(BenchmarkRun.ran_at.desc()).limit(limit)
        ).all()
        out = []
        for row in rows:
            top = max((r["threads"] for r in row.results), default=1)
            out.append(
                BenchRunSummaryOut(
                    id=row.id,
                    ran_at=row.ran_at,
                    label=row.label,
                    hardware_id=row.hardware_id,
                    cpu_model=str(row.hardware.get("cpu", {}).get("model", "")),
                    headline=[
                        BenchHeadlineOut(
                            model=r["model"],
                            variant=r["variant"],
                            threads=r["threads"],
                            inference_p50_ms=r["latency_ms"]["inference"]["p50"],
                            total_p50_ms=r["latency_ms"]["total"]["p50"],
                        )
                        for r in row.results
                        if r["threads"] == top
                    ],
                )
            )
        return out


# --------------------------------------------------------------------------- registry
def registry_out(settings: BenchSettings) -> BenchRegistryOut:
    reg = registry(settings)
    return BenchRegistryOut(
        models=[
            BenchModelOut.model_validate(
                {
                    **{
                        k: m[k]
                        for k in (
                            "id",
                            "title",
                            "summary",
                            "params_millions",
                            "input_size",
                            "crop_pct",
                            "published_top1",
                            "published_top5",
                            "paper",
                            "licence",
                            "homepage",
                        )
                    },
                    "weights_url": m["weights"]["url"],
                    "quantisation": m["quantisation"],
                    "files": {
                        v: {"bytes": f["bytes"], "sha256": f["sha256"]}
                        for v, f in m["files"].items()
                    },
                }
            )
            for m in reg["models"]
        ],
        variants=reg["variants"],
        tools=reg["tools"],
        quantisation=reg["quantisation"],
        photos=reg["photos"],
        published_accuracy_source=TIMM_RESULTS,
    )


def samples(settings: BenchSettings) -> list[BenchSampleOut]:
    index = photos(settings)
    by_file = {p["file"]: p for p in index["photos"]}
    return [
        BenchSampleOut(
            name=name,
            url=f"/api/bench/samples/{name}",
            width=by_file[name]["width"],
            height=by_file[name]["height"],
            licence=by_file[name]["licence"],
            licence_url=by_file[name]["licence_url"],
            source_url=by_file[name]["source_url"],
        )
        for name in index["samples"]
    ]


def sample_bytes(settings: BenchSettings, name: str) -> bytes:
    if not SAMPLE_NAME.match(name) or name not in photos(settings)["samples"]:
        raise BenchError(404, "not_found", "No such sample photo.")
    return (settings.data_dir / "images" / name).read_bytes()


@lru_cache(maxsize=1)
def hardware_id() -> str:
    return str(fingerprint()["id"])


# --------------------------------------------------------------------------- try it
def _limits(settings: BenchSettings, runtime: str) -> ChildLimits:
    return ChildLimits(
        timeout_seconds=settings.try_timeout_seconds,
        cpu_seconds=max(10, int(settings.try_timeout_seconds) * settings.try_threads),
        memory_mb=None if runtime == "pytorch" else settings.child_memory_mb,
        file_mb=1 if runtime == "pytorch" else 0,
    )


def sanitise(settings: BenchSettings, data: bytes) -> tuple[bytes, dict[str, Any]]:
    if not data:
        raise BenchError(422, "empty_file", "The file is empty.")
    if len(data) > settings.try_max_bytes:
        mb = settings.try_max_bytes // (1024 * 1024)
        raise BenchError(413, "too_large", f"Photos up to {mb} MB can be uploaded.")
    try:
        answer = run_child(
            command("onnxruntime", settings.torch_python),
            {"mode": "sanitise", "max_pixels": settings.try_max_pixels, "side": settings.try_side},
            _limits(settings, "onnxruntime"),
            payload=data,
        )
    except ChildError as exc:
        if exc.code in REJECTED:
            raise BenchError(422, exc.code, exc.message) from exc
        raise
    return base64.b64decode(answer["jpeg"]), answer["info"]


def classify_bytes(
    settings: BenchSettings, jpeg: bytes, model_id: str, *, sanitised: bool = False
) -> dict[str, Any]:
    """Run a photo through every variant of a model; ``jpeg`` must be clean unless
    ``sanitised`` is False, in which case it is cleaned first."""
    reg = registry(settings)
    model = next((m for m in reg["models"] if m["id"] == model_id), None)
    if model is None:
        raise BenchError(404, "unknown_model", "No such model.")
    info: dict[str, Any] = {}
    if not sanitised:
        jpeg, info = sanitise(settings, jpeg)
    names = labels(settings)
    by_runtime: dict[str, list[dict[str, Any]]] = {}
    for v in reg["variants"]:
        by_runtime.setdefault(v["runtime"], []).append(variant_options(settings, model, v))
    answers: dict[str, dict[str, Any]] = {}
    imports: dict[str, float] = {}
    for runtime, variants in by_runtime.items():
        answer = run_child(
            command(runtime, settings.torch_python),
            {"mode": "classify", "model": model, "variants": variants,
             "threads": settings.try_threads, "runs": 5},
            _limits(settings, runtime),
            payload=jpeg,
            threads=settings.try_threads,
        )  # fmt: skip
        imports[runtime] = answer["import_ms"]
        for result in answer["results"]:
            answers[result["variant"]] = result
    ref_top1 = answers[REFERENCE_VARIANT]["top5"][0]["index"]
    results = []
    for v in reg["variants"]:
        r = answers[v["id"]]
        results.append(
            {
                **{k: r[k] for k in ("variant", "load_ms", "first", "warm")},
                "top5": [{**p, "label": names[p["index"]]} for p in r["top5"]],
                "same_top1_as_reference": r["top5"][0]["index"] == ref_top1,
            }
        )
    return {
        "model": model_id,
        "photo": {
            "format": info.get("format"),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
        },
        "results": results,
        "import_ms": imports,
    }


def try_photo(
    db: Database,
    settings: BenchSettings,
    data: bytes,
    model_id: str,
    *,
    sample: str | None = None,
) -> BenchTryOut:
    t_wait = time.perf_counter()
    with cpu_lease(db.engine, holder="bench:try", wait_seconds=settings.try_lease_wait_seconds):
        t0 = time.perf_counter()
        out = classify_bytes(settings, data, model_id, sanitised=sample is not None)
        t1 = time.perf_counter()
    if sample is not None:
        rec = next(p for p in photos(settings)["photos"] if p["file"] == sample)
        out["photo"] = {"format": "JPEG", "width": rec["width"], "height": rec["height"]}
    log.info("bench.try", model=model_id, source="sample" if sample else "upload",
             ms=round((t1 - t0) * 1000))  # fmt: skip
    return BenchTryOut(
        **out,
        source="sample" if sample else "upload",
        sample=sample,
        wait_ms=round((t0 - t_wait) * 1000),
        total_ms=round((t1 - t0) * 1000),
        hardware_id=hardware_id(),
    )


def built(settings: BenchSettings) -> bool:
    return Path(settings.registry_path).exists()
