"""Run scenarios a visitor (or the scheduler) can trigger."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    title: str
    description: str
    simulated: bool
    expected: str


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in [
        Scenario(
            "standard",
            "Load next monthly drop",
            "Ingest the next unloaded month of real invoices. Once all 25 drops are loaded, "
            "the least recently processed drop is re-processed instead.",
            simulated=False,
            expected="Succeeds; real data issues are quarantined or flagged.",
        ),
        Scenario(
            "replay",
            "Replay last drop (idempotency)",
            "Re-process the most recently loaded drop. Loads are idempotent, so no new rows "
            "should be written.",
            simulated=False,
            expected="Succeeds with 0 new rows.",
        ),
        Scenario(
            "crm_flaky",
            "Flaky CRM API",
            "The CRM returns HTTP 503 twice for every page before recovering. The extractor "
            "retries with exponential backoff and jitter.",
            simulated=True,
            expected="Succeeds after retries; retry count is recorded.",
        ),
        Scenario(
            "crm_outage",
            "CRM outage",
            "The CRM is down for the whole run. Retries are exhausted and the run fails "
            "before anything is written.",
            simulated=True,
            expected="Fails at extract; warehouse unchanged.",
        ),
        Scenario(
            "corrupt_drop",
            "Corrupted file drop",
            "About 7.5% of the next drop's lines are damaged in transit (truncated lines, "
            "wrong date locale, text in numeric fields, invalid bytes).",
            simulated=True,
            expected="Bad rows are quarantined, the quality gate fails and nothing is published.",
        ),
    ]
}
