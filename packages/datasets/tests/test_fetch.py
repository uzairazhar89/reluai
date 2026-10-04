from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from reluai_datasets.fetch import DownloadError, download

PAYLOAD = b"x" * 5000


def client(status: int = 200, body: bytes = PAYLOAD) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_verifies_checksum(tmp_path: Path) -> None:
    dest = tmp_path / "f.bin"
    digest = download(
        "https://example.test/f",
        dest,
        max_bytes=10_000,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        client=client(),
    )
    assert dest.read_bytes() == PAYLOAD
    assert digest == hashlib.sha256(PAYLOAD).hexdigest()


def test_checksum_mismatch_leaves_nothing_behind(tmp_path: Path) -> None:
    dest = tmp_path / "f.bin"
    with pytest.raises(DownloadError, match="checksum"):
        download(
            "https://example.test/f",
            dest,
            max_bytes=10_000,
            expected_sha256="0" * 64,
            client=client(),
        )
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_size_cap_enforced(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="limit"):
        download("https://example.test/f", tmp_path / "f.bin", max_bytes=100, client=client())


def test_http_errors_wrapped(tmp_path: Path) -> None:
    with pytest.raises(DownloadError):
        download(
            "https://example.test/f",
            tmp_path / "f.bin",
            max_bytes=100,
            client=client(status=403, body=b"no"),
        )
