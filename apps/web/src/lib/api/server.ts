import "server-only";

/**
 * Server-side reads from the API (inside the Docker network, or a local API in development).
 * Never throws: pages render an honest "offline" state when the API is unreachable, including
 * during `next build`, and pick up live data on the next revalidation.
 */
export type ServerResult<T> = { ok: true; data: T } | { ok: false; reason: string };

const apiOrigin = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function serverGet<T>(
  path: string,
  revalidateSeconds: number,
): Promise<ServerResult<T>> {
  try {
    const res = await fetch(`${apiOrigin}${path}`, {
      next: { revalidate: revalidateSeconds },
      signal: AbortSignal.timeout(2500),
      headers: { accept: "application/json" },
    });
    if (!res.ok) return { ok: false, reason: `API returned ${res.status}` };
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, reason: "API unreachable" };
  }
}
