"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api, ApiError, unwrap } from "@/lib/api/client";
import type { AskRequest, CsvDataset, Problem } from "@/lib/api/types";

export const BUNDLED = "retail";
export const MAX_UPLOAD_BYTES = 2_000_000;

export function useDataset(id: string, initial?: CsvDataset) {
  return useQuery({
    queryKey: ["csv", "dataset", id],
    initialData: id === BUNDLED ? initial : undefined,
    queryFn: async () =>
      id === BUNDLED
        ? unwrap(await api.GET("/api/csv/datasets/retail"))
        : unwrap(
            await api.GET("/api/csv/uploads/{upload_id}", {
              params: { path: { upload_id: id } },
            }),
          ),
    staleTime: id === BUNDLED ? 5 * 60_000 : Infinity,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
}

/** Multipart upload; openapi-fetch's JSON client is not used for the file body. */
async function uploadFile(file: File): Promise<CsvDataset> {
  const form = new FormData();
  form.append("file", file, file.name);
  let res: Response;
  try {
    res = await fetch("/api/csv/uploads", { method: "POST", body: form });
  } catch {
    throw new ApiError({ status: 0 });
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Problem> & Partial<CsvDataset>;
  if (!res.ok) {
    const retry = Number(res.headers.get("retry-after"));
    throw new ApiError(
      { ...body, status: res.status },
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return body as CsvDataset;
}

export function useUpload() {
  return useMutation({ mutationFn: uploadFile });
}

export function useAsk() {
  return useMutation({
    mutationFn: async (body: AskRequest) => unwrap(await api.POST("/api/csv/ask", { body })),
  });
}
