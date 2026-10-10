"""The DuckDB sandbox every query runs in.

Tables are opened read-only with file, network and extension access switched off and the
configuration locked, a memory cap and one thread; each query gets a timeout that interrupts
it. Connections are kept open per table, and only one query runs per API process at a time.
Even so, the SQL that reaches it is never visitor text: it is compiled from a validated plan
with bound parameters.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from reluai_csv.settings import CsvSettings

_SLOT = threading.BoundedSemaphore(1)
_SLOT_WAIT_SECONDS = 10.0


class SandboxBusyError(RuntimeError):
    """Another query is still running in this process."""


class QueryTimeoutError(RuntimeError):
    """The query was interrupted after the time limit."""


class QueryFailedError(RuntimeError):
    """DuckDB rejected or could not finish the query."""


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float


def locked_config(settings: CsvSettings) -> dict[str, Any]:
    return {
        "enable_external_access": False,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "threads": settings.query_threads,
        "memory_limit": settings.query_memory_limit,
    }


_OPEN: OrderedDict[str, duckdb.DuckDBPyConnection] = OrderedDict()
_OPEN_LOCK = threading.Lock()
_MAX_OPEN = 8


def _connection(path: Path, settings: CsvSettings) -> duckdb.DuckDBPyConnection:
    """A read-only, locked-down connection kept open per table (a few ms instead of ~100)."""
    key = str(path)
    with _OPEN_LOCK:
        con = _OPEN.get(key)
        if con is not None:
            _OPEN.move_to_end(key)
            return con
        con = duckdb.connect(key, read_only=True, config=locked_config(settings))
        con.execute("SET lock_configuration = true")
        _OPEN[key] = con
        while len(_OPEN) > _MAX_OPEN:
            _, oldest = _OPEN.popitem(last=False)
            oldest.close()
        return con


def forget(path: Path) -> None:
    """Close the cached connection to a table that is about to be deleted."""
    with _SLOT, _OPEN_LOCK:
        con = _OPEN.pop(str(path), None)
        if con is not None:
            con.close()


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def run_query(
    path: Path, sql: str, params: list[object], settings: CsvSettings, *, max_rows: int
) -> QueryResult:
    if not path.is_file():
        raise QueryFailedError("the table is no longer available")
    if not _SLOT.acquire(timeout=_SLOT_WAIT_SECONDS):
        raise SandboxBusyError("another query is running")
    try:
        cursor = _connection(path, settings).cursor()
        timed_out = threading.Event()

        def _interrupt() -> None:
            timed_out.set()
            cursor.interrupt()

        timer = threading.Timer(settings.query_timeout_seconds, _interrupt)
        t0 = time.perf_counter()
        timer.start()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchmany(max_rows + 1)
            names = [d[0] for d in (cursor.description or [])]
        except duckdb.InterruptException as exc:
            raise QueryTimeoutError("query interrupted after the time limit") from exc
        except duckdb.Error as exc:
            if timed_out.is_set():
                raise QueryTimeoutError("query interrupted after the time limit") from exc
            raise QueryFailedError(str(exc).splitlines()[0][:200]) from exc
        finally:
            timer.cancel()
            cursor.close()
        elapsed = (time.perf_counter() - t0) * 1000
    finally:
        _SLOT.release()
    truncated = len(rows) > max_rows
    return QueryResult(
        columns=names,
        rows=[[_plain(v) for v in r] for r in rows[:max_rows]],
        truncated=truncated,
        elapsed_ms=round(elapsed, 1),
    )
