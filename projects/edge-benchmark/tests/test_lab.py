"""The measuring path on a stand-in model: child processes, the suite, agreement, Try it,
the photo split and the hardware fingerprint."""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pytest

from reluai_bench import hardware, images
from reluai_bench.benchmark import NotBuiltError, _agreement, registry, run_suite
from reluai_bench.registry import MODELS, VARIANTS
from reluai_bench.runner import ChildError, ChildLimits, command, run_child
from reluai_bench.service import BenchError, classify_bytes, samples, sanitise
from reluai_bench.settings import BenchSettings

from .conftest import photo

ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- suite
def test_suite_measures_every_variant(fake_settings: BenchSettings) -> None:
    run = run_suite(fake_settings)
    assert {(r["model"], r["variant"], r["threads"]) for r in run["results"]} == {
        ("tiny", v, 1) for v in ("pytorch-fp32", "onnx-fp32", "onnx-int8")
    }
    r = run["results"][0]
    assert r["iterations"] == 5 and r["warmup"] == 1
    lat = r["latency_ms"]
    assert 0 < lat["inference"]["p50"] <= lat["inference"]["p95"]
    assert lat["total"]["p50"] >= lat["preprocess"]["p50"]
    assert r["throughput"]["batch"] == 2 and r["throughput"]["images_per_second"] > 0
    assert r["memory_mb"]["peak"] >= r["memory_mb"]["after_load"] > 0
    assert 0 < r["cpu_percent"] < 400
    # Same model file for every variant here, so the answers agree exactly.
    assert {a["variant"] for a in run["agreement"]} == {"onnx-fp32", "onnx-int8"}
    for a in run["agreement"]:
        assert a["photos"] == 5 and a["top1_agreement"] == 100.0
        assert a["max_probability_difference"] == 0.0
    hw = run["hardware"]
    assert len(hw["id"]) == 12 and "onnxruntime" in hw["versions"]
    assert run["protocol"]["agreement_photos"] == 5
    json.dumps(run)  # storable as JSON


def test_agreement_metrics() -> None:
    ref = np.array([[0.7, 0.2, 0.1, 0, 0, 0], [0.1, 0.6, 0.3, 0, 0, 0]], dtype=np.float32)
    other = np.array([[0.6, 0.3, 0.1, 0, 0, 0], [0.5, 0.2, 0.3, 0, 0, 0]], dtype=np.float32)
    a = _agreement(ref, other)
    assert a["top1_agreement"] == 50.0
    assert (a["confident_photos"], a["top1_agreement_confident"]) == (2, 50.0)
    assert a["reference_top1_in_top5"] == 100.0
    assert a["max_probability_difference"] == pytest.approx(0.4)
    assert a["mean_top1_probability_difference"] == pytest.approx((0.1 + 0.4) / 2)


def test_missing_build_is_reported(tmp_path: Path) -> None:
    with pytest.raises(NotBuiltError):
        registry(BenchSettings(data_dir=tmp_path))


def test_pytorch_child_needs_its_environment(tmp_path: Path) -> None:
    with pytest.raises(ChildError) as err:
        command("pytorch", tmp_path / "python")
    assert err.value.code == "no_pytorch"


def test_child_is_stopped_at_the_deadline(fake_settings: BenchSettings) -> None:
    reg = registry(fake_settings)
    model = reg["models"][0]
    opts = {"mode": "benchmark", "model": model, "threads": 1, "warmup": 0,
            "iterations": 10**7, "latency_images": [str(fake_settings.data_dir / "images" /
                                                          "000000000000.jpg")],
            "throughput_batch": 1, "throughput_seconds": 1, "agreement_images": [],
            "variant": {"id": "onnx-fp32", "runtime": "onnxruntime",
                        "path": str(fake_settings.data_dir / "models" / "tiny.onnx")}}  # fmt: skip
    with pytest.raises(ChildError) as err:
        run_child(command("onnxruntime", fake_settings.torch_python), opts,
                  ChildLimits(timeout_seconds=1.5, cpu_seconds=30, memory_mb=1024))  # fmt: skip
    assert err.value.code == "timeout"


