"""Data-quality checks and the DQ score.

DQ score = 100 × Σ(weight × passed) / Σ(weight) over the checks evaluated in a run.
Gate checks stop the load when they fail ("quality gate"); warn checks lower the score
but publish the data; info checks are reported only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from reluai_pipeline.settings import PipelineSettings
from reluai_pipeline.validate import ValidationResult

WEIGHTS = {"gate": 3.0, "warn": 2.0, "info": 1.0}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    dimension: str  # validity | completeness | uniqueness | integrity | timeliness | accuracy
    stage: str  # batch | warehouse
    severity: str  # gate | warn | info
    passed: bool
    observed: float | None
    threshold: str
    detail: str

    @property
    def weight(self) -> float:
        return WEIGHTS[self.severity]


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def batch_checks(v: ValidationResult, settings: PipelineSettings) -> list[CheckResult]:
    read = max(v.rows_read, 1)
    reject_ratio = v.rows_rejected / read
    dup_ratio = v.rows_deduplicated / read
    sales = v.accepted[(v.accepted["line_type"] == "product") & (v.accepted["kind"] == "sale")]
    completeness = float(sales["customer_id"].notna().mean()) if len(sales) else 1.0
    orphans = v.reject_counts.get("unknown_product", 0) + v.reject_counts.get("unknown_customer", 0)
    dated = max(
        read
        - v.reject_counts.get("bad_date", 0)
        - v.reject_counts.get("malformed_row", 0)
        - v.reject_counts.get("encoding_error", 0),
        1,
    )
    in_period = 1 - v.rows_outside_period / dated

    return [
        CheckResult(
            "reject_ratio",
            "validity",
            "batch",
            "gate",
            reject_ratio <= settings.reject_ratio_gate,
            reject_ratio,
            f"≤ {_pct(settings.reject_ratio_gate)}",
            f"{v.rows_rejected:,} of {v.rows_read:,} rows quarantined",
        ),
        CheckResult(
            "duplicate_ratio",
            "uniqueness",
            "batch",
            "warn",
            dup_ratio <= settings.duplicate_ratio_warn,
            dup_ratio,
            f"≤ {_pct(settings.duplicate_ratio_warn)}",
            f"{v.rows_deduplicated:,} exact duplicate lines removed",
        ),
        CheckResult(
            "customer_completeness",
            "completeness",
            "batch",
            "warn",
            completeness >= settings.customer_completeness_min,
            completeness,
            f"≥ {_pct(settings.customer_completeness_min)}",
            "share of product sale lines with a customer ID",
        ),
        CheckResult(
            "period_consistency",
            "timeliness",
            "batch",
            "warn",
            in_period >= 0.99,
            in_period,
            "≥ 99.00%",
            f"{v.rows_outside_period:,} rows dated outside the drop month",
        ),
        CheckResult(
            "reference_integrity",
            "integrity",
            "batch",
            "warn",
            orphans / read <= 0.001,
            orphans / read,
            "≤ 0.10%",
            f"{orphans:,} rows reference an unknown product or customer",
        ),
    ]


def schema_check(passed: bool, detail: str) -> CheckResult:
    return CheckResult(
        "schema_conforms",
        "validity",
        "batch",
        "gate",
        passed,
        1.0 if passed else 0.0,
        "header = contract",
        detail,
    )


def warehouse_checks(
    session: Session, *, drop_key: str, expected_lines: int, previous_drop: str | None
) -> list[CheckResult]:
    loaded, orphan_lines, orphan_invoices = session.execute(
        text("""
        SELECT
          (SELECT count(*) FROM retail.invoice_line WHERE drop_key = :d),
          (SELECT count(*) FROM retail.invoice_line l
             LEFT JOIN retail.invoice i USING (invoice_no)
             WHERE l.drop_key = :d AND i.invoice_no IS NULL),
          (SELECT count(*) FROM retail.invoice i
             LEFT JOIN retail.customer c USING (customer_id)
             WHERE i.drop_key = :d AND i.customer_id IS NOT NULL AND c.customer_id IS NULL)
    """),
        {"d": drop_key},
    ).one()
    results = [
        CheckResult(
            "load_reconciliation",
            "accuracy",
            "warehouse",
            "gate",
            loaded >= expected_lines,
            float(loaded),
            f"≥ {expected_lines:,} lines",
            f"warehouse holds {loaded:,} lines for drop {drop_key}",
        ),
        CheckResult(
            "warehouse_orphans",
            "integrity",
            "warehouse",
            "warn",
            orphan_lines == 0 and orphan_invoices == 0,
            float(orphan_lines + orphan_invoices),
            "= 0",
            f"{orphan_lines} lines without invoice, {orphan_invoices} invoices without customer",
        ),
    ]
    if previous_drop is not None:
        y, m = (int(x) for x in previous_drop.split("-"))
        expected_next = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
        in_sequence = drop_key <= expected_next
        results.append(
            CheckResult(
                "drop_sequence",
                "timeliness",
                "warehouse",
                "info",
                in_sequence,
                None,
                "no gap after previous drop",
                f"previous drop {previous_drop}, this drop {drop_key}",
            )
        )
    return results


def dq_score(results: list[CheckResult]) -> float:
    total = sum(r.weight for r in results)
    if total == 0:
        return 0.0
    return round(100 * sum(r.weight for r in results if r.passed) / total, 1)
