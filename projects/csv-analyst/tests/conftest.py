"""Fixtures for the CSV analyst tests.

``canonical_dir`` holds a small generated table in the bundled dataset's canonical layout
(the same columns and types as the verified Online Retail II Parquet). Its rows are random
but seeded, so every run sees the same table. It exists only for unit tests and is never
shown on the website; the real dataset is used by ``test_real_dataset.py`` when present.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from reluai_csv import sandbox
from reluai_csv.datasets import build_bundled, bundled_schema
from reluai_csv.schema import DatasetSchema
from reluai_csv.settings import CsvSettings

# Every country in the real table, so the parser sees the same known values.
COUNTRIES = [
    "United Kingdom", "EIRE", "Germany", "France", "Netherlands", "Spain", "Switzerland",
    "Belgium", "Portugal", "Australia", "Channel Islands", "Italy", "Norway", "Sweden",
    "Cyprus", "Finland", "Austria", "Denmark", "Unspecified", "Greece", "Japan", "Poland",
    "USA", "United Arab Emirates", "Israel", "Hong Kong", "Singapore", "Malta", "Iceland",
    "Canada", "Lithuania", "RSA", "Bahrain", "Brazil", "Thailand", "Korea",
    "European Community", "Lebanon", "West Indies", "Bermuda", "Nigeria", "Czech Republic",
    "Saudi Arabia",
]  # fmt: skip
PRODUCTS = [
    ("85123A", "WHITE HANGING HEART T-LIGHT HOLDER", 2.55),
    ("71053", "WHITE METAL LANTERN", 3.39),
    ("22633", "HAND WARMER UNION JACK", 1.85),
    ("84879", "ASSORTED COLOUR BIRD ORNAMENT", 1.69),
    ("22423", "REGENCY CAKESTAND 3 TIER", 12.75),
    ("47566", "PARTY BUNTING", 4.95),
    ("20725", "LUNCH BAG RED RETROSPOT", 1.65),
    ("21212", "PACK OF 72 RETROSPOT CAKE CASES", 0.55),
    ("22720", "SET OF 3 CAKE TINS PANTRY DESIGN", 4.95),
    ("POST", "POSTAGE", 18.0),
    ("23166", "MEDIUM CERAMIC TOP STORAGE JAR", 1.25),
    ("22197", "SMALL POPCORN HOLDER", 0.85),
]
ROWS = 900


def _rows() -> list[tuple[object, ...]]:
    rng = random.Random(20111209)
    start = datetime(2009, 12, 1, 8)
    span = (datetime(2011, 12, 9, 18) - start).total_seconds()
    out: list[tuple[object, ...]] = []
    invoice = 489000
    while len(out) < ROWS:
        invoice += 1
        cancelled = rng.random() < 0.05
        when = start + timedelta(seconds=int(rng.random() * span) // 60 * 60)
        country = "United Kingdom" if rng.random() < 0.6 else rng.choice(COUNTRIES)
        customer = None if rng.random() < 0.2 else 12346 + rng.randrange(120)
        for _ in range(rng.randint(1, 4)):
            code, description, price = rng.choice(PRODUCTS)
            quantity = rng.choice([1, 2, 3, 4, 6, 12, 24, 48])
            out.append(
                (
                    f"C{invoice}" if cancelled else str(invoice),
                    code,
                    None if rng.random() < 0.01 else description,
                    -quantity if cancelled else quantity,
                    when,
                    price,
                    customer,
                    country,
                )
            )
    out.append(out[3])  # one exact duplicate, as in the real data
    return out


@pytest.fixture(scope="session")
def canonical_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    df = pd.DataFrame(
        _rows(),
        columns=[
            "invoice",
            "stock_code",
            "description",
            "quantity",
            "invoice_date",
            "price",
            "customer_id",
            "country",
        ],
    )
    df["invoice_date"] = pd.to_datetime(df["invoice_date"]).astype("datetime64[s]")
    df["customer_id"] = df["customer_id"].astype("Int64")
    for col in ("invoice", "stock_code", "description", "country"):
        df[col] = df[col].astype("string")
    out = tmp_path_factory.mktemp("canonical")
    df.to_parquet(out / "online-retail-ii.parquet", index=False)
    return out


@pytest.fixture(scope="session")
def csv_settings(canonical_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> CsvSettings:
    data_dir = tmp_path_factory.mktemp("csv")
    build_bundled(canonical_dir, data_dir)
    return CsvSettings(
        data_dir=data_dir,
        canonical_dir=canonical_dir,
        upload_dir=tmp_path_factory.mktemp("uploads"),
    )


@pytest.fixture(scope="session")
def schema(csv_settings: CsvSettings) -> DatasetSchema:
    return bundled_schema(csv_settings)


@pytest.fixture(scope="session")
def frame(csv_settings: CsvSettings) -> pd.DataFrame:
    """The bundled test table as pandas, read with plain DuckDB rather than the sandbox.

    DuckDB shares one database instance per file and process, so this connection uses the
    sandbox's configuration.
    """
    con = duckdb.connect(
        str(csv_settings.bundled_db), read_only=True, config=sandbox.locked_config(csv_settings)
    )
    try:
        return con.execute("SELECT * FROM sales").df()
    finally:
        con.close()


@pytest.fixture
def upload_settings(csv_settings: CsvSettings, tmp_path: Path) -> Iterator[CsvSettings]:
    """Settings with a private, empty upload folder for one test."""
    settings = csv_settings.model_copy(update={"upload_dir": tmp_path / "uploads"})
    yield settings
    for db_file in (tmp_path / "uploads").glob("*.duckdb"):
        sandbox.forget(db_file)
