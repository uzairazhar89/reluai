"use client";

import { StatusBadge } from "@/components/status-badge";
import type { Run } from "@/lib/api/types";
import {
  formatDropKey,
  formatDuration,
  formatInt,
  formatRelative,
  formatScore,
} from "@/lib/format";
import { useNow } from "@/lib/now";

import { isActive } from "./queries";

const triggerSuffix: Record<string, string> = {
  scheduled: ", scheduled",
  visitor: ", by a visitor",
  cli: ", from the CLI",
  backfill: ", backfill",
};

interface Props {
  runs: Run[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  scenarioTitle: (id: string) => string;
}

export function RunsTable({ runs, selectedId, onSelect, scenarioTitle }: Props) {
  const now = useNow();
  if (runs.length === 0) {
    return (
      <p className="text-sm text-muted">
        No runs yet. Start one above, or wait for the next scheduled run.
      </p>
    );
  }
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full text-left text-sm sm:min-w-[620px]">
        <caption className="sr-only">
          Recent pipeline runs. Select a run to see its details.
        </caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3 font-medium">Run</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Rows read</th>
            <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Quarantined</th>
            <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Quality</th>
            <th className="hidden py-2 text-right font-medium sm:table-cell">Duration</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const selected = r.id === selectedId;
            return (
              <tr
                key={r.id}
                className={`border-b border-line/60 ${selected ? "bg-surface-2" : "hover:bg-surface-2/50"}`}
              >
                <td className="py-2 pl-2 pr-3">
                  <button
                    type="button"
                    onClick={() => onSelect(r.id)}
                    aria-current={selected ? "true" : undefined}
                    className="text-left"
                  >
                    <span
                      className={`block ${selected ? "text-text" : "text-link hover:underline"}`}
                    >
                      {scenarioTitle(r.scenario)}
                    </span>
                    <span className="block text-xs text-faint">
                      {r.drop_key ? `${formatDropKey(r.drop_key)}, ` : ""}
                      {formatRelative(r.started_at ?? r.queued_at, now)}
                      {triggerSuffix[r.trigger] ?? ""}
                    </span>
                    {!isActive(r.status) && r.rows_read > 0 && (
                      <span className="block text-xs text-muted sm:hidden">
                        {formatInt(r.rows_read)} rows, quality {formatScore(r.dq_score)}
                      </span>
                    )}
                  </button>
                </td>
                <td className="py-2 pr-3">
                  <StatusBadge status={r.status} />
                </td>
                <td className="num hidden py-2 pr-3 text-right sm:table-cell">
                  {isActive(r.status) ? "–" : formatInt(r.rows_read)}
                </td>
                <td className="num hidden py-2 pr-3 text-right text-muted sm:table-cell">
                  {isActive(r.status) ? "–" : formatInt(r.rows_rejected)}
                </td>
                <td className="num hidden py-2 pr-3 text-right sm:table-cell">
                  {formatScore(r.dq_score)}
                </td>
                <td className="num hidden py-2 pr-2 text-right text-muted sm:table-cell">
                  {formatDuration(r.duration_ms)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
