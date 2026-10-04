import { readFileSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type Route } from "@playwright/test";

/**
 * Browser tests answer every /api request from fixtures captured from a real run of the
 * pipeline, so the suite needs no backend and gives the same result every time.
 */
const fixture = <T>(name: string): T =>
  JSON.parse(readFileSync(path.join(__dirname, "fixtures", `${name}.json`), "utf8")) as T;

type Json = Record<string, unknown>;
type RunJson = Json & { id: string; status: string; scenario: string };

export const summary = fixture<Json>("summary");
export const runs = fixture<RunJson[]>("runs");
export const scenarios = fixture<Json[]>("scenarios");
export const succeededDetail = fixture<Json & { run: RunJson }>("run-succeeded");
export const quarantine = fixture<Json>("quarantine");

export const NEW_RUN_ID = "00000000-0000-4000-8000-000000000001";

function emptyDetail(run: RunJson): Json {
  return {
    run,
    steps: [],
    checks: [],
    reasons: [],
    warnings: [],
    logs: [],
    environment: null,
    dq_formula: succeededDetail.dq_formula,
  };
}

/** The new run goes queued → running → succeeded over successive polls. */
function newRunDetail(poll: number): Json {
  const base = succeededDetail.run;
  if (poll === 0) {
    return emptyDetail({ ...base, id: NEW_RUN_ID, status: "queued", trigger: "visitor" });
  }
  if (poll === 1) {
    return emptyDetail({ ...base, id: NEW_RUN_ID, status: "running", trigger: "visitor" });
  }
  return { ...succeededDetail, run: { ...base, id: NEW_RUN_ID, trigger: "visitor" } };
}

export interface ApiOptions {
  /** Response for POST /api/pipeline/runs; defaults to 202 with NEW_RUN_ID. */
  postRun?: { status: number; body: Json; headers?: Record<string, string> };
  /** Fail every pipeline read with this status (simulates the API being down). */
  failReadsWith?: number;
}

export async function mockApi(page: Page, options: ApiOptions = {}) {
  const posted: Json[] = [];
  let polls = 0;
  const json = (route: Route, body: unknown, status = 200, headers: Record<string, string> = {}) =>
    route.fulfill({
      status,
      headers,
      contentType: status >= 400 ? "application/problem+json" : "application/json",
      body: JSON.stringify(body),
    });

  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;

    if (req.method() === "POST" && p === "/api/pipeline/runs") {
      posted.push(req.postDataJSON() as Json);
      const r = options.postRun ?? {
        status: 202,
        body: { run_id: NEW_RUN_ID, status: "queued", pending_runs: 1 },
      };
      return json(route, r.body, r.status, r.headers);
    }
    if (req.method() === "POST" && p === "/api/contact") {
      posted.push(req.postDataJSON() as Json);
      return json(route, { received: true }, 202);
    }
    if (options.failReadsWith) {
      return json(
        route,
        { status: options.failReadsWith, title: "Unavailable" },
        options.failReadsWith,
      );
    }
    if (p === "/api/pipeline/summary") return json(route, summary);
    if (p === "/api/pipeline/scenarios") return json(route, scenarios);
    if (p === "/api/pipeline/runs") {
      const list = posted.length ? [newRunDetail(polls).run, ...runs] : runs;
      return json(route, list);
    }
    const quarantineMatch = p.match(/^\/api\/pipeline\/runs\/([^/]+)\/quarantine$/);
    if (quarantineMatch) return json(route, quarantine);
    const detailMatch = p.match(/^\/api\/pipeline\/runs\/([^/]+)$/);
    if (detailMatch) {
      const id = detailMatch[1];
      if (id === NEW_RUN_ID) return json(route, newRunDetail(polls++));
      if (id === succeededDetail.run.id) return json(route, succeededDetail);
      const run = runs.find((r) => r.id === id);
      return run ? json(route, emptyDetail(run)) : json(route, { status: 404 }, 404);
    }
    return json(route, { status: 404, title: "Not found" }, 404);
  });
  return { posted };
}

/** Fail the test on serious or critical accessibility violations. */
export async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(
    serious.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`),
  ).toEqual([]);
}

/** Collect browser console errors; 404s for deliberately missing pages are filtered by callers. */
export function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}
