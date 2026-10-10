"""The DuckDB sandbox holds even if hostile SQL ever reached it.

The compiler never produces these statements; the tests feed them to the sandbox directly
to show that a bug upstream could still not read files, write, load extensions or change
the configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reluai_csv import sandbox
from reluai_csv.sandbox import QueryFailedError, QueryTimeoutError, SandboxBusyError, run_query
from reluai_csv.settings import CsvSettings


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/hostname')",
        "SELECT * FROM 'https://example.com/data.csv'",
        "COPY sales TO '/tmp/reluai-exfiltrated.csv'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "ATTACH '/tmp/reluai-other.duckdb' AS other",
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "SET memory_limit = '8GB'",
        "PRAGMA threads = 8",
        "CREATE TABLE stolen AS SELECT * FROM sales",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "UPDATE sales SET revenue = 0",
        "EXPORT DATABASE '/tmp/reluai-export'",
    ],
)
def test_hostile_statements_fail(sql: str, csv_settings: CsvSettings) -> None:
    with pytest.raises(QueryFailedError):
        run_query(csv_settings.bundled_db, sql, [], csv_settings, max_rows=5)
    assert not Path("/tmp/reluai-exfiltrated.csv").exists()  # noqa: S108


def test_table_is_unchanged_after_hostile_statements(csv_settings: CsvSettings) -> None:
    result = run_query(
        csv_settings.bundled_db, "SELECT count(*) FROM sales", [], csv_settings, max_rows=1
    )
    assert result.rows[0][0] > 0


def test_slow_queries_are_interrupted(csv_settings: CsvSettings) -> None:
    quick = csv_settings.model_copy(update={"query_timeout_seconds": 0.2})
    with pytest.raises(QueryTimeoutError):
        run_query(
            quick.bundled_db,
            "SELECT count(*) FROM range(100000000000) a",
            [],
            quick,
            max_rows=1,
        )
    # The connection is still usable afterwards.
    result = run_query(quick.bundled_db, "SELECT 1", [], quick, max_rows=1)
    assert result.rows == [[1]]


def test_one_query_at_a_time(monkeypatch: pytest.MonkeyPatch, csv_settings: CsvSettings) -> None:
    monkeypatch.setattr(sandbox, "_SLOT_WAIT_SECONDS", 0.05)
    assert sandbox._SLOT.acquire(timeout=1)
    try:
        with pytest.raises(SandboxBusyError):
            run_query(csv_settings.bundled_db, "SELECT 1", [], csv_settings, max_rows=1)
    finally:
        sandbox._SLOT.release()


def test_rows_are_capped(csv_settings: CsvSettings) -> None:
    result = run_query(
        csv_settings.bundled_db, "SELECT * FROM range(10)", [], csv_settings, max_rows=3
    )
    assert result.truncated
    assert len(result.rows) == 3


def test_missing_table_file(tmp_path: Path, csv_settings: CsvSettings) -> None:
    with pytest.raises(QueryFailedError):
        run_query(tmp_path / "gone.duckdb", "SELECT 1", [], csv_settings, max_rows=1)


def test_connection_settings_are_locked(csv_settings: CsvSettings) -> None:
    result = run_query(
        csv_settings.bundled_db,
        "SELECT current_setting('enable_external_access'), current_setting('threads'), "
        "current_setting('lock_configuration')",
        [],
        csv_settings,
        max_rows=1,
    )
    assert result.rows == [[False, 1, True]]
