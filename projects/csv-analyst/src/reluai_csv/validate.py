"""Check a query plan against the table and normalise it.

Structural checks (types, lengths, allowed operators) come from the Pydantic model. This
module adds everything that depends on the table: the columns exist, aggregations suit the
column type, filter values can be converted to the column's type, and known category values
are spelled the way the data spells them. Problems come back as a list the LLM can read and
correct; a plan with any problem is never compiled.
"""

from __future__ import annotations

import calendar
import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from reluai_csv.plan import Filter, Metric, QueryPlan, Scalar, TimeBucket
from reluai_csv.schema import ORDERED_KINDS, ColumnInfo, DatasetSchema

MAX_IN_VALUES = 20
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:[T ][0-9:.]+)?$")


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class Validated:
    plan: QueryPlan | None
    issues: list[Issue]

    @property
    def ok(self) -> bool:
        return self.plan is not None and not self.issues


def period(text: str) -> tuple[date, date] | None:
    """'2011' → whole year, '2011-03' → whole month, '2011-03-04' → that day (inclusive)."""
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), m.group(2), m.group(3)
    try:
        if month is None:
            return date(year, 1, 1), date(year, 12, 31)
        mon = int(month)
        if day is None:
            return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])
        d = date(year, mon, int(day))
    except ValueError:
        return None
    return d, d


class _Checker:
    def __init__(self, schema: DatasetSchema) -> None:
        self.schema = schema
        self.issues: list[Issue] = []

    def issue(self, path: str, code: str, message: str) -> None:
        self.issues.append(Issue(path, code, message))

    def resolve(self, name: str, path: str) -> ColumnInfo | None:
        col = self.schema.column(name)
        if col is None:
            close = difflib.get_close_matches(name, self.schema.names, n=3, cutoff=0.5)
            if close:
                hint = f" Did you mean: {', '.join(close)}?"
            else:  # tables have at most 50 columns, so listing them all stays short
                hint = f" The columns are: {', '.join(self.schema.names)}."
            self.issue(path, "unknown_column", f"Column '{name}' does not exist.{hint}")
        return col

    # -------------------------------------------------------------- metrics
    def metric(self, i: int, m: Metric) -> Metric:
        path = f"metrics[{i}]"
        if m.column is None:
            if m.agg != "count":
                self.issue(path, "column_required", f"'{m.agg}' needs a column.")
            return m
        col = self.resolve(m.column, f"{path}.column")
        if col is None:
            return m
        if col.kind == "other":
            self.issue(path, "unsupported_type", f"Column '{col.name}' cannot be aggregated.")
        elif m.agg in {"sum", "avg"} and not col.numeric:
            self.issue(
                path,
                "type_mismatch",
                f"'{m.agg}' needs a numeric column; '{col.name}' is {col.kind}.",
            )
        elif m.agg in {"min", "max"} and col.kind not in ORDERED_KINDS:
            self.issue(
                path,
                "type_mismatch",
                f"'{m.agg}' needs a numeric or date column; '{col.name}' is {col.kind}.",
            )
        return Metric(agg=m.agg, column=col.name)

    # -------------------------------------------------------------- groups
    def group(self, i: int, name: str) -> str | None:
        col = self.resolve(name, f"group_by[{i}]")
        if col is None:
            return None
        if col.kind == "date":
            self.issue(
                f"group_by[{i}]",
                "use_time_bucket",
                f"'{col.name}' is a date; use time_bucket to group it by day, month or year.",
            )
        elif col.kind == "other":
            self.issue(f"group_by[{i}]", "unsupported_type", f"Cannot group by '{col.name}'.")
        return col.name

    def bucket(self, tb: TimeBucket) -> TimeBucket:
        col = self.resolve(tb.column, "time_bucket.column")
        if col is None:
            return tb
        if col.kind != "date":
            self.issue("time_bucket.column", "type_mismatch", f"'{col.name}' is not a date.")
        return TimeBucket(column=col.name, grain=tb.grain)

    # -------------------------------------------------------------- filters
    def coerce(self, col: ColumnInfo, value: Scalar, path: str) -> Scalar | None:  # noqa: PLR0911
        if isinstance(value, bool) and col.kind != "boolean":
            self.issue(path, "type_mismatch", f"'{col.name}' is {col.kind}, not true/false.")
            return None
        if col.kind in {"integer", "number"}:
            number = _to_number(value)
            if number is None:
                self.issue(path, "type_mismatch", f"'{value}' is not a number ('{col.name}').")
                return None
            if col.kind == "integer" and float(number).is_integer():
                return int(number)
            return number
        if col.kind == "boolean":
            flag = _to_bool(value)
            if flag is None:
                self.issue(path, "type_mismatch", f"'{col.name}' takes true or false.")
            return flag
        if col.kind == "date":
            text = str(value)
            if period(text) is None:
                self.issue(
                    path, "bad_date", f"'{text}' is not a date (use YYYY, YYYY-MM or YYYY-MM-DD)."
                )
                return None
            return text
        text = str(value).strip()
        if not text or len(text) > 100:
            self.issue(path, "bad_value", "Text values must be 1 to 100 characters.")
            return None
        if col.values:
            canonical = {v.lower(): v for v in col.values}
            hit = canonical.get(text.lower())
            if hit is None:
                close = difflib.get_close_matches(text, col.values, n=3, cutoff=0.6)
                hint = f" Close matches: {', '.join(close)}." if close else ""
                self.issue(path, "unknown_value", f"'{text}' does not occur in '{col.name}'.{hint}")
                return None
            return hit
        return text

    def filter(self, i: int, f: Filter) -> Filter:  # noqa: PLR0911, PLR0912, PLR0915
        path = f"filters[{i}]"
        col = self.resolve(f.column, f"{path}.column")
        if col is None:
            return f
        if col.kind == "other":
            self.issue(path, "unsupported_type", f"Cannot filter on '{col.name}'.")
            return f
        op, value = f.op, f.value
        if op in {"is_null", "not_null"}:
            return Filter(column=col.name, op=op, value=None)
        if value is None:
            self.issue(f"{path}.value", "value_required", f"'{op}' needs a value.")
            return f
        if op in {"in", "not_in"}:
            items = value if isinstance(value, list) else [value]
            if not 1 <= len(items) <= MAX_IN_VALUES:
                self.issue(f"{path}.value", "bad_value", f"'{op}' takes 1 to 20 values.")
                return f
            members = [self.coerce(col, v, f"{path}.value[{j}]") for j, v in enumerate(items)]
            if col.kind == "date":
                self.issue(path, "type_mismatch", "Use 'between' for date ranges.")
            kept: list[Scalar] = [v for v in members if v is not None]
            return Filter(column=col.name, op=op, value=kept)
        if op == "between":
            if not isinstance(value, list) or len(value) != 2:
                self.issue(f"{path}.value", "bad_value", "'between' takes [low, high].")
                return f
            if col.kind not in ORDERED_KINDS:
                self.issue(path, "type_mismatch", "'between' needs a number or date column.")
                return f
            low = self.coerce(col, value[0], f"{path}.value[0]")
            high = self.coerce(col, value[1], f"{path}.value[1]")
            if low is None or high is None:
                return f
            if col.kind == "date":
                lo, hi = period(str(low)), period(str(high))
                assert lo is not None  # noqa: S101 - coerce checked
                assert hi is not None  # noqa: S101
                low, high = lo[0].isoformat(), hi[1].isoformat()
            n_low, n_high = _to_number(low), _to_number(high)
            if n_low is not None and n_high is not None:
                if n_low > n_high:
                    self.issue(f"{path}.value", "bad_range", "Low is greater than high.")
            elif str(low) > str(high):
                self.issue(f"{path}.value", "bad_range", "Start is after end.")
            return Filter(column=col.name, op="between", value=[low, high])
        if isinstance(value, list):
            self.issue(f"{path}.value", "bad_value", f"'{op}' takes a single value.")
            return f
        if op == "contains":
            if col.kind != "text":
                self.issue(path, "type_mismatch", "'contains' works on text columns.")
                return f
            text = str(value).strip()
            if not 1 <= len(text) <= 100:
                self.issue(f"{path}.value", "bad_value", "Search text must be 1 to 100 characters.")
                return f
            return Filter(column=col.name, op=op, value=text)
        if op in {"gt", "gte", "lt", "lte"} and col.kind not in ORDERED_KINDS:
            self.issue(path, "type_mismatch", f"'{op}' needs a number or date column.")
            return f
        coerced = self.coerce(col, value, f"{path}.value")
        if coerced is None:
            return f
        if col.kind == "date":
            span = period(str(coerced))
            assert span is not None  # noqa: S101 - coerce checked
            start, end = span[0].isoformat(), span[1].isoformat()
            if op == "eq":
                return Filter(column=col.name, op="between", value=[start, end])
            if op == "ne":
                self.issue(path, "type_mismatch", "Use 'lt'/'gt' to exclude dates.")
                return f
            # Comparisons with a period use its start or end, so "before 2011" means < 1 Jan 2011.
            bound = end if op in {"gt", "lte"} else start
            return Filter(column=col.name, op=op, value=bound)
        return Filter(column=col.name, op=op, value=coerced)


