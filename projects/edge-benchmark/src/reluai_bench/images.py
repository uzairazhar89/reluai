"""The photos the lab uses, taken from the coco-cc bundle (see scripts/assets/coco_cc.py).

The bundle's ``general`` subset (COCO 2017 validation photos under reuse licences, with no
street vehicles in them) is split once, reproducibly, into:

* ``calibration``: 128 photos the 8-bit models are calibrated on;
* ``agreement``: 200 other photos on which every variant's answers are compared with
  PyTorch's (the first ``latency_images`` of them are also used for latency);
* ``samples``: a few of the remaining photos offered in "Try it".

Only these photos are copied into the data directory, with their licence and source.
"""

from __future__ import annotations

import json
import random
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUNDLE = "coco-cc-subset-v1"
BUNDLE_URL = (
    f"https://github.com/uzairazhar89/reluai/releases/download/assets-coco-cc-v1/{BUNDLE}.tar"
)
BUNDLE_SHA256 = "747c1a7aac8f8229131cd22664575e1f36246481e119dfbe63387ea409d36b2f"
BUNDLE_MAX_BYTES = 200 * 1024 * 1024
SPLIT_SEED = 7
CALIBRATION = 128
AGREEMENT = 200
# Photos offered in "Try it", chosen by hand from the rest for variety (COCO image ids);
# when empty, the first few of the rest are used.
SAMPLE_IDS: tuple[int, ...] = (464786, 50844, 375015, 418961, 347456, 39769, 558421, 567432)
SAMPLES = 8
LICENCE_URLS = {
    "Attribution License": ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/"),
    "Attribution-ShareAlike License": (
        "CC BY-SA 2.0",
        "https://creativecommons.org/licenses/by-sa/2.0/",
    ),
    "No known copyright restrictions": (
        "No known copyright restrictions",
        "https://www.flickr.com/commons/usage/",
    ),
    "United States Government Work": (
        "United States Government work",
        "https://www.usa.gov/government-copyright",
    ),
}


@dataclass(frozen=True, slots=True)
class Photo:
    id: int
    file: str
    width: int
    height: int
    licence: str
    licence_url: str
    source_url: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "width": self.width,
            "height": self.height,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "source_url": self.source_url,
        }


def split(general: list[int], *, seed: int = SPLIT_SEED) -> dict[str, list[int]]:
    ids = sorted(general)
    random.Random(seed).shuffle(ids)  # noqa: S311 - reproducible split, not security
    calibration = sorted(ids[:CALIBRATION])
    agreement = ids[CALIBRATION : CALIBRATION + AGREEMENT]  # keeps the shuffled order
    rest = ids[CALIBRATION + AGREEMENT :]
    if SAMPLE_IDS:
        missing = [i for i in SAMPLE_IDS if i not in rest]
        if missing:
            raise ValueError(f"sample photos not in the remaining set: {missing}")
        samples = list(SAMPLE_IDS)
    else:
        samples = rest[:SAMPLES]
    return {"calibration": calibration, "agreement": agreement, "samples": samples}


def extract(tar_path: Path, out_dir: Path) -> dict[str, Any]:
    """Copy the photos the lab needs out of the bundle; returns the ``images.json`` index."""
    with tarfile.open(tar_path) as tar:

        def read(name: str) -> bytes:
            member = tar.extractfile(f"{BUNDLE}/{name}")
            if member is None:
                raise FileNotFoundError(name)
            return member.read()

        coco = json.loads(read("annotations.json"))
        subsets = json.loads(read("subsets.json"))
        licences = {lic["id"]: lic["name"] for lic in coco["licenses"]}
        records = {img["id"]: img for img in coco["images"]}
        parts = split(subsets["general"])
        photos: dict[int, Photo] = {}
        image_dir = out_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        for image_id in sorted({i for ids in parts.values() for i in ids}):
            rec = records[image_id]
            name, url = LICENCE_URLS[licences[rec["license"]]]
            photos[image_id] = Photo(
                id=image_id,
                file=rec["file_name"],
                width=rec["width"],
                height=rec["height"],
                licence=name,
                licence_url=url,
                source_url=(rec.get("flickr_url") or rec["coco_url"]).replace(
                    "http://", "https://", 1
                ),
            )
            (image_dir / rec["file_name"]).write_bytes(read(f"images/{rec['file_name']}"))
    index = {
        "bundle": BUNDLE,
        "split_seed": SPLIT_SEED,
        **{key: [photos[i].file for i in ids] for key, ids in parts.items()},
        "photos": [p.to_json() for p in photos.values()],
    }
    (out_dir / "images.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


def from_directory(src: Path, out_dir: Path) -> dict[str, Any]:
    """Development stand-in for the bundle: any folder of JPEG photos (not published)."""
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"})
    if len(files) < 4:
        raise ValueError(f"need at least 4 JPEG photos in {src}")
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    photos = []
    for i, f in enumerate(files):
        (image_dir / f.name).write_bytes(f.read_bytes())
        photos.append(Photo(i, f.name, 0, 0, "development only", "", f"file://{f.name}").to_json())
    half = max(2, len(files) // 2)
    index = {
        "bundle": f"directory:{src.name}",
        "split_seed": None,
        "calibration": [f.name for f in files[:half]],
        "agreement": [f.name for f in files[half:]],
        "samples": [f.name for f in files[: min(SAMPLES, len(files))]],
        "photos": photos,
    }
    (out_dir / "images.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index
