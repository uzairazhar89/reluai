"""Process-wide service container for code that runs outside a request (jobs, CLI).

Entry points (API start-up, worker, CLI) call :func:`set_runtime` once; background tasks
call :func:`get_runtime` to reach the database and job app. Requests use FastAPI
dependencies instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from procrastinate import App

from reluai_core.db import Database
from reluai_core.settings import CoreSettings


@dataclass(slots=True)
class Runtime:
    settings: CoreSettings
    db: Database
    jobs: App | None = None


_runtime: Runtime | None = None


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime  # noqa: PLW0603 - deliberate single process-wide container
    _runtime = runtime


def get_runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("Runtime not initialised; call set_runtime() in the entry point")
    return _runtime
