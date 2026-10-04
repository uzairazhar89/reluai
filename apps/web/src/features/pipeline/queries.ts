"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Run, RunDetail, Summary } from "@/lib/api/types";

const ACTIVE = new Set(["queued", "running"]);

/** `initial` is the server-rendered snapshot, so the dashboard paints with data, not spinners. */
export function useSummary(initial?: Summary) {
  return useQuery({
    queryKey: ["pipeline", "summary"],
    initialData: initial,
    queryFn: async () => unwrap(await api.GET("/api/pipeline/summary")),
    refetchInterval: (q) => ((q.state.data?.pending_runs ?? 0) > 0 ? 4000 : 30_000),
  });
}

export function useRuns(initial?: Run[]) {
  return useQuery({
    queryKey: ["pipeline", "runs"],
    initialData: initial,
    queryFn: async () =>
      unwrap(await api.GET("/api/pipeline/runs", { params: { query: { limit: 25 } } })),
    refetchInterval: (q) => (q.state.data?.some((r) => ACTIVE.has(r.status)) ? 4000 : 30_000),
  });
}

export function useScenarios() {
  return useQuery({
    queryKey: ["pipeline", "scenarios"],
    queryFn: async () => unwrap(await api.GET("/api/pipeline/scenarios")),
    staleTime: Infinity,
  });
}

export function useRunDetail(runId: string | null) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["pipeline", "run", runId],
    enabled: runId !== null,
    queryFn: async (): Promise<RunDetail> => {
      const detail = unwrap(
        await api.GET("/api/pipeline/runs/{run_id}", { params: { path: { run_id: runId! } } }),
      );
      if (!ACTIVE.has(detail.run.status)) {
        void qc.invalidateQueries({ queryKey: ["pipeline", "summary"] });
        void qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
      }
      return detail;
    },
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.run.status) ? 1500 : false),
  });
}

export function useQuarantine(runId: string, reason: string | null) {
  return useQuery({
    queryKey: ["pipeline", "quarantine", runId, reason],
    enabled: reason !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/pipeline/runs/{run_id}/quarantine", {
          params: { path: { run_id: runId }, query: { reason: reason ?? undefined, limit: 10 } },
        }),
      ),
  });
}

export function useTriggerRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (scenario: string) =>
      unwrap(await api.POST("/api/pipeline/runs", { body: { scenario } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
      void qc.invalidateQueries({ queryKey: ["pipeline", "summary"] });
    },
  });
}

export const isActive = (status: string) => ACTIVE.has(status);
