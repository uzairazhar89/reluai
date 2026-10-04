"use client";

import { useState } from "react";

import { buttonClasses } from "@/components/button-link";
import { Pill } from "@/components/status-badge";
import { ApiError } from "@/lib/api/client";
import { useHydrated } from "@/lib/now";

import { useScenarios, useTriggerRun } from "./queries";

function minutes(seconds: number | undefined): string {
  if (!seconds) return "a few minutes";
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 minute" : `${m} minutes`;
}

/** Turn an API problem into a sentence that says what happened and what to do next. */
export function triggerErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "quota_exceeded") {
      return `Each visitor can start 3 runs per hour, and you have used them. You can start another in ${minutes(error.retryAfter)}.`;
    }
    if (error.code === "queue_full") {
      return "Several runs are already waiting for the worker. Try again in a minute.";
    }
    if (error.code === "queue_unavailable") {
      return "The worker queue is unavailable right now, so the run was not started. Try again in a couple of minutes.";
    }
    if (error.status === 429) {
      return "Too many requests from your connection. Wait a minute and try again.";
    }
    if (error.status >= 500 || error.status === 0) {
      return "The pipeline service is not responding right now. The figures shown are from the last successful read.";
    }
    return error.message;
  }
  return "The request did not reach the server. Check your connection and try again.";
}

export function RunTrigger({ onQueued }: { onQueued: (runId: string) => void }) {
  const scenarios = useScenarios();
  const trigger = useTriggerRun();
  const [selected, setSelected] = useState("standard");
  const hydrated = useHydrated();

  if (scenarios.isPending) return <p className="text-sm text-muted">Loading scenarios…</p>;
  if (scenarios.isError) {
    return (
      <p className="text-sm text-fail">
        Scenarios could not be loaded, so runs cannot be started from here right now.
      </p>
    );
  }

  const current = scenarios.data.find((s) => s.id === selected) ?? scenarios.data[0];

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (current) trigger.mutate(current.id, { onSuccess: (res) => onQueued(res.run_id) });
      }}
      className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]"
    >
      <fieldset>
        <legend className="text-sm font-semibold text-text">Start a run</legend>
        <p className="mt-1 text-sm text-muted">
          Every scenario uses the real invoice data. The last three add a simulated failure.
        </p>
        <div className="mt-4 space-y-1.5">
          {scenarios.data.map((s) => {
            const checked = current?.id === s.id;
            return (
              <label
                key={s.id}
                className={`flex cursor-pointer items-center gap-3 rounded-sm px-3 py-2 ring-1 ring-inset transition-colors ${
                  checked ? "bg-surface-2 ring-line-strong" : "ring-line hover:bg-surface-2/60"
                }`}
              >
                <input
                  type="radio"
                  name="scenario"
                  value={s.id}
                  checked={checked}
                  onChange={() => setSelected(s.id)}
                  className="accent-[var(--color-text)]"
                />
                <span className="text-sm font-medium text-text">{s.title}</span>
                {s.simulated && (
                  <span className="ml-auto">
                    <Pill tone="warn">Simulated fault</Pill>
                  </span>
                )}
              </label>
            );
          })}
        </div>
      </fieldset>

      {current && (
        <div className="flex flex-col lg:pt-[3.25rem]">
          <p className="font-medium text-text">{current.title}</p>
          <p className="mt-1.5 text-sm text-muted">{current.description}</p>
          <p className="mt-3 text-sm">
            <span className="text-faint">Expected outcome: </span>
            <span className="text-text">{current.expected}</span>
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              className={buttonClasses("primary", "sm")}
              disabled={!hydrated || trigger.isPending}
            >
              {trigger.isPending ? "Starting…" : "Run scenario"}
            </button>
            <span className="text-xs text-faint">Each visitor can start 3 runs per hour</span>
          </div>
          <div aria-live="polite" className="mt-3 min-h-5 text-sm">
            {trigger.isError && <p className="text-fail">{triggerErrorMessage(trigger.error)}</p>}
            {trigger.isSuccess && (
              <p className="text-pass">
                {trigger.data.pending_runs > 1
                  ? `Run queued, number ${trigger.data.pending_runs} in line. `
                  : "Run queued. "}
                Follow it in the run details below.
              </p>
            )}
          </div>
        </div>
      )}
    </form>
  );
}
