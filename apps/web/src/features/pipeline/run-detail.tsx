"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { StepBar } from "@/components/step-bar";
import type { Check, RunDetail } from "@/lib/api/types";
import {
  formatDateTime,
  formatDropKey,
  formatDuration,
  formatInt,
  formatScore,
} from "@/lib/format";

import { isActive, useQuarantine, useRunDetail } from "./queries";

const checkLabel: Record<string, string> = {
  schema_conforms: "Header matches the data contract",
  reject_ratio: "Share of rows quarantined",
  duplicate_ratio: "Share of exact duplicate lines",
  customer_completeness: "Sales lines with a customer ID",
  period_consistency: "Rows dated inside the drop month",
  reference_integrity: "Rows referencing unknown products or customers",
  load_reconciliation: "Warehouse holds every published line",
  warehouse_orphans: "Orphaned lines or invoices in the warehouse",
  drop_sequence: "No gap since the previous drop",
};

const stepStopped: Record<string, string> = {
  resolve: "Stopped while choosing the drop.",
  extract: "Stopped while reading the sources.",
  validate: "Stopped during validation.",
  transform: "Stopped during transformation.",
  quality_gate: "Stopped at the quality gate.",
  load: "Stopped during the load; the transaction was rolled back.",
  queue: "Not started.",
};

const triggerText: Record<string, string> = {
  scheduled: "Started by the 6-hourly schedule",
  visitor: "Started by a visitor",
  cli: "Started from the command line",
  backfill: "Part of the initial backfill",
};

function observed(c: Check): string {
  if (c.observed === null || c.observed === undefined) return "–";
  if (c.threshold.includes("%")) return `${(c.observed * 100).toFixed(2)}%`;
  return formatInt(Math.round(c.observed));
}

