import Link from "next/link";

import type { RunDetail, Summary } from "@/lib/api/types";
import {
  formatDropKey,
  formatDuration,
  formatInt,
  formatRelative,
  formatScore,
} from "@/lib/format";

import { StatusBadge } from "./status-badge";
import { StepBar } from "./step-bar";

interface Props {
  summary: Summary | null;
  detail: RunDetail | null;
  /** Render time, so relative times are consistent with the cached page. */
  renderedAt: string;
}

function Figure({ value, label, tone }: { value: string; label: string; tone?: "warn" | "fail" }) {
  const color = tone === "warn" ? "text-warn" : tone === "fail" ? "text-fail" : "text-text";
  return (
    <div className="flex flex-col-reverse">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`num text-xl font-semibold ${color}`}>{value}</dd>
    </div>
  );
}

/** The hero's live readout of the most recent pipeline run (server-rendered, refreshed by ISR). */
export function LiveRunPanel({ summary, detail, renderedAt }: Props) {
  const run = summary?.last_run;
  if (!summary || !run) {
    return (
      <section aria-labelledby="live-run" className="rounded-md border border-line bg-surface p-6">
        <h2 id="live-run" className="text-sm font-semibold">
          Latest pipeline run
        </h2>
        <p className="mt-3 text-sm text-muted">
          {summary
            ? "No runs recorded yet. The first scheduled run will appear here."
            : "The pipeline service is not reachable right now, so live figures are hidden rather than guessed."}{" "}
          <Link href="/status" className="prose-link">
            Check service status
          </Link>
        </p>
      </section>
    );
  }

  const steps = (detail?.steps ?? []).map((s) => ({
    name: s.name,
    status: s.status,
    duration_ms: s.duration_ms,
  }));
  const finished = run.finished_at ?? run.started_at;
  const failed = run.status === "failed";

  return (
    <section aria-labelledby="live-run" className="rounded-md border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="live-run" className="text-sm font-semibold">
            Latest pipeline run
          </h2>
          <p className="mt-1 text-sm text-muted">
            {formatDropKey(run.drop_key)} drop, finished{" "}
            {formatRelative(finished, new Date(renderedAt))}
            {run.simulated ? " (simulated fault scenario)" : ""}
          </p>
        </div>
        <StatusBadge status={run.status} />
      </div>

      {steps.length > 0 && (
        <div className="mt-6">
          <StepBar steps={steps} animate />
        </div>
      )}

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5">
        <Figure value={formatInt(run.rows_read)} label="rows read" />
        <Figure value={formatInt(failed ? 0 : run.rows_accepted)} label="rows published" />
        <Figure value={formatInt(run.rows_rejected)} label="rows quarantined" tone="warn" />
        <Figure value={formatInt(run.rows_deduplicated)} label="duplicates removed" />
        <Figure value={formatScore(run.dq_score)} label="quality score / 100" />
        <Figure value={formatDuration(run.duration_ms)} label="run time" />
      </dl>

      {failed && run.error_message && (
        <p className="mt-5 rounded-sm bg-fail/10 px-3 py-2 text-sm text-fail">
          Stopped at {run.failure_step?.replace("_", " ")}: {run.error_message}
        </p>
      )}

      <p className="mt-6 border-t border-line pt-4 text-xs text-muted">
        Real invoices from a UK online retailer (UCI Online Retail II), processed on this server.{" "}
        {formatInt(summary.drops_loaded)} of {formatInt(summary.drops_total)} monthly drops loaded.
      </p>
      <Link
        href="/projects/data-pipeline-observatory#demo"
        className="prose-link mt-3 inline-block text-sm"
      >
        Open the live dashboard
      </Link>
    </section>
  );
}
