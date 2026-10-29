"""API models for the Edge AI Benchmark Lab."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchLatencyStats(BaseModel):
    p50: float
    p95: float
    mean: float
    min: float


class BenchLatencyOut(BaseModel):
    total: BenchLatencyStats
    preprocess: BenchLatencyStats
    inference: BenchLatencyStats
    postprocess: BenchLatencyStats


class BenchThroughputOut(BaseModel):
    batch: int
    runs: int
    images_per_second: float


class BenchMemoryOut(BaseModel):
    start: float
    after_import: float
    after_load: float
    end: float
    peak: float


class BenchResultOut(BaseModel):
    model: str
    variant: str
    threads: int
    size_bytes: int
    import_ms: float
    load_ms: float
    latency_ms: BenchLatencyOut
    iterations: int
    warmup: int
    cpu_percent: float = Field(description="CPU time over wall time while timing; 200 = 2 cores")
    throughput: BenchThroughputOut
    memory_mb: BenchMemoryOut


class BenchAgreementOut(BaseModel):
    model: str
    variant: str
    reference: str
    photos: int
    top1_agreement: float = Field(description="% of photos with the same top class")
    confident_photos: int = Field(description="Photos where PyTorch's top class is ≥ 50%")
    top1_agreement_confident: float = Field(description="Same top class on those photos, %")
    top5_overlap: float = Field(description="Mean share of the top five classes in common, %")
    reference_top1_in_top5: float
    max_probability_difference: float
    mean_top1_probability_difference: float


class BenchCpuOut(BaseModel):
    model: str
    vendor: str | None
    mhz: int | None
    flags: list[str]
    hypervisor: bool


class BenchHardwareMemoryOut(BaseModel):
    total_mb: int | None
    container_limit_mb: int | None


class BenchHardwareOut(BaseModel):
    id: str
    cpu: BenchCpuOut
    logical_cpus: int | None
    usable_cpus: int
    cpu_quota: float | None
    memory: BenchHardwareMemoryOut
    os: str
    kernel: str
    machine: str
    python: str
    versions: dict[str, str]


class BenchRunOut(BaseModel):
    id: uuid.UUID
    ran_at: datetime
    label: str
    duration_seconds: float
    hardware: BenchHardwareOut
    protocol: dict[str, Any]
    build: dict[str, Any]
    results: list[BenchResultOut]
    agreement: list[BenchAgreementOut]


class BenchHeadlineOut(BaseModel):
    model: str
    variant: str
    threads: int
    inference_p50_ms: float
    total_p50_ms: float


class BenchRunSummaryOut(BaseModel):
    id: uuid.UUID
    ran_at: datetime
    label: str
    hardware_id: str
    cpu_model: str
    headline: list[BenchHeadlineOut]


class BenchFileOut(BaseModel):
    bytes: int
    sha256: str


class BenchScoreOut(BaseModel):
    agreement: float = Field(description="% of calibration photos with the 32-bit top class")
    confident_agreement: float = Field(description="The same, on photos it is ≥ 50% sure of")
    kl: float = Field(description="Mean KL divergence from the 32-bit probabilities")


class BenchKeptLayerOut(BaseModel):
    node: str
    op: str
    kl_when_alone: float


class BenchQuantStepOut(BaseModel):
    kept_fp32: int
    agreement: float
    confident_agreement: float
    kl: float


class BenchQuantisationOut(BaseModel):
    format: str
    weights: str
    activations: str
    calibration_method: str
    calibration_photos: int
    confident_photos: int
    confident_threshold: float
    target_agreement: float
    all_layers: BenchScoreOut
    kept_fp32: list[BenchKeptLayerOut]
    final: BenchScoreOut
    candidates: int | None = None
    steps: list[BenchQuantStepOut] = Field(default_factory=list)


class BenchModelOut(BaseModel):
    id: str
    title: str
    summary: str
    params_millions: float
    input_size: int
    crop_pct: float
    published_top1: float
    published_top5: float
    paper: str
    licence: str
    homepage: str
    weights_url: str
    files: dict[str, BenchFileOut]
    quantisation: BenchQuantisationOut


class BenchVariantOut(BaseModel):
    id: str
    title: str
    runtime: str
    precision: str
    summary: str


class BenchRegistryOut(BaseModel):
    models: list[BenchModelOut]
    variants: list[BenchVariantOut]
    tools: dict[str, str | int]
    quantisation: dict[str, str | int]
    photos: dict[str, str | int]
    published_accuracy_source: str


class BenchSampleOut(BaseModel):
    name: str
    url: str
    width: int
    height: int
    licence: str
    licence_url: str
    source_url: str


class BenchPhaseOut(BaseModel):
    preprocess: float
    inference: float
    postprocess: float


class BenchPredictionOut(BaseModel):
    index: int
    label: str
    probability: float


class BenchTryVariantOut(BaseModel):
    variant: str
    load_ms: float
    first: BenchPhaseOut = Field(description="First call after loading (includes lazy set-up)")
    warm: BenchPhaseOut = Field(description="Median of the following calls")
    top5: list[BenchPredictionOut]
    same_top1_as_reference: bool


class BenchTryPhotoOut(BaseModel):
    format: str | None = None
    width: int
    height: int


class BenchTryOut(BaseModel):
    model: str
    source: Literal["upload", "sample"]
    sample: str | None
    photo: BenchTryPhotoOut
    results: list[BenchTryVariantOut]
    import_ms: dict[str, float] = Field(description="Starting each runtime in a fresh process")
    wait_ms: int
    total_ms: int
    hardware_id: str