# --------------------------------------------------------------------------- try it
def test_classify_an_upload(fake_settings: BenchSettings) -> None:
    out = classify_bytes(fake_settings, photo(11, (800, 600), "PNG"), "tiny")
    assert out["photo"] == {"format": "PNG", "width": 800, "height": 600}
    assert [r["variant"] for r in out["results"]] == ["pytorch-fp32", "onnx-fp32", "onnx-int8"]
    first = out["results"][0]
    assert len(first["top5"]) == 5 and first["top5"][0]["label"].startswith("class ")
    assert all(r["same_top1_as_reference"] for r in out["results"])
    assert first["warm"]["inference"] > 0 and first["load_ms"] > 0
    assert set(out["import_ms"]) == {"onnxruntime"}


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [(b"", 422, "empty_file"), (b"x" * 2048, 422, "not_an_image")],
)
def test_bad_uploads(fake_settings: BenchSettings, data: bytes, status: int, code: str) -> None:
    with pytest.raises(BenchError) as err:
        sanitise(fake_settings, data)
    assert (err.value.status, err.value.code) == (status, code)


def test_oversized_upload(fake_settings: BenchSettings) -> None:
    small = fake_settings.model_copy(update={"try_max_bytes": 1024})
    with pytest.raises(BenchError) as err:
        sanitise(small, photo(1))
    assert err.value.status == 413


def test_unknown_model(fake_settings: BenchSettings) -> None:
    with pytest.raises(BenchError) as err:
        classify_bytes(fake_settings, photo(1), "nope", sanitised=True)
    assert err.value.status == 404


def test_samples_carry_their_licence(fake_settings: BenchSettings) -> None:
    out = samples(fake_settings)
    assert [s.name for s in out] == ["000000000008.jpg", "000000000009.jpg"]
    assert out[0].url == "/api/bench/samples/000000000008.jpg"
    assert out[0].licence == "CC BY 2.0"


# --------------------------------------------------------------------------- photos
def _coco_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("coco_cc", ROOT / "scripts/assets/coco_cc.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_bundle(tmp_path: Path) -> Path:
    """A bundle in the published layout, built with the bundle script's own functions."""
    coco_cc = _coco_script()
    licences = [{"id": 1, "name": "Attribution-NonCommercial License", "url": "a"},
                {"id": 4, "name": "Attribution License", "url": "b"},
                {"id": 7, "name": "No known copyright restrictions", "url": "c"}]  # fmt: skip
    imgs, anns = [], []
    for i in range(1, 901):
        imgs.append({"id": i, "license": [1, 4, 7][i % 3], "file_name": f"{i:012d}.jpg",
                     "coco_url": "", "flickr_url": f"http://flickr/{i}", "width": 32,
                     "height": 24})  # fmt: skip
        anns.append({"id": i, "image_id": i, "category_id": 3 if i % 5 == 0 else 1,
                     "iscrowd": 0})  # fmt: skip
    coco = {"info": {}, "licenses": licences, "images": imgs, "annotations": anns,
            "categories": [{"id": 1, "name": "person"}, {"id": 3, "name": "car"}]}  # fmt: skip
    chosen = coco_cc.select(coco)
    ids = set(chosen["street"]) | set(chosen["general"])
    path = tmp_path / "bundle.tar"
    with tarfile.open(path, "w") as tar:
        for i in ids:
            coco_cc._add(tar, f"images/{i:012d}.jpg", photo(i, (32, 24)))
        coco_cc._add(tar, "annotations.json", json.dumps(coco_cc.subset(coco, ids)).encode())
        coco_cc._add(tar, "subsets.json", json.dumps(chosen).encode())
    return path


def test_bundle_split_and_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "SAMPLE_IDS", ())  # the chosen photos are not in this bundle
    out = tmp_path / "data"
    index = images.extract(_fake_bundle(tmp_path), out)
    cal, agree, samp = (set(index[k]) for k in ("calibration", "agreement", "samples"))
    assert (len(cal), len(agree), len(samp)) == (128, 200, 8)
    assert not cal & agree and not cal & samp and not agree & samp
    assert {p["licence"] for p in index["photos"]} <= {
        "CC BY 2.0",
        "No known copyright restrictions",
    }
    assert all(p["source_url"].startswith("https://flickr/") for p in index["photos"])
    assert len(list((out / "images").iterdir())) == 336
    again = images.extract(_fake_bundle(tmp_path), tmp_path / "again")
    assert again["agreement"] == index["agreement"]  # reproducible


