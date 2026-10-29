"""Edge AI Benchmark Lab routes (mounted at ``/api/bench``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile

from reluai_bench import service
from reluai_bench.benchmark import NotBuiltError
from reluai_bench.runner import ChildError
from reluai_bench.schemas import (
    BenchRegistryOut,
    BenchRunOut,
    BenchRunSummaryOut,
    BenchSampleOut,
    BenchTryOut,
)
from reluai_bench.settings import BenchSettings, get_bench_settings
from reluai_core.cpu_lease import LeaseUnavailableError
from reluai_core.db import Database, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.ratelimit import consume_quota, visitor_key

router = APIRouter(tags=["bench"])
SettingsDep = Annotated[BenchSettings, Depends(get_bench_settings)]
ModelId = Annotated[str, Query(pattern=r"^[a-z0-9-]{1,40}$")]
SampleName = Annotated[str, Path(pattern=r"^[\w-]{1,40}\.jpg$")]


def _problem(exc: Exception) -> ProblemError:
    if isinstance(exc, service.BenchError):
        return ProblemError(exc.status, exc.message, code=exc.code)
    if isinstance(exc, NotBuiltError):
        return ProblemError(503, "The benchmark models are not installed on this server.",
                            code="not_built")  # fmt: skip
    if isinstance(exc, ChildError) and exc.code == "timeout":
        return ProblemError(503, "The run took too long and was stopped; try again later.",
                            code="timeout")  # fmt: skip
    if isinstance(exc, LeaseUnavailableError):
        return ProblemError(503, "The server is busy with other work; try again in a minute.",
                            code="busy", headers={"Retry-After": "30"})  # fmt: skip
    return ProblemError(500, "The run failed.", code="failed")


def _quota(request: Request, db: Database, settings: BenchSettings) -> None:
    secret = request.app.state.core_settings.visitor_hash_secret.get_secret_value()
    key = f"bench:try:{visitor_key(client_ip(request), secret)}"
    with db.session() as s:
        result = consume_quota(s, key=key, limit=settings.visitor_try_per_hour,
                               window=timedelta(hours=1))  # fmt: skip
    if not result.allowed:
        raise ProblemError(
            429,
            f"Limit of {settings.visitor_try_per_hour} runs per hour reached; try again later.",
            code="quota_exceeded",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.get("/registry", response_model=BenchRegistryOut)
def get_registry(settings: SettingsDep) -> BenchRegistryOut:
    """The models and variants, with file sizes, hashes and how they were built."""
    try:
        return service.registry_out(settings)
    except NotBuiltError as exc:
        raise _problem(exc) from exc


@router.get("/runs/latest", response_model=BenchRunOut | None)
def get_latest(db: DatabaseDep) -> BenchRunOut | None:
    """The most recent benchmark run on this server, if any."""
    return service.latest_run(db)


@router.get("/runs", response_model=list[BenchRunSummaryOut])
def get_runs(
    db: DatabaseDep, limit: Annotated[int, Query(ge=1, le=60)] = 30
) -> list[BenchRunSummaryOut]:
    """Recent runs, newest first, with the median latencies at the highest thread count."""
    return service.history(db, limit)


@router.get("/samples", response_model=list[BenchSampleOut])
def get_samples(settings: SettingsDep) -> list[BenchSampleOut]:
    """Photos offered in "Try it", with their licence and source."""
    try:
        return service.samples(settings)
    except NotBuiltError as exc:
        raise _problem(exc) from exc


@router.get(
    "/samples/{name}",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_sample(name: SampleName, settings: SettingsDep) -> Response:
    try:
        data = service.sample_bytes(settings, name)
    except (service.BenchError, NotBuiltError) as exc:
        raise _problem(exc) from exc
    return Response(data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})  # fmt: skip


@router.post("/try/samples/{name}", response_model=BenchTryOut)
def post_try_sample(
    name: SampleName,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    model: ModelId = "mobilenetv3-small",
) -> BenchTryOut:
    """Classify a sample photo with every variant of a model, now, on this server."""
    _quota(request, db, settings)
    try:
        data = service.sample_bytes(settings, name)
        return service.try_photo(db, settings, data, model, sample=name)
    except (service.BenchError, NotBuiltError, ChildError, LeaseUnavailableError) as exc:
        raise _problem(exc) from exc


@router.post("/try", response_model=BenchTryOut)
def post_try(
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP photo, up to 5 MB")],
    model: Annotated[str, Form(pattern=r"^[a-z0-9-]{1,40}$")] = "mobilenetv3-small",
) -> BenchTryOut:
    """Classify your own photo with every variant of a model. Nothing is stored: the photo
    is decoded and re-encoded in an isolated process, classified, and discarded."""
    _quota(request, db, settings)
    data = file.file.read(settings.try_max_bytes + 1)
    try:
        return service.try_photo(db, settings, data, model)
    except (service.BenchError, NotBuiltError, ChildError, LeaseUnavailableError) as exc:
        raise _problem(exc) from exc
