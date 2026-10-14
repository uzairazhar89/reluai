import type {
  InvoiceBox,
  InvoiceComparison,
  InvoiceEvaluation,
  InvoiceExtraction,
  InvoicePage,
} from "@/lib/api/types";

export const FIELD_LABELS: Record<string, string> = {
  number: "Invoice number",
  date: "Date",
  customer: "Customer ID",
  country: "Country",
  document_type: "Document type",
  total: "Total",
};

export const CHECK_LABELS: Record<string, string> = {
  line_arithmetic: "Quantity × unit price = amount on every line",
  total_matches_lines: "The lines add up to the total",
  item_count: "The number of lines matches the invoice",
  header_complete: "Invoice number and date found",
  sign: "The total’s sign fits the document type",
};

export const ROLE_LABELS: Record<string, string> = {
  code: "Stock code",
  description: "Description",
  quantity: "Quantity",
  unit_price: "Unit price",
  amount: "Amount",
};

export const LINE_FIELDS = [
  "stock_code",
  "description",
  "quantity",
  "unit_price",
  "amount",
] as const;
export type LineField = (typeof LINE_FIELDS)[number];

/** How a value is shown: dates without the time, document types in words. */
export function showValue(name: string, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "–";
  if (name === "document_type") return value === "credit_note" ? "Credit note" : "Invoice";
  if (name === "date" && typeof value === "string") return value.slice(0, 10);
  return String(value);
}

/** Position of a box on its page, as CSS percentages. */
export function boxStyle(box: InvoiceBox, page: Pick<InvoicePage, "width" | "height">) {
  const pad = 1.5;
  const pct = (v: number, of: number) => `${Math.max(0, (v / of) * 100).toFixed(3)}%`;
  return {
    left: pct(box.x0 - pad, page.width),
    top: pct(box.top - pad, page.height),
    width: pct(box.x1 - box.x0 + 2 * pad, page.width),
    height: pct(box.bottom - box.top + 2 * pad, page.height),
  };
}

export type Verdict = "right" | "wrong" | "unchecked";

export interface Mark {
  key: string;
  label: string;
  box: InvoiceBox;
  verdict: Verdict;
}

/** Every value that has a source box, with its verdict against the record (if any). */
export function marks(ex: InvoiceExtraction, cmp: InvoiceComparison | null | undefined): Mark[] {
  const out: Mark[] = [];
  for (const [name, field] of Object.entries(ex.fields)) {
    if (!field.box) continue;
    const ok = cmp?.header[name]?.correct;
    out.push({
      key: name,
      label: FIELD_LABELS[name] ?? name,
      box: field.box,
      verdict: ok === undefined ? "unchecked" : ok ? "right" : "wrong",
    });
  }
  if (ex.total.box) {
    const ok = cmp?.header.total?.correct;
    out.push({
      key: "total",
      label: "Total",
      box: ex.total.box,
      verdict: ok === undefined ? "unchecked" : ok ? "right" : "wrong",
    });
  }
  ex.lines.forEach((line, i) => {
    if (!line.box) return;
    out.push({
      key: `line-${i}`,
      label: `Line ${i + 1}`,
      box: line.box,
      verdict: lineVerdict(i, cmp),
    });
  });
  return out;
}

/** A read line is right when it pairs with a record line and all five values match. */
export function lineVerdict(index: number, cmp: InvoiceComparison | null | undefined): Verdict {
  if (!cmp) return "unchecked";
  const pair = cmp.lines.find((l) => l.read === index);
  if (!pair) return "wrong";
  return Object.values(pair.fields).every(Boolean) ? "right" : "wrong";
}

/** The record's value for one cell of a read line, when it differs. */
export function expectedCell(
  index: number,
  field: LineField,
  cmp: InvoiceComparison | null | undefined,
): string | null {
  const pair = cmp?.lines.find((l) => l.read === index);
  if (!pair || pair.fields[field] !== false) return null;
  const value = pair.expected[field];
  return value === undefined ? null : String(value);
}

/** The headline for a run: what a person processing invoices would need to know. */
export function runVerdict(
  ex: InvoiceExtraction,
  cmp: InvoiceComparison | null | undefined,
): { tone: "pass" | "warn" | "fail"; title: string; detail: string } {
  const failed = ex.checks.filter((c) => !c.passed).length;
  if (cmp) {
    if (cmp.exact && !ex.needs_review)
      return {
        tone: "pass",
        title: "Read exactly",
        detail:
          "Every value matches the record the invoice was drawn from, and every check passed.",
      };
    if (ex.needs_review)
      return {
        tone: "warn",
        title: "Flagged for review",
        detail: `${failed} check${failed === 1 ? "" : "s"} failed, so this result would go to a person instead of being used as read.`,
      };
    return {
      tone: "fail",
      title: "Wrong, and not flagged",
      detail:
        "Some values differ from the record although every check passed: the case the checks cannot catch.",
    };
  }
  return ex.needs_review
    ? {
        tone: "warn",
        title: "Needs review",
        detail: `${failed} check${failed === 1 ? "" : "s"} failed; a person should look at this invoice.`,
      }
    : {
        tone: "pass",
        title: "Checks passed",
        detail:
          "The lines multiply out and add up to the total. There is no record to compare with.",
      };
}

export interface GroupSummary {
  documents: number;
  exact: number | null;
  lines_exact: number | null;
  flagged: number | null;
  caught: number | null;
  silently_wrong: number;
  wrong: number;
  median_ms: number;
  p95_ms: number;
}

export const RESULT_GROUPS = [
  ["dev.text", "Development layouts, PDF"],
  ["dev.scan", "Development layouts, scanned"],
  ["held_out.text", "New layouts, PDF"],
  ["held_out.scan", "New layouts, scanned"],
] as const;

/** The per-group figures of an evaluation run, in display order. */
export function resultRows(run: InvoiceEvaluation): (readonly [string, string, GroupSummary])[] {
  return RESULT_GROUPS.flatMap(([key, label]) => {
    const g = run.metrics[key] as GroupSummary | undefined;
    return g ? [[key, label, g] as const] : [];
  });
}

/** Seconds for slow steps, milliseconds for fast ones. */
export function duration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