def test_chosen_samples_must_be_spare_photos(monkeypatch: pytest.MonkeyPatch) -> None:
    general = list(range(1, 401))
    monkeypatch.setattr(images, "SAMPLE_IDS", ())
    spare = images.split(general)["samples"]
    rest = [i for i in general if i not in set().union(*images.split(general).values())]
    monkeypatch.setattr(images, "SAMPLE_IDS", (rest[3], spare[0]))
    assert images.split(general)["samples"] == [rest[3], spare[0]]
    calibration = images.split(general)["calibration"][0]
    monkeypatch.setattr(images, "SAMPLE_IDS", (calibration,))
    with pytest.raises(ValueError, match="not in the remaining set"):
        images.split(general)


def test_photo_folder_for_development(tmp_path: Path) -> None:
    src = tmp_path / "photos"
    src.mkdir()
    for i in range(6):
        (src / f"p{i}.jpg").write_bytes(photo(i, (64, 48)))
    index = images.from_directory(src, tmp_path / "out")
    assert len(index["calibration"]) == 3 and len(index["agreement"]) == 3


# --------------------------------------------------------------------------- hardware
CPUINFO = """processor\t: 0
vendor_id\t: AuthenticAMD
model name\t: AMD EPYC 9354P 32-Core Processor
cpu MHz\t\t: 3249.998
flags\t\t: fpu sse4_2 avx avx2 fma avx512f avx512_vnni hypervisor

processor\t: 1
model name\t: should be ignored
"""


def test_cpuinfo_parsing() -> None:
    cpu = hardware._cpuinfo(CPUINFO)
    assert cpu["model"] == "AMD EPYC 9354P 32-Core Processor"
    assert cpu["vendor"] == "AuthenticAMD" and cpu["mhz"] == 3250
    assert cpu["flags"] == ["sse4_2", "avx", "avx2", "fma", "avx512f", "avx512_vnni"]
    assert cpu["hypervisor"] is True


def test_cgroup_limits() -> None:
    assert hardware._cpu_quota("200000 100000") == 2.0
    assert hardware._cpu_quota("max 100000") is None
    mem = hardware._memory_mb("MemTotal:  8000000 kB\n", "1073741824\n")
    assert mem == {"total_mb": 7812, "container_limit_mb": 1024}
    assert hardware._memory_mb("", "max")["container_limit_mb"] is None


def test_fingerprint_is_stable() -> None:
    a = hardware.fingerprint({"onnxruntime": "1"})
    b = hardware.fingerprint({"onnxruntime": "2"})
    assert a["id"] == b["id"]  # software versions do not change the hardware id
    assert a["usable_cpus"] >= 1


# --------------------------------------------------------------------------- registry
def test_registry_pins() -> None:
    assert {m.id for m in MODELS} == {"mobilenetv3-small", "resnet18"}
    for m in MODELS:
        assert len(m.weights.sha256) == 64 and m.weights.url.startswith("https://github.com/")
        assert m.weights.sha256[:8] in m.weights.filename
    assert [v.id for v in VARIANTS] == ["pytorch-fp32", "onnx-fp32", "onnx-int8"]


def test_sanitise_in_child_returns_clean_jpeg(fake_settings: BenchSettings) -> None:
    clean, info = sanitise(fake_settings, photo(3, (1500, 1000), "PNG"))
    assert clean[:2] == b"\xff\xd8" and info["clean_width"] == 1024
    from PIL import Image

    with Image.open(io.BytesIO(clean)) as img:
        assert img.size == (1024, 683)
