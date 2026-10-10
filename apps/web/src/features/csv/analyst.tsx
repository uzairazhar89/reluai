"use client";

import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { buttonClasses } from "@/components/button-link";
import { QueryProvider } from "@/components/query-provider";
import { Pill } from "@/components/status-badge";
import type { AskResponse, CsvDataset } from "@/lib/api/types";
import { formatInt } from "@/lib/format";
import { useHydrated } from "@/lib/now";

import { AnswerView } from "./answer-view";
import { askErrorMessage, uploadErrorMessage } from "./messages";
import { ProfilePanel } from "./profile-panel";
import { BUNDLED, MAX_UPLOAD_BYTES, useAsk, useDataset, useUpload } from "./queries";

type Source = "bundled" | "upload";

function expiresIn(iso: string | null | undefined): string {
  if (!iso) return "";
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60_000));
  return minutes <= 1 ? "within a minute" : `in ${minutes} minutes`;
}

function NotAnswered({ answer, onPick }: { answer: AskResponse; onPick: (q: string) => void }) {
  const refused = answer.status === "refused";
  return (
    <div className="space-y-4">
      <p className="text-text">
        {refused ? "The model decided this table cannot answer that: " : ""}
        {answer.message}
      </p>
      {(answer.issues ?? []).length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          {answer.issues!.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
      {(answer.suggestions ?? []).length > 0 && (
        <div>
          <p className="text-sm text-muted">Questions this table can answer:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {answer.suggestions!.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPick(s)}
                className="rounded-sm px-2.5 py-1 text-sm text-text ring-1 ring-inset ring-line hover:bg-surface-2"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalystInner({ initialDataset }: { initialDataset?: CsvDataset }) {
  const [source, setSource] = useState<Source>("bundled");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [allowLlm, setAllowLlm] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const hydrated = useHydrated();

  const datasetId = source === "upload" && uploadId ? uploadId : BUNDLED;
  const dataset = useDataset(datasetId, initialDataset);
  const upload = useUpload();
  const ask = useAsk();

  const showingUpload = source === "upload";
  const ready = !showingUpload || uploadId !== null;
  const answer = ask.data;
  const answerMatches = answer && ask.variables?.dataset === datasetId;

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || !ready) return;
    ask.mutate({
      dataset: datasetId,
      question: text,
      allow_llm: showingUpload && allowLlm,
    });
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    setFileError(null);
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setFileError(
        `This file is ${formatInt(Math.round(file.size / 1000))} KB; files can be up to 2,000 KB.`,
      );
      return;
    }
    upload.mutate(file, {
      onSuccess: (d) => {
        setUploadId(d.id);
        ask.reset();
      },
    });
  };

  const examples = dataset.data?.examples ?? [];
  const llmAvailable = dataset.data?.llm_available ?? false;

  return (
    <div className="space-y-8">
      {/* 1. Which table */}
      <fieldset>
        <legend className="text-sm font-semibold text-text">Table to analyse</legend>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {(
            [
              [
                "bundled",
                "Retailer invoices",
                "1,067,371 real invoice lines, Dec 2009 to Dec 2011",
              ],
              ["upload", "Your CSV file", "Up to 2 MB and 50,000 rows, deleted after an hour"],
            ] as const
          ).map(([value, title, note]) => (
            <label
              key={value}
              className={`flex cursor-pointer gap-3 rounded-sm px-3.5 py-3 ring-1 ring-inset transition-colors ${
                source === value
                  ? "bg-surface-2 ring-line-strong"
                  : "ring-line hover:bg-surface-2/60"
              }`}
            >
              <input
                type="radio"
                name="csv-source"
                value={value}
                checked={source === value}
                onChange={() => {
                  setSource(value);
                  ask.reset();
                }}
                className="mt-1 accent-[var(--color-text)]"
              />
              <span>
                <span className="block text-sm font-medium text-text">{title}</span>
                <span className="block text-xs text-muted">{note}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {showingUpload && (
        <div className="rounded-sm p-4 ring-1 ring-inset ring-line">
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileRef}
              id="csv-file"
              type="file"
              accept=".csv,.tsv,.txt,text/csv,text/plain"
              onChange={onFile}
              className="hidden"
              tabIndex={-1}
              aria-hidden
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={!hydrated || upload.isPending}
              className={buttonClasses(uploadId ? "secondary" : "primary", "sm")}
            >
              {upload.isPending
                ? "Uploading…"
                : uploadId
                  ? "Upload a different file"
                  : "Choose a CSV file"}
            </button>
            {uploadId && dataset.data && dataset.data.kind === "upload" && (
              <span className="text-sm text-muted">
                <span className="text-text">{dataset.data.title}</span>, deleted{" "}
                {expiresIn(dataset.data.expires_at)}
              </span>
            )}
          </div>
          <p className="mt-3 text-xs text-faint">
            The file is stored only on this server, never logged, and deleted after an hour. Its
            rows are never sent to a language model.
          </p>
          <div aria-live="polite" className="text-sm">
            {fileError && <p className="mt-2 text-fail">{fileError}</p>}
            {upload.isError && <p className="mt-2 text-fail">{uploadErrorMessage(upload.error)}</p>}
          </div>
        </div>
      )}

      {/* 2. What is in it */}
      {ready && (
        <details className="group rounded-sm ring-1 ring-inset ring-line" open={showingUpload}>
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm">
            <span className="font-medium text-text">Columns and data quality</span>
            <span className="text-xs text-muted">
              {dataset.data
                ? `${dataset.data.columns.length} columns, ${dataset.data.findings.length} findings`
                : dataset.isError
                  ? "Not available"
                  : "Loading…"}
              <span
                aria-hidden
                className="ml-2 inline-block transition-transform group-open:rotate-90"
              >
                ›
              </span>
            </span>
          </summary>
          <div className="border-t border-line px-4 py-4">
            {dataset.data ? (
              <ProfilePanel dataset={dataset.data} />
            ) : dataset.isError ? (
              <p className="text-sm text-fail">{askErrorMessage(dataset.error)}</p>
            ) : (
              <p className="text-sm text-muted">Profiling the table…</p>
            )}
          </div>
        </details>
      )}

      {/* 3. Ask */}
      {ready && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            submit(question);
          }}
          className="space-y-3"
        >
          <label htmlFor="csv-question" className="block text-sm font-semibold text-text">
            Ask a question in plain English
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="csv-question"
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={300}
              minLength={3}
              autoComplete="off"
              placeholder={
                examples[1] ? `For example: ${examples[1]}` : "Ask about totals, counts or trends"
              }
              className="h-11 w-full min-w-0 rounded-sm sm:flex-1 bg-ink px-3.5 text-text ring-1 ring-inset ring-line-strong placeholder:text-faint focus:outline-none focus-visible:ring-2 focus-visible:ring-link"
            />
            <button
              type="submit"
              className={buttonClasses("primary", "md")}
              disabled={!hydrated || ask.isPending || question.trim().length < 3}
            >
              {ask.isPending ? "Answering…" : "Ask"}
            </button>
          </div>
          {examples.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-faint">Try:</span>
              {examples.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  disabled={!hydrated || ask.isPending}
                  onClick={() => {
                    setQuestion(ex);
                    submit(ex);
                  }}
                  className="rounded-sm px-2.5 py-1 text-sm text-muted ring-1 ring-inset ring-line hover:bg-surface-2 hover:text-text disabled:opacity-50"
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
          {showingUpload && (
            <label
              className={`flex max-w-[60ch] items-start gap-3 pt-1 text-sm ${llmAvailable ? "cursor-pointer" : "opacity-70"}`}
            >
              <input
                type="checkbox"
                checked={allowLlm && llmAvailable}
                disabled={!llmAvailable}
                onChange={(e) => setAllowLlm(e.target.checked)}
                className="mt-1 accent-[var(--color-text)]"
              />
              <span className="text-muted">
                <span className="text-text">
                  Let a language model read questions the rules cannot.
                </span>{" "}
                {llmAvailable
                  ? "Sends your question and the column names and types to a free-tier model provider. Never the rows."
                  : "No language model is configured on this server right now, so only the rules answer."}
              </span>
            </label>
          )}
        </form>
      )}

      {/* 4. Answer */}
      <section aria-live="polite" aria-label="Answer" className="min-h-6">
        {ask.isError && <p className="text-fail">{askErrorMessage(ask.error)}</p>}
        {answerMatches && answer && (
          <div className="rounded-sm bg-surface p-4 ring-1 ring-inset ring-line sm:p-6">
            <p className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-faint">You asked</span>
              <span className="text-text">“{answer.question}”</span>
              {answer.status !== "answered" && (
                <Pill tone={answer.status === "failed" ? "fail" : "neutral"}>
                  {answer.status === "failed"
                    ? "Query failed"
                    : answer.status === "refused"
                      ? "Declined"
                      : "Not understood"}
                </Pill>
              )}
            </p>
            {answer.status === "answered" ? (
              <AnswerView key={`${answer.question}-${answer.timings.total_ms}`} answer={answer} />
            ) : answer.status === "failed" ? (
              <div className="space-y-3">
                <p className="text-text">{answer.message}</p>
                {answer.summary && (
                  <p className="text-sm text-muted">Interpreted as: {answer.summary}</p>
                )}
              </div>
            ) : (
              <NotAnswered
                answer={answer}
                onPick={(q) => {
                  setQuestion(q);
                  submit(q);
                }}
              />
            )}
          </div>
        )}
      </section>
    </div>
  );
}

/** The interactive demo; mounts its own query cache like the other demo islands. */
export function Analyst({ initialDataset }: { initialDataset?: CsvDataset }) {
  return (
    <QueryProvider>
      <AnalystInner initialDataset={initialDataset} />
    </QueryProvider>
  );
}
