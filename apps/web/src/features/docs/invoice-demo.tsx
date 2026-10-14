"use client";

import { useMemo, useRef, useState, type DragEvent } from "react";

import { buttonClasses } from "@/components/button-link";
import { QueryProvider } from "@/components/query-provider";
import { Pill } from "@/components/status-badge";
import type { InvoiceDocument, InvoiceExtraction, InvoicePage, InvoiceRun } from "@/lib/api/types";
import { formatInt } from "@/lib/format";
import { useHydrated } from "@/lib/now";

import { fileSize } from "./format";
import {
  boxStyle,
  CHECK_LABELS,
  duration,
  expectedCell,
  FIELD_LABELS,
  LINE_FIELDS,
  lineVerdict,
  marks,
  ROLE_LABELS,
  runVerdict,
  showValue,
  type Mark,
  type Verdict,
} from "./invoice-format";
import { docsErrorMessage } from "./messages";
import { MAX_UPLOAD_BYTES, useInvoiceGallery, useInvoiceRun, useInvoiceUpload } from "./queries";

type Source = "sample" | "upload";
type Layouts = "dev" | "held_out";
type Format = "text" | "scan";

const verdictRing: Record<Verdict, string> = {
  right: "ring-pass/80 bg-pass/10",
  wrong: "ring-fail/90 bg-fail/15",
  unchecked: "ring-link/70 bg-link/10",
};

/* ------------------------------------------------------------------ choosing */
function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={label}>
      <span className="text-xs text-faint">{label}</span>
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={`rounded-sm px-2.5 py-1 text-sm ring-1 ring-inset transition-colors ${
            value === v
              ? "bg-surface-2 text-text ring-line-strong"
              : "text-muted ring-line hover:bg-surface-2/60 hover:text-text"
          }`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

const lastRunLabel: Record<string, [string, "pass" | "warn" | "fail"]> = {
  exact: ["Read exactly last run", "pass"],
  flagged: ["Flagged last run", "warn"],
  wrong: ["Wrong last run", "fail"],
};

function Picker({
  docs,
  busy,
  selected,
  onRead,
}: {
  docs: InvoiceDocument[];
  busy: boolean;
  selected: string | null;
  onRead: (id: string) => void;
}) {
  const hydrated = useHydrated();
  const [layouts, setLayouts] = useState<Layouts>("dev");
  const [format, setFormat] = useState<Format>("text");
  const shown = docs.filter((d) => d.split === layouts && d.scanned === (format === "scan"));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Segmented
          label="Layouts"
          value={layouts}
          onChange={setLayouts}
          options={[
            ["dev", "Used in development"],
            ["held_out", "New to the extractor"],
          ]}
        />
        <Segmented
          label="Format"
          value={format}
          onChange={setFormat}
          options={[
            ["text", "PDF"],
            ["scan", "Scanned"],
          ]}
        />
      </div>
      <ul
        aria-label="Sample invoices"
        className="max-h-72 divide-y divide-line/60 overflow-auto rounded-sm ring-1 ring-inset ring-line"
      >
        {shown.map((d) => {
          const last = d.last_run ? lastRunLabel[d.last_run] : undefined;
          return (
            <li
              key={d.id}
              className={`flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 ${selected === d.id ? "bg-surface-2" : ""}`}
            >
              <span className="min-w-0 flex-1 text-sm">
                <span className="text-text">
                  {d.credit_note ? "Credit note" : "Invoice"} {d.number}
                </span>
                <span className="text-muted">
                  {" "}
                  · {formatInt(d.lines)} line{d.lines === 1 ? "" : "s"} · layout {d.style}
                </span>
              </span>
              {last && <Pill tone={last[1]}>{last[0]}</Pill>}
              <a
                href={`/api/documents/invoices/${d.id}.pdf`}
                className="text-sm text-link hover:underline"
                target="_blank"
                rel="noreferrer"
                aria-label={`Open invoice ${d.number} as a PDF`}
              >
                PDF
              </a>
              <button
                type="button"
                onClick={() => onRead(d.id)}
                disabled={!hydrated || busy}
                className={buttonClasses("secondary", "sm")}
                aria-label={`Read invoice ${d.number}`}
              >
                Read it
              </button>
            </li>
          );
        })}
        {shown.length === 0 && (
          <li className="px-3 py-3 text-sm text-muted">No invoices in this group.</li>
        )}
      </ul>
    </div>
  );
}

