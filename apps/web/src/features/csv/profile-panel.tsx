import type { CsvColumn, CsvDataset } from "@/lib/api/types";
import { formatInt, formatPct } from "@/lib/format";

const kindLabel: Record<string, string> = {
  integer: "Whole number",
  number: "Number",
  date: "Date",
  text: "Text",
  boolean: "Yes / no",
  other: "Other",
};

const numFmt = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

function shortNumber(text: string | null | undefined): string {
  if (text === null || text === undefined) return "–";
  const n = Number(text);
  return Number.isFinite(n) ? numFmt.format(n) : text;
}

function valuesSummary(c: CsvColumn): string {
  if (c.non_null === 0) return "Empty";
  if (c.kind === "date") return `${c.min ?? "–"} to ${c.max ?? "–"}`;
  if (c.kind === "integer" || c.kind === "number") {
    const range = `${shortNumber(c.min)} to ${shortNumber(c.max)}`;
    return c.mean === null || c.mean === undefined
      ? range
      : `${range}, average ${shortNumber(String(c.mean))}`;
  }
  const top = (c.top_values ?? []).slice(0, 3);
  if (top.length === 0) return "–";
  return top.map((t) => `${t.value} (${formatInt(t.count)})`).join(", ");
}

export function ProfilePanel({ dataset }: { dataset: CsvDataset }) {
  const warnings = dataset.findings.filter((f) => f.severity === "warning").length;
  return (
    <div className="space-y-6">
      <div>
        <h4 className="text-sm font-semibold text-text">
          Data-quality findings{" "}
          <span className="font-normal text-muted">
            (
            {dataset.findings.length === 0
              ? "none"
              : `${dataset.findings.length}, ${warnings} to check before trusting totals`}
            )
          </span>
        </h4>
        {dataset.findings.length === 0 ? (
          <p className="mt-2 text-sm text-muted">
            No duplicates, gaps or type problems were found in this table.
          </p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm">
            {dataset.findings.map((f, i) => (
              <li key={`${f.code}-${f.column ?? ""}-${i}`} className="flex gap-3">
                <span
                  aria-hidden
                  className={`mt-[0.45rem] size-2 shrink-0 rounded-full ${f.severity === "warning" ? "bg-warn" : "bg-faint"}`}
                />
                <span>
                  <span className="sr-only">
                    {f.severity === "warning" ? "Warning: " : "Note: "}
                  </span>
                  <span className="text-text">{f.message}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="text-sm font-semibold text-text">
          {dataset.columns.length} columns, {formatInt(dataset.rows)} rows
        </h4>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <caption className="sr-only">Columns of {dataset.title}</caption>
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Column
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Type
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  Missing
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  Distinct
                </th>
                <th scope="col" className="py-2 font-medium">
                  Values
                </th>
              </tr>
            </thead>
            <tbody>
              {dataset.columns.map((c) => (
                <tr key={c.name} className="border-b border-line/60 align-top">
                  <th scope="row" className="py-2 pr-3 font-normal">
                    <span className="font-mono text-[0.8125rem] text-text">{c.name}</span>
                    {c.description && (
                      <span className="block text-xs text-faint">{c.description}</span>
                    )}
                  </th>
                  <td className="py-2 pr-3 text-muted">{kindLabel[c.kind] ?? c.kind}</td>
                  <td
                    className={`num py-2 pr-3 text-right ${c.nulls > 0 ? "text-text" : "text-faint"}`}
                  >
                    {c.nulls === 0
                      ? "0"
                      : `${formatInt(c.nulls)} (${formatPct(c.nulls / dataset.rows)})`}
                  </td>
                  <td className="num py-2 pr-3 text-right text-muted">{formatInt(c.distinct)}</td>
                  <td className="max-w-[22rem] py-2 text-muted">{valuesSummary(c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
