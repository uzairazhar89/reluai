"""The validator: every plan, from the rules or a model, is checked against the table."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reluai_csv.evaluation import f, m, p
from reluai_csv.plan import QueryPlan, TimeBucket
from reluai_csv.schema import DatasetSchema
from reluai_csv.validate import period, validate_plan


def codes(plan: QueryPlan, schema: DatasetSchema) -> list[str]:
    return [i.code for i in validate_plan(plan, schema).issues]


def only_filter(plan: QueryPlan, schema: DatasetSchema) -> tuple[str, str, object]:
    checked = validate_plan(plan, schema)
    assert checked.ok, checked.issues
    assert checked.plan is not None
    (flt,) = checked.plan.filters
    return flt.column, flt.op, flt.value


def test_unknown_column_suggests_close_names(schema: DatasetSchema) -> None:
    issues = validate_plan(p([m("sum", "revenu")]), schema).issues
    assert [i.code for i in issues] == ["unknown_column"]
    assert "revenue" in issues[0].message


def test_column_names_are_case_insensitive_and_normalised(schema: DatasetSchema) -> None:
    checked = validate_plan(p([m("sum", "Revenue")], ["COUNTRY"]), schema)
    assert checked.plan is not None
    assert checked.plan.metrics[0].column == "revenue"
    assert checked.plan.group_by == ["country"]


@pytest.mark.parametrize(
    ("plan", "code"),
    [
        (p([m("sum", "country")]), "type_mismatch"),
        (p([m("avg", "description")]), "type_mismatch"),
        (p([m("max", "country")]), "type_mismatch"),
        (p([m("sum")]), "column_required"),
        (p([m("sum", "revenue")], ["invoiced_at"]), "use_time_bucket"),
        (
            QueryPlan(
                metrics=[m("sum", "revenue")],
                group_by=["country", "description"],
                time_bucket=TimeBucket(column="invoiced_at", grain="month"),
            ),
            "too_many_groups",
        ),
        (
            QueryPlan(
                metrics=[m("sum", "revenue")],
                time_bucket=TimeBucket(column="country", grain="month"),
            ),
            "type_mismatch",
        ),
        (p([m("count")], filters=[f("country", "eq", "Atlantis")]), "unknown_value"),
        (p([m("count")], filters=[f("quantity", "gt", "lots")]), "type_mismatch"),
        (p([m("count")], filters=[f("country", "eq", True)]), "type_mismatch"),
        (p([m("count")], filters=[f("invoiced_at", "eq", "last year")]), "bad_date"),
        (p([m("count")], filters=[f("quantity", "between", [10, 1])]), "bad_range"),
        (p([m("count")], filters=[f("quantity", "between", [1])]), "bad_value"),
        (p([m("count")], filters=[f("country", "between", ["A", "B"])]), "type_mismatch"),
        (p([m("count")], filters=[f("country", "in", [])]), "bad_value"),
        (p([m("count")], filters=[f("quantity", "contains", "1")]), "type_mismatch"),
        (p([m("count")], filters=[f("country", "gt", "France")]), "type_mismatch"),
        (p([m("count")], filters=[f("quantity", "eq")]), "value_required"),
        (p([m("count")], filters=[f("invoiced_at", "ne", "2011")]), "type_mismatch"),
    ],
)
def test_rejects(plan: QueryPlan, code: str, schema: DatasetSchema) -> None:
    assert code in codes(plan, schema)


def test_structural_limits_come_from_the_model() -> None:
    with pytest.raises(ValidationError):
        QueryPlan.model_validate({"metrics": []})
    with pytest.raises(ValidationError):
        QueryPlan.model_validate({"metrics": [{"agg": "sum", "column": "x"}], "limit": 1000})
    with pytest.raises(ValidationError):
        QueryPlan.model_validate({"metrics": [{"agg": "median", "column": "x"}]})
    with pytest.raises(ValidationError):  # no free-form SQL anywhere in a plan
        QueryPlan.model_validate({"metrics": [{"agg": "count"}], "where": "1=1"})


def test_number_values_accept_separators_and_currency(schema: DatasetSchema) -> None:
    plan = p([m("count")], filters=[f("revenue", "gte", "£1,250.50")])
    assert only_filter(plan, schema) == ("revenue", "gte", 1250.5)
    plan = p([m("count")], filters=[f("quantity", "lt", "12")])
    assert only_filter(plan, schema) == ("quantity", "lt", 12)


def test_text_values_take_the_spelling_in_the_data(schema: DatasetSchema) -> None:
    plan = p([m("count")], filters=[f("country", "in", ["germany", "FRANCE"])])
    assert only_filter(plan, schema) == ("country", "in", ["Germany", "France"])


def test_boolean_values(schema: DatasetSchema) -> None:
    plan = p([m("count")], filters=[f("is_cancellation", "eq", "yes")])
    assert only_filter(plan, schema) == ("is_cancellation", "eq", True)


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("eq", "2011", ("between", ["2011-01-01", "2011-12-31"])),
        ("eq", "2011-02", ("between", ["2011-02-01", "2011-02-28"])),
        ("eq", "2011-03-04", ("between", ["2011-03-04", "2011-03-04"])),
        ("lt", "2011", ("lt", "2011-01-01")),  # before 2011
        ("gte", "2011-03", ("gte", "2011-03-01")),  # from March 2011
        ("gt", "2010", ("gt", "2010-12-31")),  # after 2010
        ("lte", "2010-12", ("lte", "2010-12-31")),  # up to the end of December 2010
    ],
)
def test_date_periods(
    op: str, value: str, expected: tuple[str, object], schema: DatasetSchema
) -> None:
    plan = p([m("count")], filters=[f("invoiced_at", op, value)])
    _, got_op, got_value = only_filter(plan, schema)
    assert (got_op, got_value) == expected


def test_date_between_covers_whole_periods(schema: DatasetSchema) -> None:
    plan = p([m("count")], filters=[f("invoiced_at", "between", ["2010-12", "2011-01"])])
    assert only_filter(plan, schema)[2] == ["2010-12-01", "2011-01-31"]


@pytest.mark.parametrize("text", ["2011-13", "2011-02-30", "11/03/2011", "yesterday", ""])
def test_period_rejects_non_dates(text: str) -> None:
    assert period(text) is None