function UploadBox({ busy, onFile }: { busy: boolean; onFile: (f: File) => void }) {
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
          className={buttonClasses("primary", "sm")}
        >
          {busy ? "Reading…" : "Choose an invoice PDF"}
        </button>
        <span className="text-sm text-muted">or drop it here. Up to 10 MB; 4 pages are read.</span>
      </div>
      <p className="mt-3 text-xs text-faint">
        Read once, in memory, in an isolated process; nothing is stored or logged. Works best on
        invoices with one table of line items, in English. Scanned pages are read with OCR.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ the result */
function PageView({
  page,
  pageMarks,
  focus,
  setFocus,
}: {
  page: InvoicePage;
  pageMarks: Mark[];
  focus: string | null;
  setFocus: (k: string | null) => void;
}) {
  if (!page.preview) return null;
  return (
    <div className="relative overflow-hidden rounded-sm bg-white ring-1 ring-line">
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from the API */}
      <img
        src={page.preview}
        alt={`Page ${page.number} of the invoice${page.method === "ocr" ? " (scanned, read with OCR)" : ""}`}
        className="block h-auto w-full"
      />
      {pageMarks.map((m) => (
        <span
          key={m.key}
          title={m.label}
          onMouseEnter={() => setFocus(m.key)}
          onMouseLeave={() => setFocus(null)}
          style={boxStyle(m.box, page)}
          className={`absolute rounded-[2px] ring-1 ring-inset transition-opacity ${verdictRing[m.verdict]} ${
            focus && focus !== m.key ? "opacity-25" : "opacity-100"
          } ${focus === m.key ? "ring-2" : ""}`}
        />
      ))}
    </div>
  );
}

function Tick({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? "text-pass" : "text-fail"}>
      <span aria-hidden>{ok ? "✓" : "✗"}</span>
      <span className="sr-only">{ok ? "matches" : "differs"}</span>
    </span>
  );
}

