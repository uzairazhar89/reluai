"""A fingerprint of the machine a benchmark ran on.

Speed numbers mean little without the hardware: the same model can be twice as fast on a
CPU with AVX-512 VNNI (8-bit dot products in one instruction) as on one without. Every run
records the CPU model, the instruction-set extensions that matter for inference, how many
CPUs the process may use (affinity and the container's CPU quota), memory, and software
versions. Runs on the same hardware share a short fingerprint id.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any

# Extensions that change how fast convolutions and matrix products run on x86 CPUs.
ISA_FLAGS = (
    "sse4_2",
    "avx",
    "avx2",
    "fma",
    "f16c",
    "avx512f",
    "avx512bw",
    "avx512vl",
    "avx512_vnni",
    "avx_vnni",
    "avx512_bf16",
    "amx_tile",
    "amx_int8",
)


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cpuinfo(text: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if fields:
                break  # the first processor block is enough
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    flags = set(fields.get("flags", "").split())
    return {
        "model": fields.get("model name") or platform.processor() or platform.machine(),
        "vendor": fields.get("vendor_id"),
        "mhz": round(float(fields["cpu MHz"])) if fields.get("cpu MHz") else None,
        "flags": [f for f in ISA_FLAGS if f in flags],
        "hypervisor": "hypervisor" in flags,
    }


def _cpu_quota(text: str) -> float | None:
    """CPUs allowed by cgroup v2 ``cpu.max`` ("max 100000" means no limit)."""
    parts = text.split()
    if len(parts) == 2 and parts[0] != "max":
        try:
            return round(int(parts[0]) / int(parts[1]), 2)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _memory_mb(meminfo: str, cgroup_max: str) -> dict[str, int | None]:
    total = None
    if m := re.search(r"^MemTotal:\s+(\d+) kB", meminfo, re.MULTILINE):
        total = int(m.group(1)) // 1024
    limit = None
    value = cgroup_max.strip()
    if value and value != "max" and value.isdigit():
        limit = int(value) // (1024 * 1024)
    return {"total_mb": total, "container_limit_mb": limit}


def _os_name(text: str) -> str:
    if m := re.search(r'^PRETTY_NAME="?([^"\n]+)"?', text, re.MULTILINE):
        return m.group(1)
    return platform.system()


def fingerprint(versions: dict[str, str] | None = None) -> dict[str, Any]:
    cpu = _cpuinfo(_read("/proc/cpuinfo"))
    try:
        usable = len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        usable = os.cpu_count() or 1
    info: dict[str, Any] = {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "usable_cpus": usable,
        "cpu_quota": _cpu_quota(_read("/sys/fs/cgroup/cpu.max")),
        "memory": _memory_mb(_read("/proc/meminfo"), _read("/sys/fs/cgroup/memory.max")),
        "os": _os_name(_read("/etc/os-release")),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "versions": dict(sorted((versions or {}).items())),
    }
    key = {
        "model": cpu["model"],
        "flags": cpu["flags"],
        "usable": usable,
        "quota": info["cpu_quota"],
        "memory": info["memory"]["total_mb"],
    }
    info["id"] = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]
    return info
