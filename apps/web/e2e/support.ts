import { readFileSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type Route } from "@playwright/test";

/**
 * Browser tests answer every /api request from fixtures captured from real runs of the
 * services, so the suite needs no backend and gives the same result every time.
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

export const csvRetail = fixture<Json>("csv-retail");
export const csvUpload = fixture<Json & { id: string }>("csv-upload");
const csvAnswers: Record<string, Json> = {
  "Top 5 countries by revenue in 2011, excluding the UK": fixture<Json>("csv-ask-top"),
  "Revenue per month": fixture<Json>("csv-ask-month"),
  "Units by region": fixture<Json>("csv-ask-upload"),
};
const csvDeclined = fixture<Json>("csv-ask-declined");

export const supportCatalogue = fixture<Json>("support-catalogue");
const supportPending = fixture<Json & { id: string }>("support-convo-pending");
const supportApproved = fixture<Json>("support-convo-approved");
const supportRefund = fixture<Json>("support-convo-refund");

export const docsSample = fixture<Json & { id: string }>("docs-sample");
const docsChunks = fixture<Json>("docs-chunks");
export const docsUpload = fixture<Json & { id: string }>("docs-upload-queued");
const docsUploadReady = fixture<Json>("docs-upload-ready");
const docsAnswers: Record<string, Json> = {
  "What are the four functions of the AI RMF core?": fixture<Json>("docs-ask-functions"),
  "What does the framework say about cryptocurrency?": fixture<Json>("docs-ask-crypto"),
  "When is a delivery considered late?": fixture<Json>("docs-ask-upload"),
};
const docsDeclined = fixture<Json>("docs-ask-crypto");

export const invoiceGallery = fixture<Json & { documents: { id: string }[] }>("invoices-gallery");
const invoiceSampleRun = fixture<Json>("invoice-run-sample");
const invoiceUploadRun = fixture<Json>("invoice-run-upload");

export const benchRegistry = fixture<Json>("bench-registry");
export const benchSamples = fixture<{ name: string; url: string }[]>("bench-samples");
const benchTrySample = fixture<Json>("bench-try-sample");
const benchTryUpload = fixture<Json>("bench-try-upload");
const benchPhoto = readFileSync(path.join(__dirname, "fixtures", "bench-photo.jpg"));

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
  /** Response for POST /api/csv/ask instead of the recorded answers. */
  csvAsk?: { status: number; body: Json; headers?: Record<string, string> };
  /** Response for POST /api/support/conversations instead of the recorded ones. */
  supportStart?: { status: number; body: Json; headers?: Record<string, string> };
  /** Response for POST /api/documents/{id}/ask instead of the recorded answers. */
  docsAsk?: { status: number; body: Json; headers?: Record<string, string> };
  /** Response for POST /api/documents/invoices/{id}/extract instead of the recorded run. */
  invoiceRun?: { status: number; body: Json; headers?: Record<string, string> };
  /** Response for the benchmark's "Try it" requests instead of the recorded runs. */
  benchTry?: { status: number; body: Json; headers?: Record<string, string> };
}

export async function mockApi(page: Page, options: ApiOptions = {}) {
  const posted: Json[] = [];
  let polls = 0;
  let docPolls = 0;
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
    if (req.method() === "POST" && p === "/api/csv/ask") {
      const body = req.postDataJSON() as Json & { question: string };
      posted.push(body);
      if (options.csvAsk) {
        return json(route, options.csvAsk.body, options.csvAsk.status, options.csvAsk.headers);
      }
      const answer = csvAnswers[body.question] ?? { ...csvDeclined, question: body.question };
      return json(route, answer);
    }
    if (req.method() === "POST" && p === "/api/csv/uploads") {
      return json(route, csvUpload, 201);
    }
    if (req.method() === "POST" && p === "/api/support/conversations") {
      const body = req.postDataJSON() as Json & { scenario_id?: string };
      posted.push(body);
      if (options.supportStart) {
        const r = options.supportStart;
        return json(route, r.body, r.status, r.headers);
      }
      return json(route, body.scenario_id === "damaged-06" ? supportPending : supportRefund, 201);
    }
    if (req.method() === "POST" && p.endsWith("/approval")) {
      posted.push(req.postDataJSON() as Json);
      return json(route, supportApproved);
    }
    const askMatch = p.match(/^\/api\/documents\/([^/]+)\/ask$/);
    if (req.method() === "POST" && askMatch) {
      const body = req.postDataJSON() as Json & { question: string };
      posted.push(body);
      if (options.docsAsk) {
        const r = options.docsAsk;
        return json(route, r.body, r.status, r.headers);
      }
      return json(
        route,
        docsAnswers[body.question] ?? { ...docsDeclined, question: body.question },
      );
    }
    const invoiceRun = p.match(/^\/api\/documents\/invoices\/([^/]+)\/extract$/);
    if (req.method() === "POST" && invoiceRun) {
      posted.push({ invoice: invoiceRun[1] });
      if (options.invoiceRun) {
        const r = options.invoiceRun;
        return json(route, r.body, r.status, r.headers);
      }
      return json(route, invoiceSampleRun);
    }
    if (req.method() === "POST" && p === "/api/documents/invoices/uploads") {
      posted.push({ invoiceUpload: req.headers()["content-type"]?.split(";")[0] });
      return json(route, invoiceUploadRun);
    }
    if (p === "/api/documents/invoices") return json(route, invoiceGallery);
    const benchSample = p.match(/^\/api\/bench\/try\/samples\/([^/]+)$/);
    if (req.method() === "POST" && (benchSample || p === "/api/bench/try")) {
      const model = url.searchParams.get("model");
      posted.push(
        benchSample
          ? { benchSample: benchSample[1], model }
          : { benchUpload: req.headers()["content-type"]?.split(";")[0] },
      );
      if (options.benchTry) {
        const r = options.benchTry;
        return json(route, r.body, r.status, r.headers);
      }
      const recorded = benchSample ? benchTrySample : benchTryUpload;
      return json(route, { ...recorded, model: model ?? recorded.model });
    }
    if (p === "/api/bench/registry") return json(route, benchRegistry);
    if (p === "/api/bench/samples") return json(route, benchSamples);
    if (p.startsWith("/api/bench/samples/")) {
      return route.fulfill({ status: 200, contentType: "image/jpeg", body: benchPhoto });
    }
    if (req.method() === "POST" && p === "/api/documents/uploads") {
      posted.push({ upload: req.headers()["content-type"]?.split(";")[0] });
      return json(route, docsUpload, 202);
    }
    if (req.method() === "DELETE" && p === `/api/documents/${docsUpload.id}`) {
      posted.push({ deleted: docsUpload.id });
      return route.fulfill({ status: 204 });
    }
    if (p === "/api/documents/sample") return json(route, docsSample);
    if (p === `/api/documents/${docsSample.id}/chunks`) return json(route, docsChunks);
    if (p === `/api/documents/${docsUpload.id}`) {
      // The recorded upload went queued → reading → ready; one poll is shown as reading.
      const reading = { ...docsUpload, status: "reading", progress_done: 1, progress_total: 2 };
      return json(route, docPolls++ === 0 ? reading : docsUploadReady);
    }
    if (p === "/api/support/catalogue") return json(route, supportCatalogue);
    if (p === "/api/csv/datasets/retail") return json(route, csvRetail);
    if (p === `/api/csv/uploads/${csvUpload.id}`) return json(route, csvUpload);
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
