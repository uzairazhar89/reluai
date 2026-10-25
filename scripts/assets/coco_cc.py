"""Build the "coco-cc" bundle: COCO 2017 validation photos whose licence allows reuse.

Runs in the `assets` workflow (GitHub Actions), which can reach cocodataset.org; the bundle
is then published as a release asset of this repository and pinned by SHA-256 in
artifacts/manifest.yaml, so image builds and development copies fetch that exact file.

Only photos under licences that allow reuse with changes are taken (COCO records each
photo's Flickr licence): Attribution, Attribution-ShareAlike, "No known copyright
restrictions" and "United States Government Work". Non-commercial and no-derivatives
photos are left out. Two subsets are drawn, without overlap and reproducibly:

- street: every such photo with at least one bicycle, car, motorcycle, bus or truck
  (not a crowd region), for measuring detectors on street objects;
- general: a seeded sample of the rest, for calibrating and checking image classifiers.

Every photo is checked against its record (JPEG dimensions) before it is accepted. The
bundle is an uncompressed tar with fixed metadata, so the same inputs give the same bytes.

    python scripts/assets/coco_cc.py --out build/asset
Standard library only: the workflow does not install the project.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import struct
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "v1"
NAME = f"coco-cc-subset-{VERSION}"
TAG = f"assets-coco-cc-{VERSION}"
ANNOTATIONS_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
ANNOTATIONS_MEMBER = "annotations/instances_val2017.json"
ALLOWED_LICENCES = {
    "Attribution License": "CC BY 2.0",
    "Attribution-ShareAlike License": "CC BY-SA 2.0",
    "No known copyright restrictions": "No known copyright restrictions",
    "United States Government Work": "United States Government Work",
}
STREET_CATEGORIES = {"bicycle", "car", "motorcycle", "bus", "truck"}
STREET_MAX = 700
GENERAL_COUNT = 400
SEED = 2026
MAX_IMAGE_BYTES = 3_000_000


def fetch(url: str, *, attempts: int = 4, timeout: float = 120.0) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
                return bytes(resp.read())
        except OSError as exc:
            if attempt == attempts:
                raise
            print(f"retry {attempt} for {url}: {exc}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's start-of-frame marker."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    raise ValueError("no frame header")


def select(coco: dict, *, street_max: int = STREET_MAX, general_count: int = GENERAL_COUNT,
           seed: int = SEED) -> dict[str, list[int]]:  # fmt: skip
    """Image ids per subset, sorted. Licences are matched by name, not by number."""
    allowed_ids = {lic["id"] for lic in coco["licenses"] if lic["name"] in ALLOWED_LICENCES}
    names = {c["id"]: c["name"] for c in coco["categories"]}
    usable = sorted(img["id"] for img in coco["images"] if img["license"] in allowed_ids)
    with_street = {
        a["image_id"]
        for a in coco["annotations"]
        if not a.get("iscrowd") and names[a["category_id"]] in STREET_CATEGORIES
    }
    street = [i for i in usable if i in with_street]
    rng = random.Random(seed)  # noqa: S311 - reproducible selection, not security
    if len(street) > street_max:
        street = sorted(rng.sample(street, street_max))
    rest = [i for i in usable if i not in with_street]
    general = sorted(rng.sample(rest, min(general_count, len(rest))))
    return {"street": street, "general": general}


def subset(coco: dict, ids: set[int]) -> dict:
    keep_lic = {img["license"] for img in coco["images"] if img["id"] in ids}
    return {
        "info": coco["info"],
        "licenses": [lic for lic in coco["licenses"] if lic["id"] in keep_lic],
        "categories": coco["categories"],
        "images": [img for img in coco["images"] if img["id"] in ids],
        "annotations": [a for a in coco["annotations"] if a["image_id"] in ids],
    }


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(f"{NAME}/{name}")
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


README = """# COCO 2017 validation photos with reuse licences ({version})