def _to_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    text = str(value).strip().replace(",", "").lstrip("£$€")
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() and "." not in text else number


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "y"}:
        return True
    if text in {"false", "no", "0", "n"}:
        return False
    return None


def validate_plan(plan: QueryPlan, schema: DatasetSchema) -> Validated:
    c = _Checker(schema)
    metrics = [c.metric(i, m) for i, m in enumerate(plan.metrics)]
    groups: list[str] = []
    for i, g in enumerate(plan.group_by):
        name = c.group(i, g)
        if name is not None and name not in groups:
            groups.append(name)
    bucket = c.bucket(plan.time_bucket) if plan.time_bucket else None
    filters = [c.filter(i, f) for i, f in enumerate(plan.filters)]
    if len(groups) + (1 if bucket else 0) > 2:
        c.issue("group_by", "too_many_groups", "Group by at most two things, including time.")
    if c.issues:
        return Validated(None, c.issues)
    normalised = QueryPlan(
        metrics=metrics,
        group_by=groups,
        time_bucket=bucket,
        filters=filters,
        sort=plan.sort,
        limit=plan.limit,
        chart=plan.chart,
    )
    return Validated(normalised, [])


def parse_iso(value: str) -> date:
    """Dates in validated plans are always full ISO dates."""
    return datetime.strptime(value[:10], "%Y-%m-%d").date()  # noqa: DTZ007 - calendar dates
