"""The benchmark API against PostgreSQL, on the stand-in model."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from reluai_api.main import create_app
from reluai_bench.benchmark import run_suite
from reluai_bench.service import record_run
from reluai_bench.settings import BenchSettings, get_bench_settings
from reluai_core.db import Database
from reluai_core.settings import CoreSettings

from .conftest import photo

pytestmark = pytest.mark.db


@pytest.fixture
def client(
    core_settings: CoreSettings, clean_db: Database, fake_settings: BenchSettings
) -> Iterator[TestClient]:
    app = create_app(core_settings, pipeline_deferrer=lambda _: None)
    app.dependency_overrides[get_bench_settings] = lambda: fake_settings
    with TestClient(app) as c:
        yield c


def test_registry_and_samples(client: TestClient) -> None:
    reg = client.get("/api/bench/registry")
    assert reg.status_code == 200, reg.text
    body = reg.json()
    assert body["models"][0]["id"] == "tiny"
    assert set(body["models"][0]["files"]) == {"pytorch-fp32", "onnx-fp32", "onnx-int8"}
    assert body["published_accuracy_source"].startswith("https://github.com/huggingface/")
    samples = client.get("/api/bench/samples").json()
    assert len(samples) == 2
    img = client.get(samples[0]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert client.get("/api/bench/samples/000000000001.jpg").status_code == 404  # not a sample
    assert client.get("/api/bench/samples/..%2Fmodels.json").status_code in (404, 422)


def test_runs_are_recorded_and_listed(
    client: TestClient, clean_db: Database, fake_settings: BenchSettings
) -> None:
    assert client.get("/api/bench/runs/latest").json() is None
    record_run(clean_db, run_suite(fake_settings), label="manual")
    latest = client.get("/api/bench/runs/latest")
    assert latest.status_code == 200, latest.text
    run = latest.json()
    assert run["label"] == "manual" and len(run["results"]) == 3
    assert run["hardware"]["id"] == run["hardware"]["id"][:12]
    history = client.get("/api/bench/runs").json()
    assert len(history) == 1 and len(history[0]["headline"]) == 3


def test_try_a_sample_and_an_upload(client: TestClient) -> None:
    r = client.post("/api/bench/try/samples/000000000008.jpg", params={"model": "tiny"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source"] == "sample" and out["sample"] == "000000000008.jpg"
    assert out["photo"]["width"] == 320 and len(out["results"]) == 3
    up = client.post(
        "/api/bench/try",
        files={"file": ("photo.png", photo(21, (500, 400), "PNG"), "image/png")},
        data={"model": "tiny"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["source"] == "upload" and up.json()["photo"]["format"] == "PNG"
    bad = client.post("/api/bench/try", files={"file": ("x.jpg", b"nope" * 100, "image/jpeg")},
                      data={"model": "tiny"})  # fmt: skip
    assert bad.status_code == 422 and bad.json()["code"] == "not_an_image"
    unknown = client.post("/api/bench/try/samples/000000000008.jpg", params={"model": "nope"})
    assert unknown.status_code == 404


def test_try_quota(client: TestClient, fake_settings: BenchSettings) -> None:
    fake_settings.visitor_try_per_hour = 1
    assert client.post("/api/bench/try/samples/000000000009.jpg?model=tiny").status_code == 200
    again = client.post("/api/bench/try/samples/000000000009.jpg?model=tiny")
    assert again.status_code == 429 and "Retry-After" in again.headers


def test_not_built(client: TestClient, fake_settings: BenchSettings, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    fake_settings.data_dir = tmp_path_factory.mktemp("empty")
    r = client.get("/api/bench/registry")
    assert r.status_code == 503 and r.json()["code"] == "not_built"
