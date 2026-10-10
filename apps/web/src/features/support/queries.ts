"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { SupportCatalogue } from "@/lib/api/types";

export function useCatalogue(initial?: SupportCatalogue) {
  return useQuery({
    queryKey: ["support", "catalogue"],
    initialData: initial,
    queryFn: async () => unwrap(await api.GET("/api/support/catalogue")),
    staleTime: 10 * 60_000,
  });
}

export type StartInput = { scenario_id: string } | { customer_id: number; message: string };

export function useStart() {
  return useMutation({
    mutationFn: async (body: StartInput) =>
      unwrap(await api.POST("/api/support/conversations", { body })),
  });
}

export function useReply() {
  return useMutation({
    mutationFn: async ({ id, message }: { id: string; message: string }) =>
      unwrap(
        await api.POST("/api/support/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: id } },
          body: { message },
        }),
      ),
  });
}

export function useDecide() {
  return useMutation({
    mutationFn: async ({
      id,
      decision,
      note,
    }: {
      id: string;
      decision: "approve" | "reject";
      note?: string;
    }) =>
      unwrap(
        await api.POST("/api/support/conversations/{conversation_id}/approval", {
          params: { path: { conversation_id: id } },
          body: { decision, note: note || null },
        }),
      ),
  });
}
