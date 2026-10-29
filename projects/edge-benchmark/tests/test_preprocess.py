"""Preprocessing and upload sanitising."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from reluai_bench.preprocess import ImageRejectedError, decode, sanitise, softmax, to_input, top_k

from .conftest import photo

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def test_to_input_matches_the_evaluation_transform() -> None:
    img = decode(photo(1, (400, 300)))
    x = to_input(img, size=224, crop_pct=0.875, interpolation="bicubic", mean=MEAN, std=STD)
    assert x.shape == (1, 3, 224, 224) and x.dtype == np.float32 and x.flags.c_contiguous
    # By hand: shorter side to floor(224 / 0.875) = 256, then the centre 224 × 224.
    resized = img.resize((341, 256), Image.Resampling.BICUBIC)
    crop = np.asarray(resized.crop((58, 16, 282, 240)), dtype=np.float32) / 255.0
    expected = ((crop - np.array(MEAN)) / np.array(STD)).transpose(2, 0, 1)
    assert np.allclose(x[0], expected, atol=1e-5)


def test_portrait_photos_are_cropped_in_the_middle() -> None:
    img = decode(photo(2, (300, 500)))
    x = to_input(img, size=224, crop_pct=1.0, interpolation="bilinear", mean=MEAN, std=STD)
    assert x.shape == (1, 3, 224, 224)


def test_softmax_and_top_k() -> None:
    p = softmax(np.array([[1.0, 3.0, 2.0, 0.0, -1.0, 5.0]]))[0]
    assert abs(p.sum() - 1) < 1e-6
    assert [i for i, _ in top_k(p, 3)] == [5, 1, 2]


def test_sanitise_re_encodes_and_bounds_the_size() -> None:
    big = photo(3, (2000, 1500), "PNG")
    clean, info = sanitise(big, max_pixels=25_000_000, side=512)
    assert clean[:2] == b"\xff\xd8"
    assert info["format"] == "PNG" and (info["width"], info["height"]) == (2000, 1500)
    with Image.open(io.BytesIO(clean)) as img:
        assert max(img.size) == 512
        assert not img.info.get("exif")


def test_sanitise_applies_and_drops_the_exif_orientation() -> None:
    img = Image.open(io.BytesIO(photo(4, (300, 200))))
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90° when displayed
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    clean, _ = sanitise(out.getvalue(), max_pixels=10**7, side=1024)
    with Image.open(io.BytesIO(clean)) as result:
        assert result.size == (200, 300)
        assert 0x0112 not in result.getexif()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"not an image at all", "not_an_image"),
        (photo(5, (40, 40), "GIF"), "unsupported"),
        (photo(6, (600, 600), "PNG"), "too_many_pixels"),
    ],
)
def test_sanitise_refuses(data: bytes, code: str) -> None:
    with pytest.raises(ImageRejectedError) as err:
        sanitise(data, max_pixels=100_000, side=1024)
    assert err.value.code == code
