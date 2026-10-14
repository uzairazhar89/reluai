import type { InvoiceEvaluation, InvoiceEvaluationItem } from "@/lib/api/types";
import { formatDateTime, formatInt } from "@/lib/format";

import { duration, resultRows } from "./invoice-format";

function pct(n: number | null | undefined) {
  return n === null || n === undefined ? "–" : `${n.toFixed(1)}%`;
}

function problem(item: InvoiceEvaluationItem) {
  const first = item.mismatches[0] ?? "";
  return first.length > 140 ? `${first.slice(0, 140)}…` : first;
}

/** Invoice extraction accuracy from the latest run on the server, per layout group. */
export function InvoiceResults({ run }: { run: InvoiceEvaluation }) {
  const rows = resultRows(run);
  const wrong = run.results.filter((r) => !r.exact);
  return (
    <>
      <p>
        {formatInt(run.documents)} invoices from the real records, each read as a visitor&apos;s
        would be and compared with its record value by value: {formatInt(run.exact)} were read
        exactly. A document counts only if every header field, every line and the total are right.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-sm">
          <caption className="sr-only">Invoice extraction results per group</caption>
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 text-left font-medium">
                Invoices
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Read exactly
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Lines fully right
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Flagged for review
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Wrong, not flagged
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Median time
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, label, g]) => (
              <tr key={key} className="border-b border-line/60">
                <th scope="row" className="py-2 pr-3 text-left font-medium text-text">
                  {label}
                  <span className="block text-xs font-normal text-faint">
                    {formatInt(g.documents)} invoices
                  </span>
                </th>
                <td className="num py-2 pr-3 text-right text-text">{pct(g.exact)}</td>
                <td className="num py-2 pr-3 text-right">{pct(g.lines_exact)}</td>
                <td className="num py-2 pr-3 text-right">{pct(g.flagged)}</td>
                <td className="num py-2 pr-3 text-right">{formatInt(g.silently_wrong)}</td>
                <td className="num py-2 text-right">{duration(g.median_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        The extractor was developed against the first group&apos;s layouts and the scans of them, so
        those figures show it works rather than how well it generalises. The new layouts were drawn
        from seeds that were not looked at until the extractor was finished, and some use labels and
        column headings that are not in its vocabulary (&ldquo;Pcs&rdquo;, &ldquo;Net&rdquo;,
        &ldquo;Document ref.&rdquo;); those are read from the content instead. Times include
        starting the isolated reader; scans include OCR. Run {formatDateTime(run.ran_at)}.
      </p>
      {wrong.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer rounded-sm py-1 text-text hover:underline">
            The {wrong.length} invoice{wrong.length === 1 ? "" : "s"} not read exactly
          </summary>
          <ul className="mt-2 space-y-2.5 text-sm">
            {wrong.map((r) => (
              <li key={r.id} className="border-l-2 border-line pl-3">
                <span className="text-text">
                  {r.id.startsWith("C") ? "Credit note" : "Invoice"} {r.id.split("-")[0]}
                  {r.scanned ? ", scanned" : ""}, layout {r.style}
                </span>
                <span className="block text-muted">
                  {r.needs_review ? "Flagged for review" : "Not flagged"}. {problem(r)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
