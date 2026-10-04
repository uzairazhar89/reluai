"""Pytest plugin with pipeline fixtures (registered from the repository conftest).

``fixture_dataset`` is a small hand-written table in the dataset's canonical layout. Its rows
are modelled on real defects found in Online Retail II (each one is labelled below); it is a
unit-test fixture only and never shown on the website.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reluai_core.errors import install_error_handlers
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings
from reluai_pipeline.sources import crm
from reluai_pipeline.sources.builder import build_sources

ROWS = [
    # invoice, stock_code, description, qty, date, price, customer, country
    (
        "536365",
        "85123A",
        "WHITE HANGING HEART T-LIGHT HOLDER",
        6,
        "2010-01-04 08:26",
        2.55,
        17850,
        "United Kingdom",
    ),
    (
        "536365",
        "71053",
        "WHITE METAL LANTERN",
        6,
        "2010-01-04 08:26",
        3.39,
        17850,
        "United Kingdom",
    ),
    (
        "536365",
        "71053",
        "WHITE METAL LANTERN",
        6,
        "2010-01-04 08:26",
        3.39,
        17850,
        "United Kingdom",
    ),  # exact duplicate
    (
        "536366",
        "22633",
        "HAND WARMER UNION JACK",
        6,
        "2010-01-05 08:28",
        1.85,
        None,
        "United Kingdom",
    ),  # guest customer
    ("536367", "POST", "POSTAGE", 1, "2010-01-06 09:00", 18.00, 12583, "France"),  # shipping line
    (
        "C536368",
        "71053",
        "WHITE METAL LANTERN",
        -2,
        "2010-01-07 10:00",
        3.39,
        17850,
        "United Kingdom",
    ),  # cancellation
    (
        "536369",
        "21258",
        None,
        -36,
        "2010-01-08 11:00",
        0.0,
        None,
        "United Kingdom",
    ),  # stock write-off
    (
        "536370",
        "85123a",
        "WHITE HANGING HEART T-LIGHT HOLDER",
        2,
        "2010-01-09 12:00",
        2.55,
        12583,
        "France",
    ),  # lower-case code
    (
        "A536371",
        "B",
        "Adjust bad debt",
        1,
        "2010-01-10 13:00",
        -5000.0,
        None,
        "United Kingdom",
    ),  # accounting adjustment
    (
        "536372",
        "TEST001",
        "This is a test product.",
        5,
        "2010-01-11 14:00",
        4.5,
        12583,
        "France",
    ),  # test record
    (
        "536373",
        "22633",
        "HAND WARMER UNION JACK",
        12,
        "2010-01-12 15:00",
        0.0,
        17850,
        "United Kingdom",
    ),  # free item
    (
        "536374",
        "22633",
        "HAND WARMER  UNION JACK",
        24,
        "2010-01-13 16:00",
        1.65,
        12583,
        "France",
    ),  # double space
    (
        "536380",
        "85123A",
        "WHITE HANGING HEART T-LIGHT HOLDER",
        12,
        "2010-02-01 09:00",
        2.55,
        17850,
        "United Kingdom",
    ),
    ("536381", "71053", "WHITE METAL LANTERN", 3, "2010-02-02 10:00", 3.39, 12583, "France"),
    (
        "536382",
        "22633",
        "HAND WARMER UNION JACK",
        10000,
        "2010-02-03 11:00",
        1.65,
        12583,
        "France",
    ),  # extreme quantity
]


@pytest.fixture(scope="session")
def fixture_dataset() -> pd.DataFrame:
    df = pd.DataFrame(
        ROWS,
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
    return df


@pytest.fixture(scope="session")
def sources_dir(fixture_dataset: pd.DataFrame, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("sources")
    build_sources(fixture_dataset, out, content_sha256="f" * 64)
    return out


@pytest.fixture(scope="session")
def pipeline_settings(sources_dir: Path) -> PipelineSettings:
    return PipelineSettings(
        sources_dir=sources_dir,
        canonical_dir=sources_dir,
        crm_base_url="http://crm.test/internal/crm",
        crm_backoff_initial_seconds=0,
        crm_backoff_max_seconds=0,
        crm_page_size=1,  # exercises pagination
        # The fixture is deliberately defect-dense (3 of 12 rows rejected),
        # so its gates are looser than production's.
        reject_ratio_gate=0.5,
        duplicate_ratio_warn=0.2,
    )


@pytest.fixture
def crm_client_factory(pipeline_settings: PipelineSettings) -> Callable[[], httpx.Client]:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(crm.router, prefix="/internal/crm")
    app.dependency_overrides[get_pipeline_settings] = lambda: pipeline_settings

    def factory() -> httpx.Client:
        return TestClient(app, base_url="http://crm.test")

    return factory