Built by `scripts/assets/coco_cc.py` in the reluai repository from the COCO 2017
validation set. Only photos whose recorded Flickr licence allows reuse with changes are
included: {licences}.

- `annotations.json`: the COCO records (boxes, categories, licence and Flickr URL per photo)
  for the photos in this bundle, in COCO format.
- `subsets.json`: which photos are in the `street` subset (at least one bicycle, car,
  motorcycle, bus or truck) and which in the `general` subset (a seeded sample of the rest).
- `images/`: the photos, unchanged.
- `provenance.json`: source URL and SHA-256 of the annotation archive and of every photo.

Credits: photos by their Flickr authors under the licence recorded for each photo
(see `flickr_url` and `license` in annotations.json). Annotations: COCO Consortium,
CC BY 4.0 (Lin et al., "Microsoft COCO: Common Objects in Context", ECCV 2014).
"""


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    print(f"downloading {ANNOTATIONS_URL}")
    archive = fetch(ANNOTATIONS_URL, timeout=600)
    archive_sha = hashlib.sha256(archive).hexdigest()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        coco = json.loads(zf.read(ANNOTATIONS_MEMBER))
    del archive
    chosen = select(coco)
    ids = set(chosen["street"]) | set(chosen["general"])
    records = {img["id"]: img for img in coco["images"] if img["id"] in ids}
    print(f"selected {len(chosen['street'])} street and {len(chosen['general'])} general photos")

    tar_path = out / f"{NAME}.tar"
    image_hashes: dict[str, str] = {}
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as tar:
        for n, image_id in enumerate(sorted(ids), 1):
            img = records[image_id]
            data = fetch(img["coco_url"])
            if len(data) > MAX_IMAGE_BYTES:
                raise SystemExit(f"{img['file_name']}: {len(data)} bytes, over the limit")
            if jpeg_size(data) != (img["width"], img["height"]):
                raise SystemExit(f"{img['file_name']}: size differs from its record")
            image_hashes[img["file_name"]] = hashlib.sha256(data).hexdigest()
            _add(tar, f"images/{img['file_name']}", data)
            if n % 100 == 0:
                print(f"  {n}/{len(ids)}")
        licences = ", ".join(sorted(set(ALLOWED_LICENCES.values())))
        _add(tar, "README.md", README.format(version=VERSION, licences=licences).encode())
        _add(tar, "annotations.json", json.dumps(subset(coco, ids), separators=(",", ":")).encode())
        _add(tar, "subsets.json", json.dumps(chosen, indent=1).encode())
        provenance = {
            "bundle": NAME,
            "annotations": {"url": ANNOTATIONS_URL, "member": ANNOTATIONS_MEMBER,
                            "sha256": archive_sha},
            "selection": {"licences": sorted(ALLOWED_LICENCES), "street_categories":
                          sorted(STREET_CATEGORIES), "street_max": STREET_MAX,
                          "general_count": GENERAL_COUNT, "seed": SEED},
            "images_sha256": dict(sorted(image_hashes.items())),
        }  # fmt: skip
        _add(tar, "provenance.json", json.dumps(provenance, indent=1).encode())

    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(f"{digest}  {tar_path.name}\n")
    (out / "TAG").write_text(TAG)
    (out / "NOTES.md").write_text(
        f"COCO 2017 validation photos whose licence allows reuse with changes "
        f"({len(chosen['street'])} street, {len(chosen['general'])} general), with their "
        f"annotations. Built by `scripts/assets/coco_cc.py` from {ANNOTATIONS_URL} "
        f"(SHA-256 `{archive_sha}`).\n\n`{tar_path.name}` SHA-256: `{digest}`\n\n"
        "Photos: their Flickr authors, under the licence recorded per photo. Annotations: "
        "COCO Consortium, CC BY 4.0.\n"
    )
    print(f"{tar_path} {tar_path.stat().st_size} bytes sha256 {digest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
