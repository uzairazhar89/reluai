"""Image preprocessing shared by every variant (and by both Python environments).

The same function prepares the input for PyTorch and for ONNX Runtime, so differences in
the outputs come from the models alone. It reproduces timm's evaluation transform:
resize the shorter side to ``floor(size / crop_pct)`` with antialiased bicubic
resampling, crop the centre square, scale to [0, 1] and normalise per channel.

Only the standard library, NumPy and Pillow are imported here: this module also runs in
the PyTorch environment's child processes.
"""

from __future__ import annotations

import io
import math
import warnings
from typing import Any

import numpy as np
from PIL import Image, ImageOps

FILTERS = {"bicubic": Image.Resampling.BICUBIC, "bilinear": Image.Resampling.BILINEAR}
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageRejectedError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def decode(data: bytes) -> Image.Image:
    """Decode trusted image bytes (the bundled photos) to RGB."""
    with Image.open(io.BytesIO(data)) as img:
        return img.convert("RGB")


def sanitise(data: bytes, *, max_pixels: int, side: int) -> tuple[bytes, dict[str, Any]]:
    """Decode an uploaded image defensively and re-encode it as a plain JPEG.

    Only JPEG, PNG and WebP are accepted; images over ``max_pixels`` are refused before
    their pixels are decoded; orientation from EXIF is applied, then all metadata is
    dropped; the result is at most ``side`` pixels on its longer edge.
    """
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # checked below
            img = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as exc:
        raise ImageRejectedError("too_many_pixels", "This image has too many pixels.") from exc
    except (OSError, ValueError) as exc:
        raise ImageRejectedError("not_an_image", "This file is not a readable image.") from exc
    with img:
        if img.format not in ACCEPTED_FORMATS:
            raise ImageRejectedError("unsupported", "Upload a JPEG, PNG or WebP photo.")
        width, height = img.size
        if width * height > max_pixels:
            raise ImageRejectedError("too_many_pixels", "This image has too many pixels.")
        info = {"format": img.format, "width": width, "height": height}
        try:
            if img.format == "JPEG":
                img.draft("RGB", (side, side))  # decode at a reduced scale when possible
            oriented = ImageOps.exif_transpose(img)
            rgb = oriented.convert("RGB")
        except (Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
            raise ImageRejectedError("not_an_image", "This image could not be decoded.") from exc
    rgb.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=90)
    info |= {"clean_width": rgb.width, "clean_height": rgb.height}
    return out.getvalue(), info


def to_input(
    img: Image.Image,
    *,
    size: int,
    crop_pct: float,
    interpolation: str,
    mean: tuple[float, float, float],
    std: tuple[float, float, float],
) -> np.ndarray:
    """An NCHW float32 batch of one, as timm's evaluation transform would produce it."""
    scale = math.floor(size / crop_pct)
    w, h = img.size
    if w <= h:
        new_w, new_h = scale, int(scale * h / w)
    else:
        new_w, new_h = int(scale * w / h), scale
    resized = img.resize((new_w, new_h), FILTERS[interpolation], reducing_gap=None)
    left = round((new_w - size) / 2.0)
    top = round((new_h - size) / 2.0)
    crop = resized.crop((left, top, left + size, top + size))
    scaled: np.ndarray = np.asarray(crop, dtype=np.float32) / np.float32(255.0)
    arr = (scaled - np.asarray(mean, dtype=np.float32)) / np.asarray(std, dtype=np.float32)
    return np.ascontiguousarray(arr.transpose(2, 0, 1)[None, ...], dtype=np.float32)


def softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    out: np.ndarray = e / e.sum(axis=-1, keepdims=True)
    return out


def top_k(probs: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Indices and probabilities of the ``k`` largest entries of a 1-D array, best first."""
    idx = np.argpartition(-probs, k)[:k]
    idx = idx[np.argsort(-probs[idx], kind="stable")]
    return [(int(i), float(probs[i])) for i in idx]
