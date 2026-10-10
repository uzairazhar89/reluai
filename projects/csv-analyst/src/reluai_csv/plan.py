"""The query plan: the only thing an interpreter (rules or LLM) may produce.

A plan is data, never code. It names an aggregation, optional groupings, filters and a
limit, using column names that must exist in the table. The validator checks it against the
table, the compiler turns it into parameterised SQL, and nothing a model writes is ever
executed directly. Its JSON Schema is the tool definition the LLM fills in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

Aggregation = Literal["count", "count_distinct", "sum", "avg", "min", "max"]
Operator = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "between",
    "is_null",
    "not_null",
]
Grain = Literal["day", "week", "month", "quarter", "year"]
Sort = Literal["metric_desc", "metric_asc", "group_asc", "group_desc"]
Chart = Literal["number", "bar", "line", "table"]
Scalar = StrictStr | StrictBool | StrictInt | StrictFloat

MAX_LIMIT = 100


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agg: Aggregation = Field(description="Aggregation to compute")
    column: StrictStr | None = Field(
        default=None,
        max_length=64,
        description="Column to aggregate. Omit only for agg='count' (count of rows).",
    )


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    column: StrictStr = Field(max_length=64)
    op: Operator
    value: Scalar | list[Scalar] | None = Field(
        default=None,
        description=(
            "Comparison value. A list for 'in'/'not_in', [low, high] for 'between' "
            "(dates as 'YYYY-MM-DD'), omitted for 'is_null'/'not_null'."
        ),
    )


class TimeBucket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    column: StrictStr = Field(max_length=64, description="A date or timestamp column")
    grain: Grain


class QueryPlan(BaseModel):
    """Aggregate query over one table: metrics, optionally grouped and filtered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metrics: list[Metric] = Field(min_length=1, max_length=3)
    group_by: list[StrictStr] = Field(
        default_factory=list, max_length=2, description="Columns to group by (not dates)"
    )
    time_bucket: TimeBucket | None = Field(
        default=None, description="Group a date column by day/week/month/quarter/year"
    )
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    sort: Sort | None = Field(
        default=None,
        description="metric_* orders by the first metric; group_* by the groups/time",
    )
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)
    chart: Chart | None = Field(default=None, description="Suggested visualisation")

    @property
    def dimensions(self) -> int:
        return len(self.group_by) + (1 if self.time_bucket else 0)


class Refusal(BaseModel):
    """Arguments of the tool an LLM calls when the table cannot answer the question."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(min_length=3, max_length=300)


def plan_json_schema() -> dict[str, object]:
    schema = QueryPlan.model_json_schema()
    schema.pop("title", None)
    return schema
