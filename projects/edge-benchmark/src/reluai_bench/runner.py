"""Start the isolated benchmark process and read its answer.

ONNX Runtime variants run under the application's own Python; the PyTorch variant runs
under the separate PyTorch environment (``BenchSettings.torch_python``). Either way the
child gets a minimal environment (no database URL or keys), a CPU-time cap, no file
writes, and is killed with its process group at the wall-clock deadline. ONNX Runtime
children also get an address-space cap; PyTorch reserves far more address space than it
touches, so its child is bounded by the container's memory limit instead.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import reluai_bench
from reluai_core.logging import get_logger

log = get_logger(__name__)
_MAX_OUTPUT = 64 * 1024 * 1024

# Under the PyTorch interpreter the package is found by appending the directory that holds
# it to the end of sys.path, so the PyTorch environment's own packages always take
# precedence (only ``reluai_bench`` itself, which that environment lacks, comes from here).
_BOOTSTRAP = (
    "import runpy, sys; sys.path.append(sys.argv.pop(1)); "
    "runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)"
)
CHILD = "reluai_bench.child"


class ChildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ChildLimits:
    timeout_seconds: float
    cpu_seconds: int
    memory_mb: int | None
    # Largest file the child may write (in its own temporary directory, removed afterwards).
    # PyTorch probes for a writable temporary directory when it is imported.
    file_mb: int = 0


def package_root() -> Path:
    return Path(reluai_bench.__file__).resolve().parent.parent


def command(runtime: str, torch_python: Path, module: str = CHILD) -> list[str]:
    """The command line that runs ``module`` under the interpreter ``runtime`` needs."""
    if runtime == "pytorch":
        if not torch_python.exists():
            raise ChildError("no_pytorch", f"The PyTorch environment is missing ({torch_python}).")
        return [str(torch_python), "-I", "-B", "-c", _BOOTSTRAP, str(package_root()), module]
    return [sys.executable, "-I", "-B", "-m", module]


def _environment(threads: int, tmp: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": tmp,
        "TMPDIR": tmp,
        "OMP_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "PYTHONHASHSEED": "0",
    }


def run_child(
    cmd: list[str],
    options: dict[str, Any],
    limits: ChildLimits,
    *,
    payload: bytes = b"",
    threads: int = 1,
) -> dict[str, Any]:
    """Run one child; returns its ``{"ok": true, ...}`` answer or raises ``ChildError``."""
    opts = options | {
        "cpu_seconds": limits.cpu_seconds,
        "memory_mb": limits.memory_mb,
        "file_mb": limits.file_mb,
        "payload_bytes": len(payload),
    }
    with tempfile.TemporaryDirectory(prefix="reluai-bench-") as tmp:
        return _run(cmd, opts, limits, payload, _environment(threads, tmp))


def _run(
    cmd: list[str],
    opts: dict[str, Any],
    limits: ChildLimits,
    payload: bytes,
    env: dict[str, str],
) -> dict[str, Any]:
    proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and module, no shell
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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
    try:
        stdout, stderr = proc.communicate(json.dumps(opts).encode() + b"\n" + payload)
    finally:
        timer.cancel()
    if timed_out.is_set() or proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
        log.warning("bench.child_killed", returncode=proc.returncode, timed_out=timed_out.is_set())
        raise ChildError("timeout", "The measurement took longer than allowed and was stopped.")
    line = stdout[:_MAX_OUTPUT].strip().splitlines()[-1:] if stdout else []
    if not line:
        tail = stderr.decode(errors="replace").strip().splitlines()[-3:]
        log.warning("bench.child_failed", returncode=proc.returncode, stderr=tail)
        raise ChildError("child_failed", "The measurement process stopped without an answer.")
    try:
        answer: dict[str, Any] = json.loads(line[0])
    except json.JSONDecodeError as exc:
        raise ChildError("child_failed", "The measurement process answered garbage.") from exc
    if not answer.get("ok"):
        raise ChildError(str(answer.get("code")), str(answer.get("message")))
    return answer
