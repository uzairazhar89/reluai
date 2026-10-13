"use client";

import { useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";

import { buttonClasses } from "@/components/button-link";
import { QueryProvider } from "@/components/query-provider";
import { Pill } from "@/components/status-badge";
import type { DocumentAnswer, DocumentInfo, DocumentPassage } from "@/lib/api/types";
import { formatInt } from "@/lib/format";
import { useHydrated } from "@/lib/now";

import {
  answerParts,
  fileSize,
  isProcessing,
  matchLabel,
  methodLabel,
  pagesLabel,
  segments,
  stageLabel,
  stageProgress,
  whyRetrieved,
} from "./format";
import { docsErrorMessage } from "./messages";
import {
  MAX_UPLOAD_BYTES,
  useAsk,
  useChunks,
  useDelete,
  useDocument,
  useSample,
  useUpload,
} from "./queries";

type Source = "sample" | "upload";

export const SAMPLE_QUESTIONS = [
  "What are the four functions of the AI RMF core?",
  "Which characteristics make an AI system trustworthy?",
  "Who are AI actors?",
  "What does the framework say about cryptocurrency?",
];

function expiresIn(iso: string | null | undefined): string {
  if (!iso) return "";
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60_000));
  return minutes <= 1 ? "within a minute" : `in ${minutes} minutes`;
}

