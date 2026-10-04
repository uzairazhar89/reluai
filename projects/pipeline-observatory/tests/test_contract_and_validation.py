from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

from reluai_pipeline.contract import SchemaMismatchError, parse_drop
from reluai_pipeline.extract import corrupt_drop, read_catalogue
from reluai_pipeline.rules import classify_line_type, normalise_stock_code
from reluai_pipeline.sources.builder import load_index
from reluai_pipeline.validate import ReferenceData, validate


def drop_bytes(sources_dir: Path, key: str) -> bytes:
    return (sources_dir / f"invoices/{key}.csv.gz").read_bytes()


def refs(sources_dir: Path) -> ReferenceData:
    catalogue = {p["stock_code"]: p["description"] for p in read_catalogue(sources_dir)}
    return ReferenceData(catalogue=catalogue, customers={17850, 12583})


def test_sources_index_lists_monthly_drops(sources_dir: Path) -> None:
    index = load_index(sources_dir)
    assert [d.key for d in index.drops] == ["2010-01", "2010-02"]
    assert index.drops[0].rows == 12
    catalogue = read_catalogue(sources_dir)
    codes = {p["stock_code"] for p in catalogue}
    assert "85123A" in codes and "85123a" not in codes  # lower-case variant normalised
    assert "TEST001" not in codes and "B" not in codes  # not real products


def test_header_must_match_contract() -> None:
    bad = gzip.compress(b"Invoice,Code,Desc\n1,2,3\n")
    with pytest.raises(SchemaMismatchError):
        parse_drop(bad)


def test_structural_problems_are_quarantined_with_line_numbers() -> None:
    header = b"Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country\n"
    good = b"536365,85123A,WHITE HEART,6,2010-01-04 08:26:00,2.55,17850,United Kingdom\n"
    data = header + good + b"536366,22633\n" + b"536367,22633,\xff\xfe,1,x,1,1,UK\n" + good
    parsed = parse_drop(data)
    assert len(parsed.records) == 2
    assert [(i.line_number, i.reason_code) for i in parsed.issues] == [
        (3, "malformed_row"),
        (4, "encoding_error"),
    ]
    assert parsed.rows_read == 4


def test_validation_applies_every_rule(sources_dir: Path) -> None:
    v = validate(
        parse_drop(drop_bytes(sources_dir, "2010-01")),
        period=pd.Period("2010-01", freq="M"),
        refs=refs(sources_dir),
    )
    assert dict(v.reject_counts) == {
        "stock_adjustment": 1,
        "accounting_adjustment": 1,
        "test_record": 1,
    }
    assert v.rows_deduplicated == 1
    assert len(v.accepted) == 12 - 3 - 1
    assert v.warning_counts["missing_customer_id"] == 1
    assert v.warning_counts["zero_price_line"] == 1
    assert v.warning_counts["stock_code_normalised"] == 1
    reasons = set(v.quarantine["reason_code"])
    assert reasons == {"stock_adjustment", "accounting_adjustment", "test_record", "duplicate_line"}
    by_code = v.accepted.set_index("invoice")
    assert by_code.loc["C536368", "kind"] == "cancellation"
    assert by_code.loc["536367", "line_type"] == "shipping"
    assert by_code.loc["536370", "stock_code"] == "85123A"
    assert by_code.loc["536374", "description"] == "HAND WARMER UNION JACK"  # spaces collapsed


def test_unknown_references_and_period_are_enforced(sources_dir: Path) -> None:
    parsed = parse_drop(drop_bytes(sources_dir, "2010-02"))
    v = validate(
        parsed,
        period=pd.Period("2010-03", freq="M"),
        refs=ReferenceData(catalogue={}, customers=set()),
    )
    assert v.reject_counts["outside_drop_period"] == 3
    v2 = validate(
        parsed,
        period=pd.Period("2010-02", freq="M"),
        refs=ReferenceData(catalogue={"85123A": "X"}, customers={17850}),
    )
    assert v2.reject_counts["unknown_product"] == 2
    assert v2.warning_counts.get("extreme_quantity") is None  # that row was rejected
    v3 = validate(parsed, period=pd.Period("2010-02", freq="M"), refs=refs(sources_dir))
    assert v3.warning_counts["extreme_quantity"] == 1


def test_corrupt_drop_is_deterministic_per_seed(sources_dir: Path) -> None:
    data = drop_bytes(sources_dir, "2010-01")
    a, counts_a = corrupt_drop(data, seed=7)
    b, counts_b = corrupt_drop(data, seed=7)
    assert a == b and counts_a == counts_b
    parse_drop(a)  # header survives corruption


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("85123a", "85123A"),
        ("m", "M"),
        ("gift_0001_20", "gift_0001_20"),
        ("POST", "POST"),
    ],
)
def test_normalise_stock_code(code: str, expected: str) -> None:
    assert normalise_stock_code(code) == expected


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("POST", "shipping"),
        ("DOT", "shipping"),
        ("D", "discount"),
        ("M", "manual"),
        ("AMAZONFEE", "fee"),
        ("gift_0001_20", "voucher"),
        ("DCGS0003", "product"),
        ("85123A", "product"),
        ("ADJUST2", "adjustment"),
    ],
)
def test_line_types(code: str, kind: str) -> None:
    assert classify_line_type(code) == kind
