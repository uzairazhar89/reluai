import { describe, expect, it } from "vitest";

import type { InvoiceComparison, InvoiceEvaluation, InvoiceExtraction } from "@/lib/api/types";

import {
  boxStyle,
  duration,
  expectedCell,
  lineVerdict,
  marks,
  resultRows,
  runVerdict,
  showValue,
} from "./invoice-format";

const box = { page: 1, x0: 100, top: 200, x1: 150, bottom: 210 };
const field = (value: string | number | null, withBox = true) => ({
  value,
  text: value === null ? null : String(value),
  box: withBox ? box : null,
  label: "Label",
  by: "label" as const,
});

const extraction: InvoiceExtraction = {
  document_type: "invoice",
  fields: {
    number: field("536365"),
    date: field("2010-12-01T08:26"),
    customer: field(17850),
    country: field("United Kingdom", false),
  },
  total: field("15.30"),
  subtotal: null,
  item_count: null,
  lines: [
    {
      stock_code: "22752",
      description: "SET 7 BABUSHKA NESTING BOXES",
      quantity: 2,
      unit_price: "7.65",
      amount: "15.30",
      cells: {},
      box,
    },
  ],
  columns: [],
  checks: [{ name: "line_arithmetic", passed: true, detail: "ok" }],
  needs_review: false,
  notes: [],
};

const comparison: InvoiceComparison = {
  exact: false,
  header: {
    number: { read: "536365", record: "536365", correct: true },
    date: { read: "2010-12-01", record: "2010-12-01", correct: true },
    customer: { read: 17850, record: 17850, correct: true },
    country: { read: "United Kingdom", record: "United Kingdom", correct: true },
    document_type: { read: "invoice", record: "invoice", correct: true },
    total: { read: "15.30", record: "15.30", correct: true },
  },
  lines: [
    {
      read: 0,
      record: 0,
      fields: {
        stock_code: true,
        description: false,
        quantity: true,
        unit_price: true,
        amount: true,
      },
      expected: {
        stock_code: "22752",
        description: "SET 7 BABUSHKA NESTING BOXES",
        quantity: 2,
        unit_price: "7.65",
        amount: "15.30",
      },
    },
  ],
  missing: [],
  extra: [],
};

describe("invoice format", () => {
  it("shows values the way a reader expects", () => {
    expect(showValue("date", "2010-12-01T08:26")).toBe("2010-12-01");
    expect(showValue("document_type", "credit_note")).toBe("Credit note");
    expect(showValue("customer", null)).toBe("–");
  });

  it("places boxes as page percentages", () => {
    const s = boxStyle(box, { width: 200, height: 400 });
    expect(s.left).toBe("49.250%");
    expect(s.top).toBe("49.625%");
  });

  it("marks every boxed value with its verdict", () => {
    const m = marks(extraction, comparison);
    expect(m.map((x) => x.key)).toEqual(["number", "date", "customer", "total", "line-0"]);
    expect(m.find((x) => x.key === "line-0")?.verdict).toBe("wrong");
    expect(marks(extraction, null).every((x) => x.verdict === "unchecked")).toBe(true);
    expect(lineVerdict(3, comparison)).toBe("wrong");
  });

  it("shows the record's value only where a cell is wrong", () => {
    expect(expectedCell(0, "description", comparison)).toBe("SET 7 BABUSHKA NESTING BOXES");
    expect(expectedCell(0, "amount", comparison)).toBeNull();
  });

  it("separates flagged results from silent errors", () => {
    expect(runVerdict(extraction, comparison).title).toBe("Wrong, and not flagged");
    expect(runVerdict({ ...extraction, needs_review: true }, comparison).tone).toBe("warn");
    expect(runVerdict(extraction, { ...comparison, exact: true }).title).toBe("Read exactly");
    expect(runVerdict(extraction, null).title).toBe("Checks passed");
  });

  it("orders result groups and formats durations", () => {
    const g = {
      documents: 1,
      exact: 100,
      lines_exact: 100,
      flagged: 0,
      caught: null,
      silently_wrong: 0,
      wrong: 0,
      median_ms: 120,
      p95_ms: 150,
    };
    const run = {
      metrics: { "held_out.scan": g, "dev.text": g, all: g },
    } as unknown as InvoiceEvaluation;
    expect(resultRows(run).map(([k]) => k)).toEqual(["dev.text", "held_out.scan"]);
    expect(duration(120)).toBe("120 ms");
    expect(duration(4870)).toBe("4.9 s");
  });
});