function Marked({ text, ranges }: { text: string; ranges: [number, number][] }) {
  return (
    <>
      {segments(text, ranges).map((s, i) =>
        s.mark ? (
          <mark key={i} className="rounded-[2px] bg-link/20 px-0.5 text-text">
            {s.text}
          </mark>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}

/* ------------------------------------------------------------------ document */
function ProgressLine({ doc }: { doc: DocumentInfo }) {
  const share = stageProgress(doc);
  return (
    <div className="space-y-2" role="status">
      <p className="text-sm text-text">{stageLabel(doc)}…</p>
      <div className="h-1 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full bg-link transition-[width] duration-300 ${share === null ? "w-1/3 animate-pulse" : ""}`}
          style={share === null ? undefined : { width: `${Math.max(4, share * 100)}%` }}
        />
      </div>
    </div>
  );
}

function Outline({ doc }: { doc: DocumentInfo }) {
  if (doc.outline.length === 0) {
    return <p className="text-sm text-muted">No headings were recognised in this document.</p>;
  }
  return (
    <ol className="max-h-72 space-y-1 overflow-auto pr-2 text-sm">
      {doc.outline.slice(0, 120).map((o, i) => (
        <li
          key={`${i}-${o.title}`}
          className="flex gap-3"
          style={{ paddingLeft: `${(o.level - 1) * 0.9}rem` }}
        >
          <span className="num w-10 shrink-0 text-right text-xs text-faint">p. {o.page}</span>
          <span className={o.level === 1 ? "text-text" : "text-muted"}>{o.title}</span>
        </li>
      ))}
    </ol>
  );
}

function DocumentFacts({ doc }: { doc: DocumentInfo }) {
  const facts: [string, ReactNode][] = [
    [
      "Pages",
      `${formatInt(doc.pages_read)} read of ${formatInt(doc.page_count)}` +
        (doc.pages_ocr ? `, ${formatInt(doc.pages_ocr)} with OCR` : ""),
    ],
    ["Text", `${formatInt(doc.chars)} characters, ${formatInt(doc.chunks)} passages`],
    [
      "Search",
      doc.search_mode === "hybrid"
        ? "Keywords and meaning (hybrid)"
        : doc.search_mode === "keyword"
          ? "Keywords only"
          : "–",
    ],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
      {facts.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs text-faint">{k}</dt>
          <dd className="text-text">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function ChunkExplorer({ doc }: { doc: DocumentInfo }) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const chunks = useChunks(doc.id, offset, open);
  const total = chunks.data?.total ?? doc.chunks;
  return (
    <details
      className="group rounded-sm ring-1 ring-inset ring-line"
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm">
        <span className="font-medium text-text">How it was split into passages</span>
        <span className="text-xs text-muted">
          {formatInt(doc.chunks)} passages
          <span aria-hidden className="ml-2 inline-block transition-transform group-open:rotate-90">
            ›
          </span>
        </span>
      </summary>
      <div className="space-y-3 border-t border-line px-4 py-4">
        <p className="text-xs text-muted">
          Each passage is an exact span of the text, filed under its heading path, so an answer can
          point to where it came from. Consecutive passages share a sentence.
        </p>
        {chunks.isError && <p className="text-sm text-fail">{docsErrorMessage(chunks.error)}</p>}
        <ol className="space-y-3">
          {(chunks.data?.items ?? []).map((c) => (
            <li key={c.ordinal} className="rounded-sm bg-surface-2 px-3 py-2.5">
              <p className="flex flex-wrap gap-x-2 text-xs text-faint">
                <span className="num">#{c.ordinal + 1}</span>
                <span>{pagesLabel(c.page_from, c.page_to)}</span>
                <span>{formatInt(c.words)} words</span>
                {c.heading && <span className="text-muted">{c.heading}</span>}
              </p>
              <p className="mt-1 line-clamp-4 text-sm text-muted">{c.text}</p>
            </li>
          ))}
        </ol>
        {total > 10 && (
          <div className="flex items-center gap-3 text-sm">
            <button
              type="button"
              className={buttonClasses("secondary", "sm")}
              disabled={offset === 0 || chunks.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 10))}
            >
              Previous
            </button>
            <span className="num text-xs text-muted">
              {formatInt(offset + 1)}–{formatInt(Math.min(total, offset + 10))} of{" "}
              {formatInt(total)}
            </span>
            <button
              type="button"
              className={buttonClasses("secondary", "sm")}
              disabled={offset + 10 >= total || chunks.isFetching}
              onClick={() => setOffset(offset + 10)}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </details>
  );
}

function DocumentCard({
  doc,
  onDelete,
  deleting,
}: {
  doc: DocumentInfo;
  onDelete?: () => void;
  deleting?: boolean;
}) {
  return (
    <div className="space-y-4 rounded-sm p-4 ring-1 ring-inset ring-line sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-text">{doc.title ?? doc.filename}</p>
          <p className="mt-0.5 text-xs text-muted">
            {doc.title && doc.title !== doc.filename ? `${doc.filename}, ` : ""}
            {fileSize(doc.file_bytes)}
            {doc.kind === "upload" && doc.expires_at && <>, deleted {expiresIn(doc.expires_at)}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {doc.kind === "sample" ? (
            <Pill tone="pass">Real document</Pill>
          ) : (
            <Pill>Your upload</Pill>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className={buttonClasses("secondary", "sm")}
            >
              {deleting ? "Deleting…" : "Delete now"}
            </button>
          )}
        </div>
      </div>
      {isProcessing(doc.status) ? (
        <ProgressLine doc={doc} />
      ) : doc.status === "failed" ? (
        <p className="text-sm text-fail">{doc.error_message ?? "This PDF could not be read."}</p>
      ) : (
        <>
          <DocumentFacts doc={doc} />
          {doc.warnings.length > 0 && (
            <ul className="space-y-1 text-sm text-warn">
              {doc.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <details className="group">
            <summary className="cursor-pointer list-none text-sm text-muted hover:text-text">
              <span
                aria-hidden
                className="mr-1.5 inline-block transition-transform group-open:rotate-90"
              >
                ›
              </span>
              Headings found ({formatInt(doc.outline.length)})
            </summary>
            <div className="mt-3">
              <Outline doc={doc} />
            </div>
          </details>
        </>
      )}
      {doc.source && (
        <p className="text-xs text-faint">
          {doc.source.publisher}.{" "}
          <a href={doc.source.url} className="prose-link" rel="noreferrer">
            {doc.source.url.replace("https://", "")}
          </a>
          . {doc.source.licence}.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ answer */
function PassageCard({
  p,
  answer,
  flash,
}: {
  p: DocumentPassage;
  answer: DocumentAnswer;
  flash: boolean;
}) {
  const quotes = answer.quotes
    .filter((q) => q.number === p.number)
    .map((q) => [q.start, q.end] as [number, number]);
  const cited = answer.citations.includes(p.number);
  return (
    <li
      id={`passage-${p.number}`}
      className={`scroll-mt-24 rounded-sm px-3.5 py-3 ring-1 ring-inset transition-colors ${
        flash ? "bg-link/10 ring-link/60" : cited ? "ring-line-strong" : "ring-line"
      }`}
    >
      <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
        <span className="num font-medium text-text">[{p.number}]</span>
        <span className="text-text">{pagesLabel(p.page_from, p.page_to)}</span>
        {p.heading && <span className="text-muted">{p.heading}</span>}
        <span className="text-faint">{whyRetrieved(p)}</span>
      </p>
      <p className={`mt-1.5 text-sm text-muted ${cited ? "" : "line-clamp-3"}`}>
        {quotes.length > 0 ? (
          <Marked text={p.text} ranges={quotes} />
        ) : cited ? (
          p.text
        ) : (
          <Marked text={p.snippet} ranges={p.highlights} />
        )}
      </p>
    </li>
  );
}

function AnswerCard({ answer }: { answer: DocumentAnswer }) {
  const [flash, setFlash] = useState<number | null>(null);
  const jump = (n: number) => {
    document
      .getElementById(`passage-${n}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlash(n);
    window.setTimeout(() => setFlash((f) => (f === n ? null : f)), 1600);
  };
  return (
    <div className="space-y-5 rounded-sm bg-surface p-4 ring-1 ring-inset ring-line sm:p-6">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-faint">You asked</span>
        <span className="text-text">“{answer.question}”</span>
      </p>
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Pill tone={answer.abstained ? "warn" : "pass"}>
            {answer.abstained ? "Not found in the document" : "Answer"}
          </Pill>
          <Pill>{methodLabel(answer)}</Pill>
        </div>
        <p className="max-w-[70ch] text-[1.0625rem] leading-relaxed text-text">
          {answerParts(answer.answer).map((part, i) =>
            part.kind === "text" ? (
              <span key={i}>{part.text}</span>
            ) : (
              <span key={i} className="whitespace-nowrap">
                {part.numbers.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => jump(n)}
                    aria-label={`Show passage ${n}`}
                    className="num mx-0.5 rounded-sm px-1 text-sm text-link ring-1 ring-inset ring-link/40 hover:bg-link/10"
                  >
                    {n}
                  </button>
                ))}
              </span>
            ),
          )}
        </p>
        {answer.note && answer.abstained && (
          <p className="mt-2 text-sm text-muted">Why: {answer.note}.</p>
        )}
        {answer.fallback_reason && (
          <p className="mt-2 text-xs text-faint">
            Answered without a model: {answer.fallback_reason}.
          </p>
        )}
      </div>
      {answer.passages.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-text">
            {answer.abstained ? "Closest passages" : "Passages retrieved"}
          </p>
          <ol className="space-y-2">
            {answer.passages.map((p) => (
              <PassageCard key={p.number} p={p} answer={answer} flash={flash === p.number} />
            ))}
          </ol>
        </div>
      )}
      <p className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-faint">
        <span>
          Search: {answer.search_mode === "hybrid" ? "keywords + meaning" : "keywords"},{" "}
          {answer.retrieval_ms} ms
        </span>
        <span>Answer: {answer.answer_ms} ms</span>
        {matchLabel(answer) && <span>{matchLabel(answer)}</span>}
        <span>Model tokens: {formatInt(answer.tokens)}</span>
        {answer.retries > 0 && <span>Model retries: {answer.retries}</span>}
        {answer.attempts
          .filter((a) => a.outcome !== "ok")
          .map((a) => (
            <span key={`${a.provider}-${a.outcome}`}>
              Skipped {a.provider} ({a.outcome.replaceAll("_", " ")})
            </span>
          ))}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ demo */
function UploadBox({
  busy,
  hasDocument,
  onFile,
}: {
  busy: boolean;
  hasDocument: boolean;
  onFile: (f: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const hydrated = useHydrated();
  const [over, setOver] = useState(false);
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  };
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={`rounded-sm border border-dashed p-4 transition-colors ${over ? "border-link bg-link/5" : "border-line-strong"}`}
    >
      <input
        ref={ref}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onFile(file);
        }}
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => ref.current?.click()}
          disabled={!hydrated || busy}
          className={buttonClasses(hasDocument ? "secondary" : "primary", "sm")}
        >
          {busy ? "Uploading…" : hasDocument ? "Upload a different PDF" : "Choose a PDF"}
        </button>
        <span className="text-sm text-muted">or drop it here. Up to 10 MB; 60 pages are read.</span>
      </div>
      <p className="mt-3 text-xs text-faint">
        The PDF is read in memory and not kept; the extracted text is deleted after an hour, and
        neither is logged. Text from scanned pages is read with OCR on this server (up to 5 pages).
      </p>
    </div>
  );
}

function QaInner({ initialSample }: { initialSample?: DocumentInfo }) {
  const [source, setSource] = useState<Source>("sample");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [allowExternal, setAllowExternal] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const hydrated = useHydrated();

  const sample = useSample(initialSample);
  const uploaded = useDocument(source === "upload" ? uploadId : null);
  const upload = useUpload();
  const ask = useAsk();
  const remove = useDelete();

  const doc = source === "sample" ? sample.data : uploadId ? uploaded.data : undefined;
  const docError = source === "sample" ? sample.error : uploaded.error;
  const ready = doc?.status === "ready";
  const answer = ask.data;
  const answerMatches = answer && doc && ask.variables?.id === doc.id;

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 2 || !doc || !ready) return;
    ask.mutate({
      id: doc.id,
      body: {
        question: text,
        mode: "auto",
        allow_external: doc.kind === "upload" && allowExternal,
      },
    });
  };

  const onFile = (file: File) => {
    setFileError(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setFileError(`This file is ${fileSize(file.size)}; PDFs can be up to 10 MB.`);
      return;
    }
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      setFileError("Only PDF files can be uploaded.");
      return;
    }
    upload.mutate(file, {
      onSuccess: (d) => {
        setUploadId(d.id);
        ask.reset();
      },
    });
  };

  const examples = source === "sample" ? SAMPLE_QUESTIONS : [];
  const externalAvailable = doc?.external_llm_available ?? false;

  return (
    <div className="space-y-8">
      <fieldset>
        <legend className="text-sm font-semibold text-text">Document to ask about</legend>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {(
            [
              ["sample", "NIST AI Risk Management Framework", "Real 48-page PDF, already indexed"],
              ["upload", "Your PDF", "Up to 10 MB, deleted after an hour"],
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
                name="docs-source"
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

      {source === "upload" && (
        <div className="space-y-2">
          <UploadBox busy={upload.isPending} hasDocument={uploadId !== null} onFile={onFile} />
          <div aria-live="polite" className="text-sm">
            {fileError && <p className="text-fail">{fileError}</p>}
            {upload.isError && <p className="text-fail">{docsErrorMessage(upload.error)}</p>}
            {remove.isError && <p className="text-fail">{docsErrorMessage(remove.error)}</p>}
          </div>
        </div>
      )}

      <div aria-live="polite">
        {doc ? (
          <div className="space-y-3">
            <DocumentCard
              doc={doc}
              deleting={remove.isPending}
              onDelete={
                doc.kind === "upload"
                  ? () =>
                      remove.mutate(doc.id, {
                        onSuccess: () => {
                          setUploadId(null);
                          ask.reset();
                        },
                      })
                  : undefined
              }
            />
            {ready && <ChunkExplorer key={doc.id} doc={doc} />}
          </div>
        ) : docError ? (
          <p className="text-sm text-fail">{docsErrorMessage(docError)}</p>
        ) : source === "sample" ? (
          <p className="text-sm text-muted">Loading the sample document…</p>
        ) : null}
      </div>

      {ready && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            submit(question);
          }}
          className="space-y-3"
        >
          <label htmlFor="docs-question" className="block text-sm font-semibold text-text">
            Ask a question about this document
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="docs-question"
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={300}
              minLength={2}
              autoComplete="off"
              placeholder={examples[0] ? `For example: ${examples[0]}` : "What does it say about…?"}
              className="h-11 w-full min-w-0 rounded-sm bg-ink px-3.5 text-text ring-1 ring-inset ring-line-strong placeholder:text-faint focus:outline-none focus-visible:ring-2 focus-visible:ring-link sm:flex-1"
            />
            <button
              type="submit"
              className={buttonClasses("primary", "md")}
              disabled={!hydrated || ask.isPending || question.trim().length < 2}
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
                  className="rounded-sm px-2.5 py-1 text-left text-sm text-muted ring-1 ring-inset ring-line hover:bg-surface-2 hover:text-text disabled:opacity-50"
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
          {doc?.kind === "upload" && (
            <label
              className={`flex max-w-[64ch] items-start gap-3 pt-1 text-sm ${externalAvailable ? "cursor-pointer" : "opacity-70"}`}
            >
              <input
                type="checkbox"
                checked={allowExternal && externalAvailable}
                disabled={!externalAvailable}
                onChange={(e) => setAllowExternal(e.target.checked)}
                className="mt-1 accent-[var(--color-text)]"
              />
              <span className="text-muted">
                <span className="text-text">Let a hosted model write the answer.</span>{" "}
                {externalAvailable
                  ? "Sends your question and the retrieved passages (not the whole file) to a free-tier model provider."
                  : "No hosted model is configured on this server right now, so answers are quoted from the passages."}
              </span>
            </label>
          )}
        </form>
      )}

      <section aria-live="polite" aria-label="Answer" className="min-h-6">
        {ask.isError && <p className="text-fail">{docsErrorMessage(ask.error)}</p>}
        {answerMatches && answer && <AnswerCard key={answer.question} answer={answer} />}
      </section>
    </div>
  );
}

/** The interactive demo; mounts its own query cache like the other demo islands. */
export function QaDemo({ initialSample }: { initialSample?: DocumentInfo }) {
  return (
    <QueryProvider>
      <QaInner initialSample={initialSample} />
    </QueryProvider>
  );
}
