"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api, ApiError, unwrap } from "@/lib/api/client";
import type { BenchRegistry, BenchSample, BenchTry, Problem } from "@/lib/api/types";

export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

async function send(url: string, init: RequestInit): Promise<BenchTry> {
  let res: Response;
  try {
    res = await fetch(url, { method: "POST", ...init });
  } catch {
    throw new ApiError({ status: 0 });
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Problem> & Partial<BenchTry>;
  if (!res.ok) {
    const retry = Number(res.headers.get("retry-after"));
    throw new ApiError(
      { ...body, status: res.status },
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return body as BenchTry;
}

export type TryRequest =
  { kind: "sample"; name: string; model: string } | { kind: "upload"; file: File; model: string };

export function tryPhoto(req: TryRequest): Promise<BenchTry> {
  if (req.kind === "sample") {
    const q = new URLSearchParams({ model: req.model });
    return send(`/api/bench/try/samples/${encodeURIComponent(req.name)}?${q}`, {});
  }
  const form = new FormData();
  form.append("file", req.file, req.file.name);
  form.append("model", req.model);
  return send("/api/bench/try", { body: form });
}

export function useTry() {
  return useMutation({ mutationFn: tryPhoto });
}

export function useRegistry(initial?: BenchRegistry) {
  return useQuery({
    queryKey: ["bench", "registry"],
    initialData: initial,
    queryFn: async () => unwrap(await api.GET("/api/bench/registry")),
    staleTime: 5 * 60_000,
  });
}

export function useSamples(initial?: BenchSample[]) {
  return useQuery({
    queryKey: ["bench", "samples"],
    initialData: initial,
    queryFn: async () => unwrap(await api.GET("/api/bench/samples")),
    staleTime: 5 * 60_000,
  });
}
