import { describe, expect, it } from "vitest";

import { formatCell, formatPeriod, toCsv } from "./format";

describe("toCsv", () => {
  it("neutralises cells a spreadsheet would run as formulas", () => {
    const csv = toCsv(
      [{ label: "Product" }, { label: "Units" }],
      [
        ['=HYPERLINK("http://x")', 1],
        ["+cmd|' /C calc'!A0", 2],
        ["-2+3", -3],
        ["@SUM(A1:A2)", 4],
        ["Plain, with comma", 5],
      ],
    );
    const lines = csv.trimEnd().split("\r\n");
    expect(lines[0]).toBe("Product,Units");
    expect(lines[1]).toBe(`"'=HYPERLINK(""http://x"")",1`);
    expect(lines[2]).toBe("'+cmd|' /C calc'!A0,2");
    expect(lines[3]).toBe("'-2+3,-3"); // negative numbers stay numbers
    expect(lines[4]).toBe("'@SUM(A1:A2),4");
    expect(lines[5]).toBe('"Plain, with comma",5');
  });

  it("writes missing values as empty cells", () => {
    expect(toCsv([{ label: "a" }, { label: "b" }], [[null, "x"]])).toBe("a,b\r\n,x\r\n");
  });
});

describe("formatPeriod", () => {
  it.each([
    ["month", "Mar 2011"],
    ["quarter", "Q1 2011"],
    ["year", "2011"],
    ["day", "1 Mar 2011"],
    ["week", "1 Mar 2011"],
  ] as const)("%s", (grain, expected) => {
    expect(formatPeriod("2011-03-01", grain)).toBe(expected);
  });
});

describe("formatCell", () => {
  it("formats by kind", () => {
    expect(formatCell(1234567, { kind: "integer", role: "metric" })).toBe("1,234,567");
    expect(formatCell(1234.5678, { kind: "number", role: "metric" })).toBe("1,234.57");
    expect(formatCell(null, { kind: "text", role: "group" })).toBe("(missing)");
    expect(formatCell(true, { kind: "boolean", role: "group" })).toBe("Yes");
    expect(formatCell("2010-12-01", { kind: "date", role: "time" }, "month")).toBe("Dec 2010");
  });
});
