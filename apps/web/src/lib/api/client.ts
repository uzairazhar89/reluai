import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { Problem } from "./types";

/** Typed browser client for same-origin API calls (generated from the API's OpenAPI document). */
export const api = createClient<paths>({ baseUrl: "" });

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly retryAfter: number | undefined;

  constructor(problem: Problem, retryAfter?: number) {
    super(problem.detail ?? problem.title ?? `Request failed (${problem.status})`);
    this.status = problem.status;
    this.code = problem.code;
    this.retryAfter = retryAfter;
  }
}

/** Unwrap an openapi-fetch result, turning problem responses into ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined && result.response.ok) return result.data;
  const raw = (result.error ?? {}) as Partial<Problem>;
  const retry = Number(result.response.headers.get("retry-after"));
  throw new ApiError(
    { status: result.response.status, ...raw },
    Number.isFinite(retry) && retry > 0 ? retry : undefined,
  );
}
