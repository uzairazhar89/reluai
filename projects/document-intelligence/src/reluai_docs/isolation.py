"""Run the PDF reader in a separate, resource-capped process.

A malformed or hostile PDF can make a parser spin, allocate without bound or crash. The
reader therefore runs as its own short-lived process (``reluai_docs.child``) that:

* gets a minimal environment (no database URL, API keys or other secrets);
* caps its own address space, CPU time and file writes before reading the input;
* is killed, with its process group, when the wall-clock deadline passes.

Its output is plain data (lines and boxes), parsed here; nothing it returns is executed.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

from reluai_core.logging import get_logger
from reluai_docs.pdfread import ReadError, ReadLimits, ReadResult

log = get_logger(__name__)
Progress = Callable[[str, int, int], None]
_MAX_LINE = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReaderLimits:
    read: ReadLimits
    timeout_seconds: float = 60.0
    cpu_seconds: int = 90
    memory_mb: int = 1536
    max_bytes: int = 10 * 1024 * 1024


def _environment(threads: int) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": "/tmp",  # noqa: S108 - nothing is written; some libraries read HOME
        "OMP_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": "1",
        "PYTHONHASHSEED": "0",
    }
    return env


def _collect(
    stdout: IO[bytes], progress: Progress | None
) -> tuple[ReadResult | None, ReadError | None]:
    """Read the child's events until it closes its output."""
    result: ReadResult | None = None
    error: ReadError | None = None
    while raw := stdout.readline(_MAX_LINE):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None, ReadError("reader_failed", "The PDF reader returned unreadable output.")
        kind = event.get("event")
        if kind == "progress" and progress is not None:
            progress(str(event["stage"]), int(event["done"]), int(event["total"]))
        elif kind == "result":
            result = ReadResult.from_json(event["data"])
        elif kind == "error":
            error = ReadError(str(event["code"]), str(event["message"]))
    return result, error


def read_isolated(
    data: bytes, limits: ReaderLimits, progress: Progress | None = None
) -> ReadResult:
    """Read ``data`` in a child process; raises ``ReadError`` with a visitor-safe message."""
    options = {
        "memory_mb": limits.memory_mb,
        "cpu_seconds": limits.cpu_seconds,
        "max_bytes": limits.max_bytes,
        "max_pages": limits.read.max_pages,
        "max_ocr_pages": limits.read.max_ocr_pages,
        "ocr_dpi": limits.read.ocr_dpi,
        "ocr_max_pixels": limits.read.ocr_max_pixels,
        "ocr_threads": limits.read.ocr_threads,
        "segments": limits.read.segments,
        "preview_pages": limits.read.preview_pages,
        "preview_dpi": limits.read.preview_dpi,
    }
    proc = subprocess.Popen(
        [sys.executable, "-I", "-B", "-m", "reluai_docs.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_environment(limits.read.ocr_threads),
        start_new_session=True,
    )
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)

    timer = threading.Timer(limits.timeout_seconds, kill)
    timer.daemon = True
    timer.start()
    assert proc.stdin is not None  # noqa: S101
    assert proc.stdout is not None  # noqa: S101
    try:
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.write(json.dumps(options).encode() + b"\n")
            proc.stdin.write(data)
            proc.stdin.close()
        result, error = _collect(proc.stdout, progress)
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        kill()
        code = proc.wait()
    finally:
        timer.cancel()
        proc.stdout.close()
    if timed_out.is_set() or code in (-signal.SIGXCPU, -signal.SIGKILL):
        log.warning("docs.reader_killed", returncode=code, timed_out=timed_out.is_set())
        raise ReadError(
            "timeout", "Reading this PDF took longer than the demo allows; try a smaller file."
        )
    if error is not None:
        raise error
    if result is None:
        log.warning("docs.reader_failed", returncode=code)
        raise ReadError("reader_failed", "This PDF could not be read.")
    return result
