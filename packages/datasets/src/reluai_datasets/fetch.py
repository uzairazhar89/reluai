"""Streaming downloads with a size cap and SHA-256 verification."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import httpx

from reluai_core.logging import get_logger

log = get_logger(__name__)


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def download(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    expected_sha256: str | None = None,
    timeout: float = 120.0,
    client: httpx.Client | None = None,
) -> str:
    """Download ``url`` to ``dest`` atomically; returns the file's SHA-256.

    Refuses files larger than ``max_bytes`` and, when given, files whose checksum differs from
    ``expected_sha256``. Nothing is left at ``dest`` on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    h = hashlib.sha256()
    size = 0
    tmp = Path(tempfile.mkstemp(dir=dest.parent, prefix=".download-")[1])
    try:
        with http.stream("GET", url) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise DownloadError(f"{url}: {declared} bytes exceeds limit {max_bytes}")
            with tmp.open("wb") as fh:
                for block in resp.iter_bytes():
                    size += len(block)
                    if size > max_bytes:
                        raise DownloadError(f"{url}: exceeded {max_bytes} byte limit")
                    h.update(block)
                    fh.write(block)
        digest = h.hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise DownloadError(f"{url}: checksum {digest} != expected {expected_sha256}")
        tmp.replace(dest)
    except httpx.HTTPError as exc:
        raise DownloadError(f"{url}: {exc}") from exc
    else:
        log.info("dataset.downloaded", url=url, bytes=size, sha256=digest)
        return digest
    finally:
        tmp.unlink(missing_ok=True)
        if owns_client:
            http.close()
