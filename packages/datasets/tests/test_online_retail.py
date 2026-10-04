from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from reluai_datasets.manifest import ContentChecks, load_manifest
from reluai_datasets.online_retail import (
    CANONICAL_COLUMNS,
    ContentMismatchError,
    fingerprint,
    normalise,
    verify,
)


def rda_style() -> pd.DataFrame:
    """Column layout of the R mirror (text codes, float quantity/customer)."""
    return pd.DataFrame(
        {
            "Invoice": ["489434", "C489449"],
            "StockCode": ["85048", "22087"],
            "Description": ["15CM CHRISTMAS GLASS BALL 20 LIGHTS", None],
            "Quantity": [12.0, -12.0],
            "InvoiceDate": pd.to_datetime(["2009-12-01 07:45:00", "2009-12-01 10:33:00"]),
            "Price": [6.95, 0.85],
            "CustomerID": [13085.0, float("nan")],
            "Country": ["United Kingdom", "Australia"],
        }
    )


def xlsx_style() -> pd.DataFrame:
    """Column layout of the UCI workbook (numeric codes, 'Customer ID', stray spaces)."""
    return pd.DataFrame(
        {
            "Invoice": [489434, "C489449"],
            "StockCode": [85048, "22087"],
            "Description": ["15CM CHRISTMAS GLASS BALL 20 LIGHTS ", ""],
            "Quantity": [12, -12],
            "InvoiceDate": ["2009-12-01 07:45:00", "2009-12-01 10:33:00"],
            "Price": [6.95, 0.85],
            "Customer ID": [13085, None],
            "Country": ["United Kingdom", "Australia"],
        }
    )


def test_both_source_layouts_normalise_to_identical_content() -> None:
    a, b = normalise(rda_style()), normalise(xlsx_style())
    assert list(a.columns) == CANONICAL_COLUMNS
    assert fingerprint(a) == fingerprint(b)
    assert a["customer_id"].isna().tolist() == [False, True]
    assert a["description"].isna().tolist() == [False, True]


def test_fingerprint_is_order_independent_but_content_sensitive() -> None:
    df = normalise(rda_style())
    assert fingerprint(df) == fingerprint(df.iloc[::-1].reset_index(drop=True))
    changed = df.copy()
    changed.loc[0, "price"] = 6.96
    assert fingerprint(changed) != fingerprint(df)


def test_verify_reports_every_mismatch() -> None:
    df = normalise(rda_style())
    checks = ContentChecks(
        rows=3,
        columns=CANONICAL_COLUMNS,
        min_timestamp=datetime(2009, 12, 1, 7, 45),
        max_timestamp=datetime(2009, 12, 1, 10, 33),
        content_sha256="0" * 64,
    )
    with pytest.raises(ContentMismatchError) as err:
        verify(df, checks)
    assert "rows 2 != 3" in str(err.value)
    assert "content fingerprint" in str(err.value)
    good = checks.model_copy(update={"rows": 2, "content_sha256": fingerprint(df)})
    assert verify(df, good) == fingerprint(df)


def test_missing_columns_rejected() -> None:
    with pytest.raises(ContentMismatchError, match="missing columns"):
        normalise(rda_style().drop(columns=["Country"]))


def test_repository_manifest_is_valid() -> None:
    manifest = load_manifest()
    ds = manifest.get("online-retail-ii")
    assert ds.real_data is True
    assert ds.checks.rows == 1_067_371
    assert ds.licence.name == "CC BY 4.0"
    assert {s.role for s in ds.sources} == {"canonical", "mirror"}
    mirror = next(s for s in ds.sources if s.role == "mirror")
    assert mirror.sha256 is not None, "mirrors must be pinned by checksum"
