"use client";

import { useCallback, useRef, useState } from "react";

import { QueryProvider } from "@/components/query-provider";
import { NowProvider, useNow } from "@/lib/now";
import { StatusBadge } from "@/components/status-badge";
import type { Run, Summary } from "@/lib/api/types";
import {
  formatDropKey,
  formatDuration,
  formatInt,
  formatRelative,
  formatScore,
} from "@/lib/format";

import { useRuns, useScenarios, useSummary } from "./queries";
import { RunDetailPanel } from "./run-detail";
import { RunTrigger } from "./run-trigger";
import { RunsTable } from "./runs-table";
import { TrendChart } from "./trend-chart";

interface Props {
  initialSummary?: Summary;
  initialRuns?: Run[];
}

/** `renderedAt` is the server render time, so relative times hydrate without a mismatch. */
export function PipelineDashboard({ renderedAt, ...props }: Props & { renderedAt: string }) {
  return (
    <QueryProvider>
      <NowProvider serverNow={renderedAt}>
        <Dashboard {...props} />
      </NowProvider>
    </QueryProvider>
  );
}

function Figure({
  label,
  children,
  note,
}: {
  label: string;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <div className="flex flex-col border-t border-line pt-3">
      <dt className="order-2 text-xs text-muted">{label}</dt>
      <dd className="num order-1 text-xl font-semibold text-text">{children}</dd>
      {note && <dd className="order-3 mt-0.5 text-xs text-faint">{note}</dd>}
    </div>
  );
}

function SummaryFigures({
  s,
  scenarioTitle,
}: {
  s: Summary;
  scenarioTitle: (id: string) => string;
}) {
  const now = useNow();
  const last = s.last_run;
  return (
    <div className="space-y-9">
      <section aria-labelledby="last-run-h">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h4 id="last-run-h" className="text-sm font-semibold text-text">
            Last run
          </h4>
          {last && <StatusBadge status={last.status} />}
          <p className="text-sm text-muted">
            {last
              ? `${scenarioTitle(last.scenario)}${last.drop_key ? `, ${formatDropKey(last.drop_key)}` : ""}, ${formatRelative(last.finished_at ?? last.started_at ?? last.queued_at, now)}`
              : "No runs yet"}
          </p>
        </div>
        {last && (
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-5">
            <Figure label="Records read">{formatInt(last.rows_read)}</Figure>
            <Figure label="Quarantined">{formatInt(last.rows_rejected)}</Figure>
            <Figure label="Duplicates removed">{formatInt(last.rows_deduplicated)}</Figure>
            <Figure label="Quality score">{formatScore(last.dq_score)}</Figure>
            <Figure label="Runtime">{formatDuration(last.duration_ms)}</Figure>
          </dl>
        )}
      </section>

      <section aria-labelledby="all-runs-h">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h4 id="all-runs-h" className="text-sm font-semibold text-text">
            All runs
          </h4>
          <p className="text-sm text-muted">
            {s.last_success
              ? `Last successful run ${formatRelative(s.last_success.finished_at, now)}${s.last_success.drop_key ? `, ${formatDropKey(s.last_success.drop_key)}` : ""}`
              : "No successful run yet"}
          </p>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
          <Figure
            label={`Failed, of the last ${s.recent_window} runs`}
            note="Includes simulated faults"
          >
            {formatInt(s.failures_recent)}
          </Figure>
          <Figure label={`Monthly drops loaded, of ${formatInt(s.drops_total)}`}>
            {formatInt(s.drops_loaded)}
          </Figure>
          <Figure label="Invoice lines in warehouse">{formatInt(s.warehouse.invoice_lines)}</Figure>
          <Figure
            label="Customers in warehouse"
            note={`${formatInt(s.warehouse.invoices)} invoices`}
          >
            {formatInt(s.warehouse.customers)}
          </Figure>
        </dl>
      </section>
    </div>
  );
}

function Dashboard({ initialSummary, initialRuns }: Props) {
  const summary = useSummary(initialSummary);
  const runs = useRuns(initialRuns);
  const scenarios = useScenarios();
  const [picked, setPicked] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const scenarioTitle = useCallback(
    (id: string) => scenarios.data?.find((s) => s.id === id)?.title ?? id.replaceAll("_", " "),
    [scenarios.data],
  );

  const selectedId = picked ?? runs.data?.[0]?.id ?? summary.data?.last_run?.id ?? null;

  const select = (id: string, scroll: boolean) => {
    setPicked(id);
    if (scroll) {
      requestAnimationFrame(() =>
        detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    }
  };

  if (summary.isError && !summary.data) {
    return (
      <div className="rounded-md border border-line bg-surface p-6">
        <p className="font-medium text-text">The pipeline service is not reachable right now.</p>
        <p className="mt-1 text-sm text-muted">
          The rest of this page describes the system; the live figures return when the service is
          back. Current state of every component is on the status page.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-10 rounded-md border border-line bg-surface p-5 sm:p-7">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="heading text-lg">Pipeline dashboard</h3>
        <p className="text-xs text-faint">
          Portfolio demonstration on public data. Figures are read live from the running system.
        </p>
      </div>

      {summary.data ? (
        <SummaryFigures s={summary.data} scenarioTitle={scenarioTitle} />
      ) : (
        <p className="text-sm text-muted">Loading figures…</p>
      )}

      {summary.data && summary.data.trend.length > 0 && (
        <section aria-labelledby="trend-h">
          <h4 id="trend-h" className="mb-3 text-sm font-semibold text-text">
            Last {summary.data.trend.length} runs
          </h4>
          <TrendChart points={summary.data.trend} />
        </section>
      )}

      <div className="border-t border-line pt-8">
        <RunTrigger onQueued={(id) => select(id, false)} />
      </div>

      <section aria-labelledby="history-h" className="min-w-0 border-t border-line pt-8">
        <h4 id="history-h" className="mb-2 text-sm font-semibold text-text">
          Recent runs
        </h4>
        {runs.isError && !runs.data ? (
          <p className="text-sm text-fail">The run history could not be loaded.</p>
        ) : runs.data ? (
          <RunsTable
            runs={runs.data.slice(0, 8)}
            selectedId={selectedId}
            onSelect={(id) => select(id, true)}
            scenarioTitle={scenarioTitle}
          />
        ) : (
          <p className="text-sm text-muted">Loading runs…</p>
        )}
      </section>

      <div ref={detailRef} className="scroll-mt-24 border-t border-line pt-8">
        {selectedId ? (
          <RunDetailPanel runId={selectedId} scenarioTitle={scenarioTitle} />
        ) : (
          <p className="text-sm text-muted">
            Start a run to see each step, check and quarantined row here.
          </p>
        )}
      </div>
    </div>
  );
}
