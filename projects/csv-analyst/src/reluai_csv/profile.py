"""Profile a table and report data-quality problems before anyone asks a question.

Everything here is computed with SQL inside the DuckDB sandbox. Identifiers come from the
table's own catalogue and are quoted; no visitor text is involved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import duckdb

from reluai_csv.compile import quote_ident
from reluai_csv.schema import ColumnKind, kind_from_sql_type

Severity = Literal["warning", "info"]
KNOWN_VALUES_MAX = 60  # text columns with at most this many distinct values get a value list
TOP_VALUES = 5


@dataclass(slots=True)
class ColumnProfile:
    name: str
    kind: ColumnKind
    sql_type: str
    non_null: int
    nulls: int
    distinct: int
    min: str | None = None
    max: str | None = None
    mean: float | None = None
    top_values: list[tuple[str, int]] = field(default_factory=list)
    values: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Finding:
    severity: Severity
    code: str
    message: str
    column: str | None = None
    count: int | None = None


@dataclass(slots=True)
class Profile:
    table: str
    rows: int
    duplicate_rows: int
    columns: list[ColumnProfile]
    findings: list[Finding]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Profile:
        return cls(
            table=data["table"],
            rows=data["rows"],
            duplicate_rows=data["duplicate_rows"],
            columns=[
                ColumnProfile(
                    **{
                        **c,
                        "top_values": [tuple(v) for v in c.get("top_values", [])],
                    }
                )
                for c in data["columns"]
            ],
            findings=[Finding(**f) for f in data["findings"]],
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "0%"


def _n(count: int, noun: str, verb: tuple[str, str] | None = None) -> str:
    """'1 row is', '3 rows are': counts in findings read as sentences."""
    one = count == 1
    text = f"{count:,} {noun if one else noun + 's'}"
    return f"{text} {verb[0] if one else verb[1]}" if verb else text


def profile_table(  # noqa: PLR0912
    con: duckdb.DuckDBPyConnection, table: str
) -> Profile:
    t = quote_ident(table)
    described = con.execute(f"DESCRIBE {t}").fetchall()
    first_row = con.execute(f"SELECT count(*) FROM {t}").fetchone()  # noqa: S608
    rows = int(first_row[0]) if first_row else 0
    dup_row = con.execute(
        f"SELECT {rows} - count(*) FROM (SELECT DISTINCT * FROM {t})"  # noqa: S608 - ints/idents
    ).fetchone()
    duplicates = int(dup_row[0]) if dup_row else 0
    columns: list[ColumnProfile] = []
    findings: list[Finding] = []
    if duplicates:
        findings.append(
            Finding(
                "warning",
                "duplicate_rows",
                f"{_n(duplicates, 'row')} ({_pct(duplicates, rows)}) "
                f"{'is an exact copy' if duplicates == 1 else 'are exact copies'} of another row.",
                count=duplicates,
            )
        )

    for name, sql_type, *_ in described:
        kind = kind_from_sql_type(str(sql_type))
        c = quote_ident(str(name))
        stats = con.execute(
            f"SELECT count({c}), count(DISTINCT {c}) FROM {t}"  # noqa: S608
        ).fetchone()
        non_null, distinct = (int(stats[0]), int(stats[1])) if stats else (0, 0)
        col = ColumnProfile(
            name=str(name),
            kind=kind,
            sql_type=str(sql_type),
            non_null=non_null,
            nulls=rows - non_null,
            distinct=distinct,
        )
        if kind in {"integer", "number", "date"} and non_null:
            mm = con.execute(f"SELECT min({c}), max({c}) FROM {t}").fetchone()  # noqa: S608
            if mm:
                col.min, col.max = _text(mm[0]), _text(mm[1])
        if kind in {"integer", "number"} and non_null:
            mean = con.execute(f"SELECT avg({c})::DOUBLE FROM {t}").fetchone()  # noqa: S608
            col.mean = round(float(mean[0]), 4) if mean and mean[0] is not None else None
            neg = con.execute(f"SELECT count(*) FROM {t} WHERE {c} < 0").fetchone()  # noqa: S608
            negatives = int(neg[0]) if neg else 0
            if negatives:
                findings.append(
                    Finding(
                        "info",
                        "negative_values",
                        f"{_n(negatives, 'row', ('has', 'have'))} a negative {name}.",
                        column=str(name),
                        count=negatives,
                    )
                )
        if kind in {"text", "boolean"} and non_null:
            top = con.execute(
                f"SELECT {c}, count(*) AS n FROM {t} WHERE {c} IS NOT NULL "  # noqa: S608
                f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT {TOP_VALUES}"
            ).fetchall()
            col.top_values = [(_text(v) or "", int(n)) for v, n in top]
        if kind == "text" and 0 < distinct <= KNOWN_VALUES_MAX:
            vals = con.execute(
                f"SELECT {c} FROM {t} WHERE {c} IS NOT NULL "  # noqa: S608
                f"GROUP BY 1 ORDER BY count(*) DESC, 1"
            ).fetchall()
            col.values = [str(v[0]) for v in vals if len(str(v[0])) <= 60]
        columns.append(col)

        # ---------------------------------------------------------- findings
        if rows and non_null == 0:
            findings.append(
                Finding("warning", "empty_column", f"'{name}' is empty.", column=str(name))
            )
        elif rows and col.nulls / rows >= 0.2:
            findings.append(
                Finding(
                    "warning",
                    "mostly_missing",
                    f"'{name}' is missing in {col.nulls:,} rows ({_pct(col.nulls, rows)}).",
                    column=str(name),
                    count=col.nulls,
                )
            )
        elif col.nulls:
            findings.append(
                Finding(
                    "info",
                    "missing_values",
                    f"'{name}' is missing in {col.nulls:,} rows ({_pct(col.nulls, rows)}).",
                    column=str(name),
                    count=col.nulls,
                )
            )
        if rows > 1 and distinct == 1:
            findings.append(
                Finding(
                    "info",
                    "constant_column",
                    f"'{name}' has the same value in every row.",
                    column=str(name),
                )
            )
        if kind == "text" and non_null:
            findings.extend(_text_findings(con, t, c, str(name), non_null))

    return Profile(table, rows, duplicates, columns, findings)


def _text_findings(
    con: duckdb.DuckDBPyConnection, t: str, c: str, name: str, non_null: int
) -> list[Finding]:
    out: list[Finding] = []
    row = con.execute(
        f"""SELECT
              count(*) FILTER (WHERE TRY_CAST(replace({c}, ',', '') AS DOUBLE) IS NOT NULL),
              count(*) FILTER (WHERE TRY_CAST({c} AS DATE) IS NOT NULL
                                  OR TRY_CAST({c} AS TIMESTAMP) IS NOT NULL),
              count(*) FILTER (WHERE {c} <> trim({c})),
              count(*) FILTER (WHERE regexp_matches({c}, '^[=+@]')
                                  OR regexp_matches({c}, '^-[^0-9.]')),
              count(*) FILTER (
                  WHERE regexp_matches({c}, '^-?[0-9]{{1,3}}(,[0-9]{{3}})+([.][0-9]+)?$'))
            FROM {t} WHERE {c} IS NOT NULL"""  # noqa: S608
    ).fetchone()
    if not row:
        return out
    numeric, dates, spaced, formula, grouped = (int(v) for v in row)
    if numeric == non_null and grouped:
        out.append(
            Finding(
                "warning",
                "numbers_stored_as_text",
                f"Every value in '{name}' is a number, but {_n(grouped, 'value', ('is', 'are'))} "
                "written with "
                "thousands separators (1,200), so the column was read as text and cannot be "
                "summed or averaged.",
                column=name,
                count=grouped,
            )
        )
    elif numeric < non_null and numeric / non_null >= 0.9:
        out.append(
            Finding(
                "warning",
                "numbers_stored_as_text",
                f"'{name}' looks numeric but "
                f"{_n(non_null - numeric, 'value', ('is not a number', 'are not numbers'))}, "
                "so it was read as text.",
                column=name,
                count=non_null - numeric,
            )
        )
    if dates < non_null and dates / non_null >= 0.9:
        out.append(
            Finding(
                "warning",
                "dates_stored_as_text",
                f"'{name}' looks like dates but "
                f"{_n(non_null - dates, 'value', ('does', 'do'))} not parse, "
                "so it was read as text.",
                column=name,
                count=non_null - dates,
            )
        )
    if spaced:
        out.append(
            Finding(
                "info",
                "untrimmed_text",
                f"{_n(spaced, 'value')} in '{name}' "
                f"{'starts or ends' if spaced == 1 else 'start or end'} with spaces.",
                column=name,
                count=spaced,
            )
        )
    if formula:
        out.append(
            Finding(
                "warning",
                "formula_like_text",
                f"{_n(formula, 'value')} in '{name}' {'starts' if formula == 1 else 'start'} with "
                "=, +, - or @ and would run as "
                "formulas in a spreadsheet. Downloads from this page neutralise them.",
                column=name,
                count=formula,
            )
        )
    return out
