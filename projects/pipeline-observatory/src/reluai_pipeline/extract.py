"""Extraction from the three sources, with retries for the network source."""

from __future__ import annotations

import csv
import gzip
import io
import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

RETRYABLE_STATUS = {429, 502, 503, 504}


class CrmUnavailableError(RuntimeError):
    """The CRM could not be reached after all retries."""

    def __init__(
        self, message: str, *, events: list[dict[str, object]] | None = None, retries: int = 0
    ) -> None:
        super().__init__(message)
        self.events = events or []
        self.retries = retries


class _RetryableResponseError(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


@dataclass(slots=True)
class CrmResult:
    customers: dict[int, tuple[str, date]]  # id -> (country, first_seen)
    pages: int
    attempts: int
    retries: int
    events: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CrmRequest:
    client: httpx.Client
    base_url: str
    as_of: date
    page_size: int
    simulated_fault: str | None


class _PageFetcher:
    """Fetches one page with retries; counts attempts and records each retry."""

    def __init__(self, req: CrmRequest, page: int, result: CrmResult) -> None:
        self.req = req
        self.page = page
        self.result = result
        self.attempt = 0

    def __call__(self) -> dict[str, object]:
        self.attempt += 1
        self.result.attempts += 1
        headers = {"X-Attempt": str(self.attempt)}
        if self.req.simulated_fault:
            headers["X-Simulated-Fault"] = self.req.simulated_fault
        resp = self.req.client.get(
            f"{self.req.base_url.rstrip('/')}/customers",
            params={
                "page": self.page,
                "page_size": self.req.page_size,
                "as_of": self.req.as_of.isoformat(),
            },
            headers=headers,
        )
        if resp.status_code in RETRYABLE_STATUS:
            raise _RetryableResponseError(resp.status_code)
        resp.raise_for_status()
        body: dict[str, object] = resp.json()
        return body

    def before_sleep(self, state: RetryCallState) -> None:
        self.result.retries += 1
        exc = state.outcome.exception() if state.outcome else None
        wait = state.next_action.sleep if state.next_action else 0.0
        self.result.events.append(
            {
                "event": "crm.retry",
                "page": self.page,
                "attempt": state.attempt_number,
                "error": str(exc),
                "wait_s": round(wait, 2),
            }
        )


def fetch_customers(
    client: httpx.Client,
    *,
    base_url: str,
    as_of: date,
    page_size: int,
    max_attempts: int,
    backoff_initial: float,
    backoff_max: float,
    simulated_fault: str | None = None,
) -> CrmResult:
    """Page through the CRM register, retrying transient failures with jittered backoff."""
    req = CrmRequest(
        client=client,
        base_url=base_url,
        as_of=as_of,
        page_size=page_size,
        simulated_fault=simulated_fault,
    )
    result = CrmResult(customers={}, pages=0, attempts=0, retries=0)
    page: int | None = 1
    while page is not None:
        fetcher = _PageFetcher(req, page, result)
        retrying = Retrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential_jitter(initial=backoff_initial, max=backoff_max),
            retry=retry_if_exception_type((_RetryableResponseError, httpx.TransportError)),
            before_sleep=fetcher.before_sleep,
            reraise=True,
        )
        try:
            body = retrying(fetcher)
        except (_RetryableResponseError, httpx.TransportError) as exc:
            raise CrmUnavailableError(
                f"CRM unavailable after {max_attempts} attempts on page {page}: {exc}",
                events=result.events,
                retries=result.retries,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise CrmUnavailableError(
                f"CRM returned {exc.response.status_code}",
                events=result.events,
                retries=result.retries,
            ) from exc

        items = body.get("items", [])
        if not isinstance(items, list):
            raise CrmUnavailableError(
                "CRM response has no item list", events=result.events, retries=result.retries
            )
        for item in items:
            result.customers[int(item["customer_id"])] = (
                str(item["country"]),
                date.fromisoformat(str(item["first_seen"])),
            )
        result.pages += 1
        nxt = body.get("next_page")
        page = int(nxt) if isinstance(nxt, int) else None
    return result


def read_catalogue(sources_dir: Path) -> list[dict[str, str]]:
    raw = json.loads((sources_dir / "catalogue" / "products.json").read_text(encoding="utf-8"))
    products: list[dict[str, str]] = raw["products"]
    return products


def read_drop_file(sources_dir: Path, file: str) -> bytes:
    return (sources_dir / file).read_bytes()


# ------------------------------------------------------------------- simulated faults
def corrupt_drop(data: bytes, *, seed: int) -> tuple[bytes, dict[str, int]]:
    """Return a damaged copy of a drop for the ``corrupt_drop`` scenario (≈7.5% of rows).

    The faults mimic real transfer problems: truncated lines, an export that wrote dates in
    the wrong format, a text field shifted into the quantity column, and invalid bytes.
    """
    rng = random.Random(seed)  # noqa: S311 - simulation, not security
    lines = gzip.decompress(data).split(b"\n")
    counts = {"truncated": 0, "bad_date": 0, "text_quantity": 0, "invalid_bytes": 0}
    faults: list[tuple[float, str, Callable[[bytes], bytes]]] = [
        (0.04, "truncated", lambda ln: ln[: max(1, len(ln) // 3)]),
        (0.02, "bad_date", lambda ln: _set_field(ln, 4, _us_style_date)),
        (0.01, "text_quantity", lambda ln: _set_field(ln, 3, lambda _v: "twelve")),
        (0.005, "invalid_bytes", lambda ln: ln + b"\xff\xfe"),
    ]
    out = [lines[0]]
    for original in lines[1:]:
        line = original
        if line:
            roll = rng.random()
            acc = 0.0
            for share, name, fn in faults:
                acc += share
                if roll < acc:
                    line = fn(original)
                    if line != original:
                        counts[name] += 1
                    break
        out.append(line)
    return gzip.compress(b"\n".join(out), mtime=0), counts


def _set_field(line: bytes, index: int, fn: Callable[[str], str]) -> bytes:
    """Rewrite one CSV field (descriptions may contain quoted commas, so parse properly)."""
    text = line.decode("utf-8", errors="replace")
    fields = next(csv.reader([text]))
    if len(fields) <= index:
        return line
    fields[index] = fn(fields[index])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(fields)
    return buf.getvalue().encode("utf-8")


def _us_style_date(value: str) -> str:
    """'2010-03-01 09:15:00' -> '03/01/2010 9:15 AM' (an export with the wrong locale)."""
    try:
        d, t = value.split(" ")
        y, m, dd = d.split("-")
        hh, mm, _ss = t.split(":")
    except ValueError:
        return value
    hour = int(hh)
    suffix = "AM" if hour < 12 else "PM"
    return f"{m}/{dd}/{y} {hour % 12 or 12}:{mm} {suffix}"
