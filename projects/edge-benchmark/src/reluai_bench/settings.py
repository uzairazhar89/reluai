"""Configuration for the Edge AI Benchmark Lab (env prefix ``RELUAI_BENCH_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BenchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELUAI_BENCH_", env_file=".env", extra="ignore")

    # Built at image build time (reluai-bench build): weights, ONNX files, photos, models.json.
    data_dir: Path = Path("/var/lib/reluai/data/bench")
    # The PyTorch environment (conda-forge CPU build). Only child processes ever use it.
    torch_python: Path = Path("/opt/torch/bin/python")

    # Benchmark protocol.
    threads: tuple[int, ...] = (1, 2)
    warmup: int = Field(default=10, ge=0, le=100)
    iterations: int = Field(default=100, ge=5, le=2000)
    latency_images: int = Field(default=50, ge=1, le=500)
    throughput_batch: int = Field(default=8, ge=1, le=64)
    throughput_seconds: float = Field(default=2.0, gt=0, le=30)
    agreement_images: int = Field(default=200, ge=1, le=1000)

    # Child processes: wall clock, CPU time and address space (ONNX Runtime children only:
    # PyTorch reserves far more address space than it uses, so its child relies on the
    # container's memory limit, the CPU cap and the wall clock).
    child_timeout_seconds: float = Field(default=240.0, gt=0)
    child_cpu_seconds: int = Field(default=600, ge=10)
    child_memory_mb: int = Field(default=2048, ge=256)
    lease_wait_seconds: float = Field(default=600.0, ge=0)

    # "Try it": one photo through every variant, synchronously, under the CPU lease.
    try_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    try_max_pixels: int = Field(default=25_000_000, ge=10_000)
    try_side: int = Field(default=1024, ge=256, le=4096)
    try_threads: int = Field(default=2, ge=1, le=8)
    try_timeout_seconds: float = Field(default=45.0, gt=0)
    try_lease_wait_seconds: float = Field(default=20.0, ge=0)
    visitor_try_per_hour: int = Field(default=20, ge=1)

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "models.json"


@lru_cache(maxsize=1)
def get_bench_settings() -> BenchSettings:
    return BenchSettings()
