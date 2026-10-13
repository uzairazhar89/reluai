"""Entry point of the isolated PDF reader process (``python -m reluai_docs.child``).

Protocol: stdin carries one line of JSON options followed by the PDF bytes; stdout carries
newline-delimited JSON events (``progress``, then one ``result`` or ``error``). Before it
touches the file, the process caps its own memory, CPU time and file writes, and anything a
library prints is redirected to stderr so it cannot corrupt the protocol.
"""

from __future__ import annotations

import json
import os
import resource
import sys
from typing import Any


def _limit(kind: int, value: int) -> None:
    _soft, hard = resource.getrlimit(kind)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    resource.setrlimit(kind, (value, value if hard == resource.RLIM_INFINITY else hard))


def main() -> int:
    out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)  # stray prints from libraries go to stderr

    def emit(event: dict[str, Any]) -> None:
        out.write(json.dumps(event, separators=(",", ":")) + "\n")

    stdin = sys.stdin.buffer
    options = json.loads(stdin.readline(65536) or b"{}")
    _limit(resource.RLIMIT_AS, int(options.get("memory_mb", 1536)) * 1024 * 1024)
    _limit(resource.RLIMIT_CPU, int(options.get("cpu_seconds", 90)))
    _limit(resource.RLIMIT_FSIZE, 0)  # no files may be written
    data = stdin.read(int(options.get("max_bytes", 10 * 1024 * 1024)) + 1)

    from reluai_docs.pdfread import ReadError, ReadLimits, read_pdf

    limits = ReadLimits(
        max_pages=int(options.get("max_pages", 60)),
        max_ocr_pages=int(options.get("max_ocr_pages", 5)),
        ocr_dpi=int(options.get("ocr_dpi", 150)),
        ocr_max_pixels=int(options.get("ocr_max_pixels", 6_000_000)),
        ocr_threads=int(options.get("ocr_threads", 2)),
    )
    try:
        result = read_pdf(
            data,
            limits,
            lambda stage, done, total: emit(
                {"event": "progress", "stage": stage, "done": done, "total": total}
            ),
        )
    except ReadError as exc:
        emit({"event": "error", "code": exc.code, "message": exc.message})
        return 0
    except MemoryError:
        emit(
            {
                "event": "error",
                "code": "too_complex",
                "message": "This PDF needs more memory to read than the demo allows.",
            }
        )
        return 0
    emit({"event": "result", "data": result.to_json()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
