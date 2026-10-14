"""Turn a rendered invoice into a simulated scan: an image-only PDF.

A scanner or phone camera adds what OCR has to cope with: a slight rotation, grey
background noise, softened edges and JPEG compression, at a modest resolution. The
amounts are drawn from a seed, so the same document always gets the same "scan".
The result has no text layer, so reading it takes the OCR path.
"""

from __future__ import annotations

import io
import random

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter


def simulate_scan(pdf: bytes, *, seed: int, dpi: int = 150) -> bytes:
    rng = random.Random(seed)  # noqa: S311 - reproducible choices, not security
    noise = np.random.default_rng(seed)
    doc = pdfium.PdfDocument(pdf)
    pages: list[Image.Image] = []
    try:
        for index in range(len(doc)):
            page = doc[index]
            bitmap = page.render(scale=dpi / 72, grayscale=True)
            try:
                image = bitmap.to_pil().convert("L")
            finally:
                bitmap.close()
                page.close()
            image = image.rotate(
                rng.uniform(-1.2, 1.2), resample=Image.Resampling.BICUBIC, fillcolor=255
            )
            image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.7)))
            pixels = np.asarray(image, dtype=np.float32)
            pixels = pixels * rng.uniform(0.88, 0.97) + rng.uniform(4, 14)  # grey paper
            pixels += noise.normal(0, rng.uniform(4, 9), pixels.shape)
            image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="L")
            jpeg = io.BytesIO()
            image.save(jpeg, "JPEG", quality=rng.randint(55, 75))
            pages.append(Image.open(io.BytesIO(jpeg.getvalue())))
    finally:
        doc.close()
    out = io.BytesIO()
    pages[0].save(out, "PDF", resolution=float(dpi), save_all=True, append_images=pages[1:])
    return out.getvalue()
