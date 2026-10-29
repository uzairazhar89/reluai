import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BenchRegistry, BenchRun } from "@/lib/api/types";

import registryJson from "../../../e2e/fixtures/bench-registry.json";
import runJson from "../../../e2e/fixtures/bench-run.json";

import { BenchResults } from "./results";

const registry = registryJson as unknown as BenchRegistry;
const run = runJson as unknown as BenchRun;
const threads = run.protocol.threads as number[];

describe("BenchResults", () => {
  it("shows the hardware and a table per model, from a recorded run", () => {
    render(<BenchResults run={run} registry={registry} />);
    expect(screen.getByText(run.hardware.cpu.model)).toBeInTheDocument();
    expect(screen.getByText("AVX-512 VNNI")).toBeInTheDocument();
    for (const model of registry.models) {
      const table = screen.getByRole("table", { name: `${model.title}: measurements per variant` });
      // One row per variant and thread count, plus the header.
      expect(within(table).getAllByRole("row")).toHaveLength(1 + 3 * threads.length);
      expect(within(table).getAllByText("reference")).toHaveLength(threads.length);
    }
  });

  it("explains each comparison in words computed from the numbers", () => {
    render(<BenchResults run={run} registry={registry} />);
    expect(screen.getAllByText(/Exported to ONNX, the same 32-bit model ran/)).toHaveLength(2);
    expect(screen.getAllByText(/In 8 bits it ran/)).toHaveLength(2);
    expect(screen.getByText(/about as fast as/)).toBeInTheDocument(); // MobileNetV3 in the fixture
    expect(screen.getAllByText(/8-bit conversion\./)).toHaveLength(2);
    expect(screen.getAllByText(/as published by timm/, { selector: "span" })).toHaveLength(2);
  });
});
