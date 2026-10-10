import type { ResultColumn } from "@/lib/api/types";

export type Grain = "day" | "week" | "month" | "quarter" | "year";

const intFmt = new Intl.NumberFormat("en-GB");
const numFmt = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "2010-03-01" as the period it starts: "Mar 2010", "Q1 2010", "2010" or "1 Mar 2010". */
export function formatPeriod(iso: string, grain: Grain | null | undefined): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(Date.UTC(y, m - 1, d));
  if (grain === "year") return String(y);
  if (grain === "quarter") return `Q${Math.floor((m - 1) / 3) + 1} ${y}`;
  if (grain === "month") {
    return new Intl.DateTimeFormat("en-GB", {
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(date);
  }
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** A result cell as text for the table and chart labels. */
export function formatCell(
  value: unknown,
  column: Pick<ResultColumn, "kind" | "role">,
  grain?: Grain | null,
): string {
  if (value === null || value === undefined) return "(missing)";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    // Measures of a decimal column keep 2 decimals throughout, so a column of amounts lines up.
    return column.kind === "number" ? numFmt.format(value) : intFmt.format(value);
  }
  const text = String(value);
  if (column.role === "time") return formatPeriod(text, grain);
  return text;
}

/** Characters that make a spreadsheet treat a cell as a formula (OWASP CSV injection). */
const FORMULA_START = /^[=+\-@\t\r]/;

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "string" ? value : String(value);
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * The answer as a CSV file. Text cells that a spreadsheet would run as formulas get a leading
 * apostrophe, so opening the download in Excel never executes anything from the data.
 */
export function toCsv(columns: Pick<ResultColumn, "label">[], rows: unknown[][]): string {
  const lines = [columns.map((c) => csvCell(c.label)).join(",")];
  for (const row of rows) lines.push(row.map(csvCell).join(","));
  return lines.join("\r\n") + "\r\n";
}
