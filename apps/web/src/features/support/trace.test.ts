import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { ConversationStep } from "@/lib/api/types";

import { supportErrorMessage } from "./messages";
import { fallbackSentence, toolSummary } from "./trace";

function step(name: string, result: unknown, ok = true): ConversationStep {
  return {
    seq: 1,
    turn: 1,
    kind: "tool",
    name,
    provider: null,
    model: null,
    arguments: {},
    result,
    ok,
    prompt_tokens: 0,
    completion_tokens: 0,
    latency_ms: 0,
    note: null,
  };
}

describe("toolSummary", () => {
  it("summarises each tool's result in one line", () => {
    expect(toolSummary(step("get_invoice", { products: [1, 2], total_gbp: 530.16 }))).toBe(
      "2 products, total £530.16",
    );
    expect(
      toolSummary(
        step("calculate_refund", {
          eligible: true,
          amount_gbp: 85.92,
          refund_on_return: false,
          approval_needed: "supervisor approval",
        }),
      ),
    ).toBe("eligible: £85.92, supervisor approval");
    expect(toolSummary(step("calculate_refund", { eligible: false }))).toBe("not eligible");
    expect(
      toolSummary(
        step("get_shipment_status", {
          status: "in_transit",
          estimated_delivery: "2011-12-12",
          delivered_on: null,
        }),
      ),
    ).toBe("in transit, due 2011-12-12 (simulated)");
    expect(
      toolSummary(step("get_invoice", { error: "No invoice 1 on this account." }, false)),
    ).toBe("No invoice 1 on this account.");
  });
});

describe("fallbackSentence", () => {
  it("names skipped providers in words", () => {
    expect(fallbackSentence("fell back after groq: not_configured, cerebras: rate_limited")).toBe(
      "Skipped groq (not configured), cerebras (rate limited), so the next provider answered.",
    );
  });
});

describe("supportErrorMessage", () => {
  it("explains quota and approval states", () => {
    expect(
      supportErrorMessage(new ApiError({ status: 429, code: "quota_exceeded" }, 120)),
    ).toContain("2 minutes");
    expect(supportErrorMessage(new ApiError({ status: 409, code: "awaiting_approval" }))).toContain(
      "Approve or reject",
    );
    expect(supportErrorMessage(new TypeError("fetch failed"))).toContain("did not reach");
  });
});