function Fields({ run, setFocus }: { run: InvoiceRun; setFocus: (k: string | null) => void }) {
  const ex = run.extraction;
  const cmp = run.comparison;
  const names = ["number", "date", "customer", "country", "document_type", "total"] as const;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Header fields read from the invoice</caption>
      <thead className="text-xs text-faint">
        <tr className="border-b border-line">
          <th scope="col" className="py-1.5 pr-3 text-left font-medium">
            Field
          </th>
          <th scope="col" className="py-1.5 pr-3 text-left font-medium">
            Read
          </th>
          {cmp && (
            <th scope="col" className="py-1.5 text-left font-medium">
              Record
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {names.map((name) => {
          const f = name === "total" ? ex.total : ex.fields[name];
          const read =
            name === "document_type" ? ex.document_type : (f?.value as string | number | null);
          const verdict = cmp?.header[name];
          return (
            <tr
              key={name}
              className="border-b border-line/60 align-top"
              onMouseEnter={() => setFocus(name)}
              onMouseLeave={() => setFocus(null)}
            >
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted">
                {FIELD_LABELS[name]}
              </th>
              <td className="py-1.5 pr-3 text-text">
                <span className="num">{showValue(name, read)}</span>
                {f?.label && f.by !== "missing" && (
                  <span className="block text-xs text-faint">
                    {f.by === "elimination" ? "unfamiliar label " : "label "}“{f.label}”
                    {f.text && f.text !== String(read) && name !== "total"
                      ? `, printed “${f.text}”`
                      : ""}
                  </span>
                )}
              </td>
              {cmp && (
                <td className="py-1.5 text-muted">
                  {verdict && <Tick ok={verdict.correct} />}{" "}
                  {verdict && !verdict.correct && (
                    <span className="num">{showValue(name, verdict.record)}</span>
                  )}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Checks({ ex }: { ex: InvoiceExtraction }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {ex.checks.map((c) => (
        <li key={c.name} className="flex gap-2">
          <Tick ok={c.passed} />
          <span>
            <span className="text-text">{CHECK_LABELS[c.name] ?? c.name}</span>
            {!c.passed && <span className="block text-xs text-muted">{c.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Lines({ run, setFocus }: { run: InvoiceRun; setFocus: (k: string | null) => void }) {
  const ex = run.extraction;
  const cmp = run.comparison;
  return (
    <div
      tabIndex={0}
      role="group"
      aria-label="Line items"
      className="max-h-[28rem] overflow-auto rounded-sm ring-1 ring-inset ring-line focus-visible:outline-2 focus-visible:outline-link"
    >
      <table className="w-full min-w-[560px] text-sm">
        <caption className="sr-only">Line items read from the invoice</caption>
        <thead className="sticky top-0 bg-surface text-xs text-faint">
          <tr className="border-b border-line">
            <th scope="col" className="w-8 py-2 pl-3 text-left font-medium">
              #
            </th>
            {LINE_FIELDS.map((f) => (
              <th
                key={f}
                scope="col"
                className={`py-2 pr-3 font-medium ${f === "description" || f === "stock_code" ? "text-left" : "text-right"}`}
              >
                {ROLE_LABELS[f === "stock_code" ? "code" : f]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ex.lines.map((line, i) => {
            const verdict = lineVerdict(i, cmp);
            return (
              <tr
                key={i}
                className="border-b border-line/60 align-top"
                onMouseEnter={() => setFocus(`line-${i}`)}
                onMouseLeave={() => setFocus(null)}
              >
                <td className="num py-1.5 pl-3 text-xs text-faint">
                  {i + 1}
                  {verdict === "wrong" && (
                    <span className="sr-only"> (differs from the record)</span>
                  )}
                </td>
                {LINE_FIELDS.map((f) => {
                  const expected = expectedCell(i, f, cmp);
                  const value = line[f];
                  return (
                    <td
                      key={f}
                      className={`py-1.5 pr-3 ${f === "description" || f === "stock_code" ? "" : "num text-right"} ${
                        expected !== null ? "text-fail" : "text-text"
                      }`}
                    >
                      {value === null || value === undefined ? "–" : String(value)}
                      {expected !== null && (
                        <span className="block text-xs text-muted">record: {expected}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {cmp?.missing.map((m, k) => (
            <tr key={`missing-${k}`} className="border-b border-line/60 text-fail">
              <td className="py-1.5 pl-3 text-xs">–</td>
              <td colSpan={5} className="py-1.5 pr-3 text-sm">
                Not read: {String(m.stock_code)} {String(m.description)} × {String(m.quantity)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Result({ run }: { run: InvoiceRun }) {
  const [focus, setFocus] = useState<string | null>(null);
  const ex = run.extraction;
  const all = useMemo(() => marks(ex, run.comparison), [ex, run.comparison]);
  const verdict = runVerdict(ex, run.comparison);
  const summary = {
    document_type: ex.document_type,
    number: ex.fields.number?.value ?? null,
    date: typeof ex.fields.date?.value === "string" ? ex.fields.date.value.slice(0, 10) : null,
    customer_id: ex.fields.customer?.value ?? null,
    country: ex.fields.country?.value ?? null,
    total: ex.total.value,
    lines: ex.lines.map(({ stock_code, description, quantity, unit_price, amount }) => ({
      stock_code,
      description,
      quantity,
      unit_price,
      amount,
    })),
    needs_review: ex.needs_review,
  };
  const t = run.timings;
  const scanned = run.pages.some((p) => p.method === "ocr");
  return (
    <div className="space-y-5 rounded-sm bg-surface p-4 ring-1 ring-inset ring-line sm:p-6">
      <div className="flex flex-wrap items-start gap-3">
        <Pill tone={verdict.tone}>{verdict.title}</Pill>
        <p className="min-w-0 flex-1 text-sm text-muted">{verdict.detail}</p>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
        <div className="space-y-2">
          <div
            tabIndex={0}
            role="group"
            aria-label="Invoice pages"
            className="max-h-[36rem] space-y-3 overflow-auto pr-1 focus-visible:outline-2 focus-visible:outline-link"
          >
            {run.pages.map((p) => (
              <PageView
                key={p.number}
                page={p}
                pageMarks={all.filter((m) => m.box.page === p.number)}
                focus={focus}
                setFocus={setFocus}
              />
            ))}
          </div>
          <p className="text-xs text-faint">
            Boxes show where each value was read
            {run.comparison ? "; green matches the record, red does not" : ""}. Hover a value to
            find it.
          </p>
        </div>
        <div className="space-y-5">
          <Fields run={run} setFocus={setFocus} />
          <div>
            <p className="mb-2 text-sm font-medium text-text">Checks</p>
            <Checks ex={ex} />
          </div>
        </div>
      </div>
      <div>
        <p className="mb-2 text-sm font-medium text-text">
          {formatInt(ex.lines.length)} line item{ex.lines.length === 1 ? "" : "s"}
        </p>
        <Lines run={run} setFocus={setFocus} />
      </div>
      <details className="group">
        <summary className="cursor-pointer list-none text-sm text-muted hover:text-text">
          <span
            aria-hidden
            className="mr-1.5 inline-block transition-transform group-open:rotate-90"
          >
            ›
          </span>
          How the table was read
        </summary>
        <div className="mt-3 space-y-2 text-sm text-muted">
          <ul className="flex flex-wrap gap-2">
            {ex.columns.map((c, i) => (
              <li key={i} className="rounded-sm px-2 py-1 ring-1 ring-inset ring-line">
                <span className="text-text">“{c.header}”</span> →{" "}
                {c.role ? ROLE_LABELS[c.role] : "not used"}
                {c.by === "content" && <span className="text-faint"> (from its content)</span>}
              </li>
            ))}
          </ul>
          {ex.notes.length > 0 && (
            <ul className="list-disc space-y-1 pl-5">
              {ex.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      </details>
      <details className="group">
        <summary className="cursor-pointer list-none text-sm text-muted hover:text-text">
          <span
            aria-hidden
            className="mr-1.5 inline-block transition-transform group-open:rotate-90"
          >
            ›
          </span>
          Structured output (JSON)
        </summary>
        <pre className="mt-3 max-h-80 overflow-auto rounded-sm bg-ink p-3 font-mono text-xs leading-relaxed text-muted ring-1 ring-line">
          {JSON.stringify(summary, null, 2)}
        </pre>
      </details>
      <p className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-faint">
        {t.render_ms !== undefined && t.render_ms >= 5 && (
          <span>Generated: {duration(t.render_ms)}</span>
        )}
        {t.wait_ms !== undefined && t.wait_ms > 50 && <span>Waited: {duration(t.wait_ms)}</span>}
        <span>
          Read{scanned ? " with OCR" : ""}: {duration(t.read_ms ?? 0)}
        </span>
        <span>Extracted: {duration(t.extract_ms ?? 0)}</span>
        <span>
          {formatInt(run.pages.length)} of {formatInt(run.page_count)} page
          {run.page_count === 1 ? "" : "s"}
        </span>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ demo */
function InvoiceInner() {
  const [source, setSource] = useState<Source>("sample");
  const [selected, setSelected] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const gallery = useInvoiceGallery();
  const run = useInvoiceRun();
  const upload = useInvoiceUpload();

  const active = source === "sample" ? run : upload;
  const result = active.data;
  const busy = run.isPending || upload.isPending;

  const onFile = (file: File) => {
    setFileError(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setFileError(`This file is ${fileSize(file.size)}; PDFs can be up to 10 MB.`);
      return;
    }
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      setFileError("Only PDF files can be read.");
      return;
    }
    upload.mutate(file);
  };

  return (
    <div className="space-y-6">
      <fieldset>
        <legend className="text-sm font-semibold text-text">Invoice to read</legend>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {(
            [
              ["sample", "A sample invoice", "Real retail records, drawn in many layouts"],
              ["upload", "Your invoice PDF", "Read once and not stored"],
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
                name="invoice-source"
                value={value}
                checked={source === value}
                onChange={() => setSource(value)}
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

      {source === "sample" ? (
        gallery.isError ? (
          <p className="text-sm text-fail">{docsErrorMessage(gallery.error)}</p>
        ) : gallery.data ? (
          gallery.data.documents.length > 0 ? (
            <Picker
              docs={gallery.data.documents}
              busy={busy}
              selected={selected}
              onRead={(id) => {
                setSelected(id);
                run.mutate(id);
              }}
            />
          ) : (
            <p className="text-sm text-muted">The sample invoices are not installed here.</p>
          )
        ) : (
          <p className="text-sm text-muted">Loading the sample invoices…</p>
        )
      ) : (
        <UploadBox busy={upload.isPending} onFile={onFile} />
      )}

      <section aria-live="polite" aria-label="Extraction result" className="min-h-6 space-y-3">
        {fileError && source === "upload" && <p className="text-sm text-fail">{fileError}</p>}
        {active.isPending && (
          <p role="status" className="text-sm text-muted">
            Reading the invoice… a scanned page takes a few seconds of OCR.
          </p>
        )}
        {active.isError && <p className="text-sm text-fail">{docsErrorMessage(active.error)}</p>}
        {result && !active.isPending && (
          <>
            {result.source === "upload" && result.filename && (
              <p className="text-sm text-muted">
                Read <span className="text-text">{result.filename}</span>
              </p>
            )}
            <Result key={`${result.document?.id ?? result.filename}`} run={result} />
          </>
        )}
      </section>
    </div>
  );
}

export function InvoiceDemo() {
  return (
    <QueryProvider>
      <InvoiceInner />
    </QueryProvider>
  );
}
