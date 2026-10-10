"""Turn a validated plan into parameterised SQL, equivalent pandas code and a plain summary.

Identifiers come only from the table's own column list and are always quoted; every value
is a bound parameter. The SQL shown to visitors has the parameters inlined for readability,
but the query that runs is the parameterised one. The pandas code is for reading only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from reluai_csv.plan import Chart, Filter, Metric, QueryPlan
from reluai_csv.schema import DatasetSchema
from reluai_csv.validate import parse_iso

_GRAIN_SQL = {"day": "day", "week": "week", "month": "month", "quarter": "quarter", "year": "year"}
_GRAIN_LABEL = {
    "day": "Day",
    "week": "Week starting",
    "month": "Month",
    "quarter": "Quarter starting",
    "year": "Year",
}
_GRAIN_PANDAS = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
_AGG_SQL = {"sum": "sum", "avg": "avg", "min": "min", "max": "max"}
_AGG_WORD = {
    "count": "number of",
    "count_distinct": "number of distinct",
    "sum": "total",
    "avg": "average",
    "min": "lowest",
    "max": "highest",
}
_OP_SQL = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_OP_WORD = {
    "eq": "is",
    "ne": "is not",
    "gt": "above",
    "gte": "at least",
    "lt": "below",
    "lte": "at most",
}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def metric_alias(m: Metric) -> str:
    if m.column is None:
        return "rows"
    if m.agg == "count_distinct":
        return f"distinct_{m.column}"
    return f"{m.agg}_{m.column}"


@dataclass(frozen=True, slots=True)
class OutputColumn:
    name: str
    role: str  # "time" | "group" | "metric"
    kind: str
    label: str


@dataclass(frozen=True, slots=True)
class Compiled:
    sql: str
    params: list[object]
    display_sql: str
    pandas: str
    summary: str
    chart: Chart
    columns: list[OutputColumn]


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _next_day(value: str) -> str:
    return (parse_iso(value) + timedelta(days=1)).isoformat()


def _where(f: Filter, kind: str, params: list[object]) -> str:  # noqa: PLR0911
    col = quote_ident(f.column)
    is_date = kind == "date"
    if f.op == "is_null":
        return f"{col} IS NULL"
    if f.op == "not_null":
        return f"{col} IS NOT NULL"
    if f.op in {"in", "not_in"}:
        values = f.value if isinstance(f.value, list) else [f.value]
        params.extend(values)
        marks = ", ".join("?" for _ in values)
        return f"{col} {'NOT IN' if f.op == 'not_in' else 'IN'} ({marks})"
    if f.op == "contains":
        params.append(f"%{_escape_like(str(f.value))}%")
        return f"{col} ILIKE ? ESCAPE '\\'"
    if f.op == "between":
        assert isinstance(f.value, list)  # noqa: S101 - validated
        low, high = f.value
        if is_date:
            params.extend([low, _next_day(str(high))])
            return f"{col} >= CAST(? AS DATE) AND {col} < CAST(? AS DATE)"
        params.extend([low, high])
        return f"{col} BETWEEN ? AND ?"
    if is_date:
        value = str(f.value)
        # Whole days: "after 2011-03-04" starts the next day; "until" includes the whole day.
        if f.op in {"gt", "lte"}:
            params.append(_next_day(value))
            return f"{col} {'>=' if f.op == 'gt' else '<'} CAST(? AS DATE)"
        params.append(value)
        return f"{col} {'>=' if f.op == 'gte' else '<'} CAST(? AS DATE)"
    params.append(f.value)
    return f"{col} {_OP_SQL[f.op]} ?"


def _metric_sql(m: Metric) -> str:
    if m.column is None:
        return "count(*)"
    col = quote_ident(m.column)
    if m.agg == "count":
        return f"count({col})"
    if m.agg == "count_distinct":
        return f"count(DISTINCT {col})"
    return f"{_AGG_SQL[m.agg]}({col})"


def choose_chart(plan: QueryPlan) -> Chart:
    """The chart for a result shape; a suggested chart is used only if it fits the shape."""
    fits = {
        "number": plan.dimensions == 0 and len(plan.metrics) == 1,
        "line": plan.time_bucket is not None and not plan.group_by,
        "bar": plan.dimensions == 1,
        "table": True,
    }
    if plan.chart and fits[plan.chart]:
        return plan.chart
    if plan.dimensions == 0:
        return "number" if len(plan.metrics) == 1 else "table"
    if plan.time_bucket and not plan.group_by:
        return "line"
    if plan.dimensions == 1 and len(plan.metrics) == 1:
        return "bar"
    return "table"


def _order(plan: QueryPlan, dims: list[str], aliases: list[str]) -> str:
    sort = plan.sort
    if sort is None:
        sort = "group_asc" if plan.time_bucket else ("metric_desc" if dims else None)
    if sort is None:
        return ""
    if sort in {"metric_desc", "metric_asc"}:
        direction = "DESC" if sort == "metric_desc" else "ASC"
        tie = (", " + ", ".join(quote_ident(d) for d in dims)) if dims else ""
        return f" ORDER BY {quote_ident(aliases[0])} {direction} NULLS LAST{tie}"
    if not dims:
        return ""
    direction = "DESC" if sort == "group_desc" else "ASC"
    return " ORDER BY " + ", ".join(f"{quote_ident(d)} {direction} NULLS LAST" for d in dims)


def compile_plan(plan: QueryPlan, schema: DatasetSchema) -> Compiled:
    params: list[object] = []
    select: list[str] = []
    dims: list[str] = []
    out: list[OutputColumn] = []
    if plan.time_bucket:
        tb = plan.time_bucket
        # A table may have its own "month" column; the bucket must not share its name.
        alias: str = tb.grain if tb.grain not in schema.names else f"{tb.grain}_start"
        select.append(
            f"CAST(date_trunc('{_GRAIN_SQL[tb.grain]}', {quote_ident(tb.column)}) AS DATE)"
            f" AS {quote_ident(alias)}"
        )
        dims.append(alias)
        out.append(OutputColumn(alias, "time", "date", _GRAIN_LABEL[tb.grain]))
    for g in plan.group_by:
        col = schema.column(g)
        select.append(quote_ident(g))
        dims.append(g)
        label = col.label if col else g
        out.append(
            OutputColumn(g, "group", col.kind if col else "text", label[:1].upper() + label[1:])
        )
    aliases = [metric_alias(m) for m in plan.metrics]
    for m, alias in zip(plan.metrics, aliases, strict=True):
        select.append(f"{_metric_sql(m)} AS {quote_ident(alias)}")
        kind = "integer" if m.agg in {"count", "count_distinct"} else "number"
        if m.agg in {"min", "max"} and m.column:
            col = schema.column(m.column)
            kind = col.kind if col else kind
        words = _metric_words(m, schema)
        out.append(OutputColumn(alias, "metric", kind, words[:1].upper() + words[1:]))

    where_parts: list[str] = []
    for f in plan.filters:
        col = schema.column(f.column)
        where_parts.append(_where(f, col.kind if col else "text", params))
    # Identifiers are quoted names from the table's own catalogue; every value is a parameter.
    sql = f"SELECT {', '.join(select)} FROM {quote_ident(schema.table)}"  # noqa: S608
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if dims:
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(dims)))
    sql += _order(plan, dims, aliases)
    sql += " LIMIT ?"
    params.append(plan.limit)

    return Compiled(
        sql=sql,
        params=params,
        display_sql=_display_sql(sql, params),
        pandas=_pandas(plan, schema, aliases),
        summary=summarise(plan, schema),
        chart=choose_chart(plan),
        columns=out,
    )


def _display_sql(sql: str, params: list[object]) -> str:
    """Inline the parameters for display only (the query runs with bound parameters)."""
    parts = sql.split("?")
    text = parts[0]
    for value, rest in zip(params, parts[1:], strict=True):
        text += _literal(value) + rest
    return (
        text.replace(" FROM ", "\nFROM ")
        .replace(" WHERE ", "\nWHERE ")
        .replace(" AND ", "\n  AND ")
        .replace(" GROUP BY ", "\nGROUP BY ")
        .replace(" ORDER BY ", "\nORDER BY ")
        .replace(" LIMIT ", "\nLIMIT ")
    )


# ------------------------------------------------------------------ pandas (read-only text)
def _pandas_filter(f: Filter, kind: str) -> str:  # noqa: PLR0911
    col = f"df[{f.column!r}]"
    if f.op == "is_null":
        return f"{col}.isna()"
    if f.op == "not_null":
        return f"{col}.notna()"
    if f.op in {"in", "not_in"}:
        expr = f"{col}.isin({f.value!r})"
        # SQL's NOT IN and != leave out missing values; pandas keeps them unless told.
        return f"{col}.notna() & ~{expr}" if f.op == "not_in" else expr
    if f.op == "contains":
        return f"{col}.str.contains({f.value!r}, case=False, regex=False, na=False)"
    if f.op == "between":
        assert isinstance(f.value, list)  # noqa: S101 - validated
        low, high = f.value
        if kind == "date":
            return f"({col} >= {low!r}) & ({col} < {_next_day(str(high))!r})"
        return f"{col}.between({low!r}, {high!r})"
    value = f.value
    if kind == "date":
        value = _next_day(str(value)) if f.op in {"gt", "lte"} else value
        op = {"gt": ">=", "gte": ">=", "lt": "<", "lte": "<"}[f.op]
        return f"({col} {op} {value!r})"
    if f.op == "ne":
        return f"{col}.notna() & ({col} != {value!r})"
    op = {"eq": "==", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[f.op]
    return f"({col} {op} {value!r})"


def _pandas(plan: QueryPlan, schema: DatasetSchema, aliases: list[str]) -> str:  # noqa: PLR0912
    lines = ["import pandas as pd", "", f"df = ...  # the {schema.table} table as a DataFrame"]
    if plan.filters:
        conds = []
        for f in plan.filters:
            col = schema.column(f.column)
            conds.append(_pandas_filter(f, col.kind if col else "text"))
        lines.append("df = df[" + " & ".join(conds) + "]")
    keys: list[str] = []
    if plan.time_bucket:
        tb = plan.time_bucket
        lines.append(
            f"df = df.assign({tb.grain}=df[{tb.column!r}].dt.to_period("
            f"{_GRAIN_PANDAS[tb.grain]!r}).dt.start_time)"
        )
        keys.append(tb.grain)
    keys.extend(plan.group_by)
    aggs = []
    for m, alias in zip(plan.metrics, aliases, strict=True):
        if m.column is None:
            source, func = (keys[0] if keys else "index"), "size"
        else:
            source = m.column
            func = {"count": "count", "count_distinct": "nunique"}.get(m.agg, m.agg)
            func = "mean" if func == "avg" else func
        aggs.append(f"{alias}=({source!r}, {func!r})")
    if keys:
        lines.append("result = (")
        lines.append(f"    df.groupby({keys!r}, as_index=False, dropna=False)")
        lines.append(f"    .agg({', '.join(aggs)})")
        sort = plan.sort or ("group_asc" if plan.time_bucket else "metric_desc")
        if sort.startswith("metric"):
            lines.append(f"    .sort_values({aliases[0]!r}, ascending={sort == 'metric_asc'})")
        else:
            lines.append(f"    .sort_values({keys!r}, ascending={sort == 'group_asc'})")
        lines.append(f"    .head({plan.limit})")
        lines.append(")")
    else:
        parts = []
        for m, alias in zip(plan.metrics, aliases, strict=True):
            if m.column is None:
                parts.append(f"{alias!r}: len(df)")
            else:
                func = {"count": "count", "count_distinct": "nunique", "avg": "mean"}.get(
                    m.agg, m.agg
                )
                parts.append(f"{alias!r}: df[{m.column!r}].{func}()")
        lines.append("result = {" + ", ".join(parts) + "}")
    return "\n".join(lines)


# ------------------------------------------------------------------ plain-English summary
def _metric_words(m: Metric, schema: DatasetSchema) -> str:
    if m.column is None:
        return f"number of {schema.row_noun}"
    col = schema.column(m.column)
    if m.agg == "count_distinct" and col is not None and col.entity:
        return f"number of distinct {col.entity}"
    label = col.label if col else m.column
    return f"{_AGG_WORD[m.agg]} {label}"


def _fmt_date(value: str) -> str:
    d = parse_iso(value)
    return f"{d.day} {d.strftime('%b %Y')}"


def _filter_words(f: Filter, schema: DatasetSchema) -> str:  # noqa: PLR0911
    col = schema.column(f.column)
    label = col.label if col else f.column
    if f.op == "is_null":
        return f"{label} is missing"
    if col is not None and col.kind == "boolean" and f.op == "eq":
        return f"{label}: {'yes' if f.value else 'no'}"
    if f.op == "not_null":
        return f"{label} is present"
    if f.op in {"in", "not_in"}:
        values = f.value if isinstance(f.value, list) else [f.value]
        joined = ", ".join(str(v) for v in values)
        return f"{label} {'is not' if f.op == 'not_in' else 'is'} one of {joined}"
    if f.op == "contains":
        return f"{label} contains “{f.value}”"
    if f.op == "between":
        assert isinstance(f.value, list)  # noqa: S101 - validated
        low, high = f.value
        if col is not None and col.kind == "date":
            if low == high:
                return f"{label} on {_fmt_date(str(low))}"
            return f"{label} from {_fmt_date(str(low))} to {_fmt_date(str(high))}"
        return f"{label} between {low} and {high}"
    if col is not None and col.kind == "date":
        word = {"gt": "after", "gte": "from", "lt": "before", "lte": "up to"}[f.op]
        return f"{label} {word} {_fmt_date(str(f.value))}"
    return f"{label} {_OP_WORD[f.op]} {f.value}"


def summarise(plan: QueryPlan, schema: DatasetSchema) -> str:
    metrics = " and ".join(_metric_words(m, schema) for m in plan.metrics)
    text = metrics[0].upper() + metrics[1:]
    groups = []
    if plan.time_bucket:
        groups.append(f"per {plan.time_bucket.grain}")
    for g in plan.group_by:
        col = schema.column(g)
        groups.append(f"by {col.label if col else g}")
    if groups:
        text += " " + ", ".join(groups)
    if plan.filters:
        text += ", where " + " and ".join(_filter_words(f, schema) for f in plan.filters)
    if plan.dimensions:
        sort = plan.sort or ("group_asc" if plan.time_bucket else "metric_desc")
        if sort in {"metric_desc", "metric_asc"}:
            word = "highest" if sort == "metric_desc" else "lowest"
            text += f"; only the {word}" if plan.limit == 1 else f"; {word} {plan.limit} first"
        elif plan.limit < 100:
            text += f"; first {plan.limit}"
    return text + "."
