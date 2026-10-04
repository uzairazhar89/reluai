import { ApiError } from "@/lib/api/client";

import { triggerErrorMessage } from "./run-trigger";

describe("triggerErrorMessage", () => {
  it("tells a visitor when their quota resets", () => {
    const msg = triggerErrorMessage(
      new ApiError({ status: 429, code: "quota_exceeded", detail: "limit" }, 1500),
    );
    expect(msg).toContain("3 runs per hour");
    expect(msg).toContain("25 minutes");
  });

  it("explains a full queue", () => {
    expect(triggerErrorMessage(new ApiError({ status: 429, code: "queue_full" }))).toMatch(
      /already waiting/,
    );
  });

  it("explains an unavailable queue", () => {
    expect(triggerErrorMessage(new ApiError({ status: 503, code: "queue_unavailable" }))).toMatch(
      /was not started/,
    );
  });

  it("covers nginx rate limiting, which has no problem body", () => {
    expect(triggerErrorMessage(new ApiError({ status: 429 }))).toMatch(/Too many requests/);
  });

  it("covers server errors and network failures", () => {
    expect(triggerErrorMessage(new ApiError({ status: 502 }))).toMatch(/not responding/);
    expect(triggerErrorMessage(new TypeError("Failed to fetch"))).toMatch(/did not reach/);
  });
});
