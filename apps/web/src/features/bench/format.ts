import type { BenchAgreement, BenchLatency, BenchResult } from "@/lib/api/types";

/** Milliseconds with precision that suits the size: 0.84 ms, 8.7 ms, 54 ms, 1,234 ms. */
export function ms(value: number): string {
  if (!Number.isFinite(value)) return "–";
  if (value < 1) return `${value.toFixed(2)} ms`;
  if (value < 10) return `${value.toFixed(2)} ms`;
  if (value < 100) return `${value.toFixed(1)} ms`;
  return `${Math.round(value).toLocaleString("en-GB")} ms`;
}

/** Seconds for start-up times measured in milliseconds: 2.5 s, or 480 ms below one second. */
export function startup(valueMs: number): string {
  return valueMs >= 1000 ? `${(valueMs / 1000).toFixed(1)} s` : ms(valueMs);
}

export function megabytes(bytes: number): string {
  const mb = bytes / 1_000_000;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

export function memory(mb: number): string {
  return `${Math.round(mb).toLocaleString("en-GB")} MB`;
}

export function percent(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

/** How much faster ``value`` is than ``reference`` (both durations), e.g. "3.1× faster". */
export function speedup(reference: number, value: number): string {
  if (!(reference > 0) || !(value > 0)) return "–";
  const ratio = reference / value;
  if (ratio >= 1.05) return `${ratio.toFixed(1)}× faster`;
  if (ratio <= 0.95) return `${(1 / ratio).toFixed(1)}× slower`;
  return "about the same";
}

export type Tone = "pass" | "warn" | "fail";

/** Agreement with PyTorch on the top class: near-identical, noticeably off, or broken. */
export function agreementTone(top1: number): Tone {
  if (top1 >= 99) return "pass";
  if (top1 >= 90) return "warn";
  return "fail";
}

/** The three phases of one photo's latency at the median, for a stacked bar. */
export function phases(latency: BenchLatency) {
  const pre = latency.preprocess.p50;
  const inf = latency.inference.p50;
  const post = latency.postprocess.p50;
  return { pre, inf, post, sum: pre + inf + post };
}

export function resultsFor(results: BenchResult[], model: string): BenchResult[] {
  return results.filter((r) => r.model === model);
}

export function agreementFor(
  agreement: BenchAgreement[],
  model: string,
  variant: string,
): BenchAgreement | undefined {
  return agreement.find((a) => a.model === model && a.variant === variant);
}

const FLAGS: Record<string, string> = {
  sse4_2: "SSE4.2",
  avx: "AVX",
  avx2: "AVX2",
  fma: "FMA",
  f16c: "F16C",
  avx512f: "AVX-512",
  avx512bw: "AVX-512 BW",
  avx512vl: "AVX-512 VL",
  avx512_vnni: "AVX-512 VNNI",
  avx_vnni: "AVX-VNNI",
  avx512_bf16: "AVX-512 BF16",
  amx_tile: "AMX",
  amx_int8: "AMX INT8",
};

export function flagLabel(flag: string): string {
  return FLAGS[flag] ?? flag.toUpperCase();
}

/** Whether the CPU has a single instruction for 8-bit dot products (VNNI or AMX). */
export function hasInt8DotProduct(flags: string[]): boolean {
  return flags.some((f) => f === "avx512_vnni" || f === "avx_vnni" || f === "amx_int8");
}

export function threadsLabel(n: number): string {
  return n === 1 ? "1 thread" : `${n} threads`;
}
