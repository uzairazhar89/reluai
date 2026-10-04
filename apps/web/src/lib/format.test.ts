import {
  formatDropKey,
  formatDuration,
  formatInt,
  formatPct,
  formatRelative,
  formatScore,
} from "./format";

describe("formatInt", () => {
  it("groups thousands the British way", () => {
    expect(formatInt(1067371)).toBe("1,067,371");
  });
  it("shows a dash for missing values", () => {
    expect(formatInt(null)).toBe("–");
    expect(formatInt(undefined)).toBe("–");
  });
});

describe("formatPct", () => {
  it("formats ratios", () => {
    expect(formatPct(0.0069)).toBe("0.7%");
    expect(formatPct(0.006876, 2)).toBe("0.69%");
  });
  it("handles missing and NaN", () => {
    expect(formatPct(null)).toBe("–");
    expect(formatPct(Number.NaN)).toBe("–");
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0 ms"],
    [769, "769 ms"],
    [2376, "2.38 s"],
    [12_500, "12.5 s"],
    [125_000, "2 min 5 s"],
  ])("%d ms -> %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
  it("shows a dash for runs that have not finished", () => {
    expect(formatDuration(null)).toBe("–");
  });
});

describe("formatScore", () => {
  it("keeps one decimal", () => {
    expect(formatScore(90)).toBe("90.0");
    expect(formatScore(78.571)).toBe("78.6");
    expect(formatScore(null)).toBe("–");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-10-04T12:00:00Z");
  it.each([
    ["2026-10-04T11:59:40Z", "just now"],
    ["2026-10-04T11:57:00Z", "3 minutes ago"],
    ["2026-10-04T09:00:00Z", "3 hours ago"],
    ["2026-10-03T12:00:00Z", "yesterday"],
    ["2026-09-01T12:00:00Z", "1 Sept 2026"],
  ])("%s -> %s", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
  it("shows a dash without a timestamp", () => {
    expect(formatRelative(null, now)).toBe("–");
  });
});

describe("formatDropKey", () => {
  it("names the month", () => {
    expect(formatDropKey("2010-12")).toBe("December 2010");
  });
  it("passes through keys it cannot parse", () => {
    expect(formatDropKey("latest")).toBe("latest");
    expect(formatDropKey(null)).toBe("–");
  });
});
