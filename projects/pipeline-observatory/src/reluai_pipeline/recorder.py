"""Records a run's steps and structured log lines, and checkpoints them for live viewing.

Each log line goes both to the process log (JSON) and to ``pipeline.run_log`` so the
dashboard shows the *actual* log of a run, not a reconstruction.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson
from sqlalchemy import insert

from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_pipeline.models import RunLog, RunStep

_LEVELS = {"debug", "info", "warning", "error"}


def _jsonable(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = orjson.loads(orjson.dumps(fields, default=str))
    return result


@dataclass(slots=True)
class StepState:
    name: str
    rows_in: int | None = None
    rows_out: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class RunRecorder:
    def __init__(self, db: Database, run_id: uuid.UUID) -> None:
        self.db = db
        self.run_id = run_id
        self._log = get_logger("reluai.pipeline", run_id=str(run_id))
        self._pending_logs: list[dict[str, Any]] = []
        self._pending_steps: list[dict[str, Any]] = []
        self._position = 0
        self.steps: list[dict[str, Any]] = []

    def log(self, level: str, event: str, **fields: Any) -> None:
        level = level if level in _LEVELS else "info"
        getattr(self._log, level)(event, **fields)
        self._pending_logs.append(
            {
                "run_id": self.run_id,
                "ts": datetime.now(UTC),
                "level": level,
                "event": event[:64],
                "fields": _jsonable(fields),
            }
        )

    @contextmanager
    def step(self, name: str) -> Iterator[StepState]:
        state = StepState(name=name)
        self._position += 1
        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        self.log("info", "step.started", step=name)
        status = "succeeded"
        try:
            yield state
        except BaseException:
            status = "failed"
            raise
        finally:
            duration = round((time.perf_counter() - t0) * 1000)
            row = {
                "run_id": self.run_id,
                "position": self._position,
                "name": name,
                "status": status,
                "started_at": started_at,
                "duration_ms": duration,
                "rows_in": state.rows_in,
                "rows_out": state.rows_out,
                "detail": _jsonable(state.detail) or None,
            }
            self._pending_steps.append(row)
            self.steps.append(row)
            self.log(
                "info" if status == "succeeded" else "error",
                "step.finished",
                step=name,
                status=status,
                duration_ms=duration,
                rows_in=state.rows_in,
                rows_out=state.rows_out,
            )
            self.checkpoint()

    def skip(self, name: str, reason: str) -> None:
        self._position += 1
        row = {
            "run_id": self.run_id,
            "position": self._position,
            "name": name,
            "status": "skipped",
            "started_at": datetime.now(UTC),
            "duration_ms": 0,
            "rows_in": None,
            "rows_out": None,
            "detail": {"reason": reason},
        }
        self._pending_steps.append(row)
        self.steps.append(row)
        self.log("info", "step.skipped", step=name, reason=reason)

    def checkpoint(self) -> None:
        """Persist new steps and log lines in their own short transaction."""
        if not self._pending_logs and not self._pending_steps:
            return
        with self.db.session() as s:
            if self._pending_steps:
                s.execute(insert(RunStep), self._pending_steps)
            if self._pending_logs:
                s.execute(insert(RunLog), self._pending_logs)
        self._pending_logs.clear()
        self._pending_steps.clear()
