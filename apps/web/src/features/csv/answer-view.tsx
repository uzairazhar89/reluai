"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";

import { buttonClasses } from "@/components/button-link";
import { Pill } from "@/components/status-badge";
import type { AskResponse } from "@/lib/api/types";
import { formatInt } from "@/lib/format";

import { formatCell, toCsv, type Grain } from "./format";
import { ResultChart } from "./result-chart";

const TABS = [
  ["chart", "Chart"],
  ["table", "Table"],
  ["sql", "SQL"],
  ["pandas", "pandas"],
] as const;
type Tab = (typeof TABS)[number][0];

function Interpreter({ answer }: { answer: AskResponse }) {
  const it = answer.interpreter;
  if (it.kind === "rules") {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <Pill tone="pass">Rules</Pill>
        <span className="text-xs text-muted">Read by the rule-based parser, no model used</span>
      </span>
    );
  }
  if (it.kind === "llm") {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <Pill tone="warn">LLM</Pill>
        <span className="text-xs text-muted">
          {it.provider} {it.model}
          {", "}
          {formatInt(it.tokens)} tokens, {it.latency_ms} ms
          {it.retries > 0 &&
            `, ${it.retries} ${it.retries === 1 ? "retry" : "retries"} after validation`}
        </span>
      </span>
    );
  }
  return null;
}

function download(answer: AskResponse) {
  const csv = toCsv(answer.columns ?? [], answer.rows ?? []);
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "answer.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function CodeBlock({ code, label }: { code: string; label: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      className="overflow-x-auto rounded-sm bg-ink p-4 font-mono text-[0.8125rem] leading-relaxed text-text ring-1 ring-line"
    >
      <code>{code}</code>
    </pre>
  );
}

export function AnswerView({ answer }: { answer: AskResponse }) {
  const [tab, setTab] = useState<Tab>(answer.chart === "table" ? "table" : "chart");
  const id = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const columns = answer.columns ?? [];
  const rows = answer.rows ?? [];
  const grain = (answer.plan?.time_bucket?.grain ?? null) as Grain | null;

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const focused = tabRefs.current.findIndex((el) => el === document.activeElement);
    const i = focused >= 0 ? focused : TABS.findIndex(([t]) => t === tab);
    const next =
      e.key === "ArrowRight"
        ? (i + 1) % TABS.length
        : e.key === "ArrowLeft"
          ? (i + TABS.length - 1) % TABS.length
          : -1;
    if (next < 0) return;
    e.preventDefault();
    setTab(TABS[next]![0]);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-xs text-faint">Interpreted as</p>
        <p className="text-lg leading-snug text-text">{answer.summary}</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Interpreter answer={answer} />
          <span className="num text-xs text-faint">
            Query ran in {answer.timings.query_ms} ms, {answer.timings.total_ms} ms in all
          </span>
        </div>
      </div>

      <div>
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line">
          <div role="tablist" aria-label="Answer views" className="flex" onKeyDown={onKey}>
            {TABS.map(([t, label], i) => (
              <button
                key={t}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                role="tab"
                id={`${id}-${t}-tab`}
                aria-selected={tab === t}
                aria-controls={`${id}-${t}`}
                tabIndex={tab === t ? 0 : -1}
                onClick={() => setTab(t)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
                  tab === t
                    ? "border-text text-text"
                    : "border-transparent text-muted hover:text-text"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() => download(answer)}
              className={`${buttonClasses("quiet")} mb-2 text-sm`}
            >
              Download CSV
            </button>
          )}
        </div>

        <div
          role="tabpanel"
          id={`${id}-${tab}`}
          aria-labelledby={`${id}-${tab}-tab`}
          className="pt-5"
        >
          {tab === "chart" && <ResultChart answer={answer} />}
          {tab === "table" &&
            (rows.length === 0 ? (
              <p className="text-sm text-muted">No rows matched the filters.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">{answer.summary}</caption>
                  <thead className="text-xs text-muted">
                    <tr className="border-b border-line">
                      {columns.map((c) => (
                        <th
                          key={c.name}
                          scope="col"
                          className={`py-2 pr-4 font-medium ${c.role === "metric" ? "text-right" : ""}`}
                        >
                          {c.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="text-text">
                    {rows.map((r, i) => (
                      <tr key={i} className="border-b border-line/60">
                        {columns.map((c, j) => (
                          <td
                            key={c.name}
                            className={`py-1.5 pr-4 ${c.role === "metric" ? "num text-right" : ""} ${r[j] === null ? "text-faint" : ""}`}
                          >
                            {formatCell(r[j], c, grain)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          {tab === "sql" && answer.sql && (
            <div className="space-y-3">
              <CodeBlock code={answer.sql} label="SQL that was run" />
              <p className="text-xs text-faint">
                Shown with the values filled in. It ran with bound parameters on a read-only,
                sandboxed DuckDB connection.
              </p>
            </div>
          )}
          {tab === "pandas" && answer.pandas && (
            <div className="space-y-3">
              <CodeBlock code={answer.pandas} label="Equivalent pandas code" />
              <p className="text-xs text-faint">
                The same query written in pandas, for reading or reuse. Tests check that it returns
                the same rows as the SQL.
              </p>
            </div>
          )}
        </div>
        {answer.truncated && (
          <p className="mt-3 text-xs text-faint">Showing the first {rows.length} rows.</p>
        )}
      </div>
    </div>
  );
}