function Checks({ checks }: { checks: Check[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm sm:min-w-[560px]">
        <caption className="sr-only">Data-quality checks</caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3 font-medium">Check</th>
            <th className="py-2 pr-3 font-medium">Result</th>
            <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Observed</th>
            <th className="hidden py-2 pr-3 font-medium sm:table-cell">Threshold</th>
            <th className="hidden py-2 text-right font-medium sm:table-cell">Weight</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.check_name} className="border-b border-line/60 align-top">
              <td className="py-2 pr-3">
                <span className="text-text">{checkLabel[c.check_name] ?? c.check_name}</span>
                <span className="block text-xs text-faint">
                  {c.dimension}, {c.severity === "gate" ? "gate (blocks publishing)" : c.severity}
                </span>
                <span className="block text-xs text-muted sm:hidden">
                  Observed {observed(c)}, threshold {c.threshold}, weight {c.weight}
                </span>
              </td>
              <td className="py-2 pr-3">
                <span
                  className={
                    c.passed ? "text-pass" : c.severity === "gate" ? "text-fail" : "text-warn"
                  }
                >
                  {c.passed ? "Passed" : "Failed"}
                </span>
              </td>
              <td className="num hidden py-2 pr-3 text-right sm:table-cell">{observed(c)}</td>
              <td className="hidden py-2 pr-3 text-muted sm:table-cell">{c.threshold}</td>
              <td className="num hidden py-2 text-right text-muted sm:table-cell">{c.weight}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QuarantineSample({ runId, reason }: { runId: string; reason: string }) {
  const q = useQuarantine(runId, reason);
  if (q.isPending) return <p className="text-xs text-muted">Loading rows…</p>;
  if (q.isError) return <p className="text-xs text-fail">Could not load rows: {q.error.message}</p>;
  return (
    <div className="mt-2 overflow-x-auto rounded-sm bg-ink p-3">
      <table className="font-mono text-xs">
        <caption className="sr-only">First rows quarantined for {reason}</caption>
        <tbody>
          {q.data.items.map((row) => (
            <tr key={row.line_number} className="align-top">
              <td className="pr-3 text-faint">line {row.line_number}</td>
              <td className="whitespace-pre text-muted">
                {Object.values(row.raw)
                  .map((v) => (v === null ? "∅" : String(v)))
                  .join(" | ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.data.total > q.data.items.length && (
        <p className="mt-2 text-xs text-faint">
          Showing the first {q.data.items.length} of {formatInt(q.data.total)} stored rows.
        </p>
      )}
    </div>
  );
}

function Reasons({ detail }: { detail: RunDetail }) {
  const [open, setOpen] = useState<string | null>(null);
  if (detail.reasons.length === 0 && detail.warnings.length === 0) {
    return <p className="text-sm text-muted">No rows were quarantined or flagged.</p>;
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <h4 className="text-sm font-semibold text-text">Quarantined or removed</h4>
        <ul className="mt-2 divide-y divide-line/60">
          {detail.reasons.map((r) => (
            <li key={r.code} className="py-2.5">
              <div className="flex items-baseline justify-between gap-3">
                <button
                  type="button"
                  className="text-left text-sm text-link hover:underline"
                  aria-expanded={open === r.code}
                  onClick={() => setOpen(open === r.code ? null : r.code)}
                >
                  {r.label}
                </button>
                <span className="num text-sm">{formatInt(r.count)}</span>
              </div>
              <p className="text-xs text-muted">{r.explanation}</p>
              {open === r.code && <QuarantineSample runId={detail.run.id} reason={r.code} />}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4 className="text-sm font-semibold text-text">Published with a warning</h4>
        {detail.warnings.length === 0 ? (
          <p className="mt-2 text-sm text-muted">None.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line/60">
            {detail.warnings.map((w) => (
              <li key={w.code} className="py-2.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-text">{w.label}</span>
                  <span className="num text-sm">{formatInt(w.count)}</span>
                </div>
                <p className="text-xs text-muted">{w.explanation}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Logs({ detail }: { detail: RunDetail }) {
  return (
    <ol className="max-h-80 space-y-0.5 overflow-auto rounded-sm bg-ink p-3 font-mono text-xs leading-relaxed">
      {detail.logs.map((l, i) => (
        <li
          key={i}
          className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 sm:grid-cols-[6.5rem_3.5rem_minmax(0,1fr)]"
        >
          <span className="text-faint">{l.ts.slice(11, 23)}</span>
          <span
            className={`hidden sm:block ${
              l.level === "error" ? "text-fail" : l.level === "warning" ? "text-warn" : "text-muted"
            }`}
          >
            {l.level}
          </span>
          <span className="[overflow-wrap:anywhere]">
            <span className={l.level === "error" ? "text-fail" : "text-text"}>{l.event}</span>{" "}
            <span className="text-muted">
              {Object.entries(l.fields)
                .filter(([, v]) => v !== null)
                .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                .join(" ")}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

export function RunDetailPanel({
  runId,
  scenarioTitle,
}: {
  runId: string;
  scenarioTitle: (id: string) => string;
}) {
  const q = useRunDetail(runId);
  if (q.isPending) return <p className="text-sm text-muted">Loading run…</p>;
  if (q.isError)
    return <p className="text-sm text-fail">Could not load this run: {q.error.message}</p>;
  const { run } = q.data;
  const active = isActive(run.status);

  return (
    <article aria-live="polite" className="space-y-7">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-text">
            {scenarioTitle(run.scenario)}
            {run.drop_key ? `, ${formatDropKey(run.drop_key)}` : ""}
          </h3>
          <p className="text-sm text-muted">
            {triggerText[run.trigger] ?? `Triggered by ${run.trigger}`}
            {run.started_at ? ` at ${formatDateTime(run.started_at)}` : ""}
            {run.simulated ? ". Simulated fault scenario." : "."}
          </p>
          {run.note && <p className="text-sm text-muted">Drop selected: {run.note}.</p>}
        </div>
        <StatusBadge status={run.status} />
      </header>

      {active && (
        <p className="rounded-sm bg-warn/10 px-3 py-2 text-sm text-warn">
          {run.status === "queued"
            ? "Queued. Runs execute one at a time on this server; this one starts when the worker is free."
            : "Running. This panel updates every couple of seconds."}
        </p>
      )}
      {run.status === "failed" && run.error_message && (
        <p className="rounded-sm bg-fail/10 px-3 py-2 text-sm text-fail">
          <span className="font-medium">
            {run.failure_step
              ? (stepStopped[run.failure_step] ?? `Stopped at ${run.failure_step}.`)
              : "Failed."}
          </span>{" "}
          {run.error_message}
        </p>
      )}

      {!active && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          {(
            [
              ["Rows read", formatInt(run.rows_read)],
              [
                run.status === "failed" ? "Passed validation" : "Published",
                formatInt(run.rows_accepted),
              ],
              ["New in warehouse", formatInt(run.rows_inserted)],
              ["Already present", formatInt(run.rows_unchanged)],
              ["Quarantined", formatInt(run.rows_rejected)],
              ["Duplicates removed", formatInt(run.rows_deduplicated)],
              ["Source retries", formatInt(run.source_retries)],
              ["Quality score", formatScore(run.dq_score)],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="flex flex-col-reverse">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="num text-lg font-semibold text-text">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {q.data.steps.length > 0 && (
        <section>
          <h4 className="mb-3 text-sm font-semibold text-text">
            Steps{" "}
            <span className="font-normal text-muted">
              ({formatDuration(run.duration_ms)} in total)
            </span>
          </h4>
          <StepBar steps={q.data.steps} />
        </section>
      )}

      {q.data.checks.length > 0 && (
        <section>
          <h4 className="mb-2 text-sm font-semibold text-text">Data-quality checks</h4>
          <Checks checks={q.data.checks} />
          <p className="mt-2 text-xs text-faint">Score = {q.data.dq_formula}.</p>
        </section>
      )}

      {!active && (
        <section>
          <Reasons detail={q.data} />
        </section>
      )}

      {q.data.logs.length > 0 && (
        <section>
          <h4 className="mb-2 text-sm font-semibold text-text">Log of this run</h4>
          <Logs detail={q.data} />
        </section>
      )}

      {q.data.environment && (
        <p className="text-xs text-faint">
          Ran on {String(q.data.environment.cpu)}, {String(q.data.environment.cpu_count)} vCPU,
          Python {String(q.data.environment.python)}, pandas {String(q.data.environment.pandas)}.
        </p>
      )}
    </article>
  );
}
