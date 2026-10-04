"""Mock CRM: a paginated REST API serving the real customer register.

Mounted under ``/internal/crm`` (blocked at the edge; only the worker calls it). Failure
scenarios are injected by the *caller* through ``X-Simulated-Fault`` so the behaviour is
deterministic and clearly labelled as simulated:

* ``flaky``  — the first two attempts of every page return 503;
* ``outage`` — every request returns 503.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel

from reluai_core.errors import ProblemError
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings

router = APIRouter(include_in_schema=False)


class CustomerRecord(BaseModel):
    customer_id: int
    country: str
    first_seen: date


class CustomerPage(BaseModel):
    page: int
    page_size: int
    total: int
    next_page: int | None
    items: list[CustomerRecord]


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache on rebuild
    return pd.read_parquet(path).sort_values("customer_id", ignore_index=True)


def customer_register(sources_dir: Path) -> pd.DataFrame:
    path = sources_dir / "crm" / "customers.parquet"
    return _load(str(path), path.stat().st_mtime)


@router.get("/customers", response_model=CustomerPage)
def list_customers(
    *,
    settings: Annotated[PipelineSettings, Depends(get_pipeline_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=2000)] = 500,
    as_of: date | None = None,
    x_simulated_fault: Annotated[str | None, Header()] = None,
    x_attempt: Annotated[int, Header(ge=1)] = 1,
) -> CustomerPage:
    if x_simulated_fault == "outage" or (x_simulated_fault == "flaky" and x_attempt <= 2):
        raise ProblemError(
            503,
            "CRM temporarily unavailable (simulated fault)",
            code="simulated_outage",
            headers={"Retry-After": "1"},
        )
    df = customer_register(settings.sources_dir)
    if as_of is not None:
        df = df[pd.to_datetime(df["first_seen"]).dt.date <= as_of]
    total = len(df)
    start = (page - 1) * page_size
    chunk = df.iloc[start : start + page_size]
    items = [
        CustomerRecord(
            customer_id=int(r["customer_id"]),
            country=str(r["country"]),
            first_seen=pd.Timestamp(r["first_seen"]).date(),
        )
        for r in chunk.to_dict(orient="records")
    ]
    has_next = start + page_size < total
    return CustomerPage(
        page=page,
        page_size=page_size,
        total=total,
        next_page=page + 1 if has_next else None,
        items=items,
    )
