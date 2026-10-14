"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api, ApiError, unwrap } from "@/lib/api/client";
import type {
  DocumentAnswer,
  DocumentInfo,
  DocumentQuestion,
  InvoiceRun,
  Problem,
} from "@/lib/api/types";

import { isProcessing } from "./format";

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const notFound = (error: unknown) =>
  error instanceof ApiError && (error.status === 404 || error.status === 403);

export function useSample(initial?: DocumentInfo) {
  return useQuery({
    queryKey: ["docs", "sample"],
    initialData: initial,
    queryFn: async () => unwrap(await api.GET("/api/documents/sample")),
    staleTime: 5 * 60_000,
  });
}

/** One uploaded document; polls while it is being read. */
export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ["docs", "document", id],
    enabled: id !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/documents/{document_id}", {
          params: { path: { document_id: id! } },
        }),
      ),
    refetchInterval: (q) => (q.state.data && isProcessing(q.state.data.status) ? 700 : false),
    retry: (count, error) => !notFound(error) && count < 2,
  });
}

export function useChunks(id: string | null, offset: number, enabled: boolean) {
  return useQuery({
    queryKey: ["docs", "chunks", id, offset],
    enabled: enabled && id !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/documents/{document_id}/chunks", {
          params: { path: { document_id: id! }, query: { offset, limit: 10 } },
        }),
      ),
    staleTime: Infinity,
  });
}

/** Multipart upload; openapi-fetch's JSON client is not used for the file body. */
async function uploadFile(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file, file.name);
  let res: Response;
  try {
    res = await fetch("/api/documents/uploads", { method: "POST", body: form });
  } catch {
    throw new ApiError({ status: 0 });
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Problem> & Partial<DocumentInfo>;
  if (!res.ok) {
    const retry = Number(res.headers.get("retry-after"));
    throw new ApiError(
      { ...body, status: res.status },
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return body as DocumentInfo;
}

export function useUpload() {
  return useMutation({ mutationFn: uploadFile });
}

export function useAsk() {
  return useMutation({
    // openapi-fetch widens the passages' [start, end] tuples to number[][]; the API
    // contract (schema.d.ts) is the tuple form.
    mutationFn: async ({ id, body }: { id: string; body: DocumentQuestion }) =>
      unwrap(
        await api.POST("/api/documents/{document_id}/ask", {
          params: { path: { document_id: id } },
          body,
        }),
      ) as DocumentAnswer,
  });
}

export function useDelete() {
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await api.DELETE("/api/documents/{document_id}", {
        params: { path: { document_id: id } },
      });
      if (!res.response.ok) unwrap(res as never);
      return id;
    },
  });
}

/* ------------------------------------------------------------------ invoices */
export function useInvoiceGallery() {
  return useQuery({
    queryKey: ["docs", "invoices"],
    queryFn: async () => unwrap(await api.GET("/api/documents/invoices")),
    staleTime: 5 * 60_000,
  });
}

/** Read a sample invoice now (render, isolated reader, extraction, comparison). */
export function useInvoiceRun() {
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/documents/invoices/{doc_id}/extract", {
          params: { path: { doc_id: id } },
        }),
      ),
  });
}

async function uploadInvoice(file: File): Promise<InvoiceRun> {
  const form = new FormData();
  form.append("file", file, file.name);
  let res: Response;
  try {
    res = await fetch("/api/documents/invoices/uploads", { method: "POST", body: form });
  } catch {
    throw new ApiError({ status: 0 });
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Problem> & Partial<InvoiceRun>;
  if (!res.ok) {
    const retry = Number(res.headers.get("retry-after"));
    throw new ApiError(
      { ...body, status: res.status },
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return body as InvoiceRun;
}

export function useInvoiceUpload() {
  return useMutation({ mutationFn: uploadInvoice });
}
