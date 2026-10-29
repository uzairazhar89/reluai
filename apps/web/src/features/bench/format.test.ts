import { describe, expect, it } from "vitest";

import {
  agreementTone,
  flagLabel,
  hasInt8DotProduct,
  megabytes,
  ms,
  phases,
  speedup,
  startup,
  threadsLabel,
} from "./format";

const stats = (p50: number) => ({ p50, p95: p50 * 2, mean: p50, min: p50 / 2 });

describe("bench formatting", () => {
  it("formats durations with sensible precision", () => {
    expect(ms(0.842)).toBe("0.84 ms");
    expect(ms(8.712)).toBe("8.71 ms");
    expect(ms(54.33)).toBe("54.3 ms");
    expect(ms(1234.4)).toBe("1,234 ms");
    expect(ms(Number.NaN)).toBe("–");
    expect(startup(2487.4)).toBe("2.5 s");
    expect(startup(32.9)).toBe("32.9 ms");
  });

  it("formats sizes", () => {
    expect(megabytes(3_401_141)).toBe("3.4 MB");
    expect(megabytes(46_812_648)).toBe("47 MB");
  });

  it("compares speeds both ways", () => {
    expect(speedup(26.36, 8.36)).toBe("3.2× faster");
    expect(speedup(1.71, 1.95)).toBe("1.1× slower");
    expect(speedup(10, 10.2)).toBe("about the same");
    expect(speedup(0, 1)).toBe("–");
  });

  it("grades agreement with PyTorch", () => {
    expect(agreementTone(100)).toBe("pass");
    expect(agreementTone(95.5)).toBe("warn");
    expect(agreementTone(12.5)).toBe("fail");
  });

  it("splits latency into its phases", () => {
    const p = phases({
      total: stats(9),
      preprocess: stats(6),
      inference: stats(2.5),
      postprocess: stats(0.2),
    });
    expect(p.sum).toBeCloseTo(8.7);
    expect(p.pre).toBe(6);
  });

  it("names CPU features", () => {
    expect(flagLabel("avx512_vnni")).toBe("AVX-512 VNNI");
    expect(flagLabel("neon")).toBe("NEON");
    expect(hasInt8DotProduct(["avx2", "fma"])).toBe(false);
    expect(hasInt8DotProduct(["avx2", "avx_vnni"])).toBe(true);
    expect(threadsLabel(1)).toBe("1 thread");
    expect(threadsLabel(2)).toBe("2 threads");
  });
});
