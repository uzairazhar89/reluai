import { expect, test } from "@playwright/test";

import { mockApi, NEW_RUN_ID, succeededDetail, trackConsoleErrors } from "./support";

const PAGE = "/projects/data-pipeline-observatory#demo";

test("a visitor starts a run and follows it to completion", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);

  const dashboard = page.locator("#demo");
  await expect(dashboard.getByRole("heading", { name: "Pipeline dashboard" })).toBeVisible();
  await expect(dashboard.getByText("Last run", { exact: true })).toBeVisible();

  await dashboard.getByLabel("Replay last drop (idempotency)").check();
  await expect(dashboard.getByText(/Loads are idempotent/)).toBeVisible();
  await dashboard.getByRole("button", { name: "Run scenario" }).click();

  await expect(dashboard.getByText(/^Run queued/)).toBeVisible();
  expect(posted).toEqual([{ scenario: "replay" }]);

  const detail = dashboard.locator("article[aria-live]");
  await expect(detail.getByText(/Queued\.|Running\./).first()).toBeVisible();
  await expect(detail.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(detail.getByRole("heading", { name: /Data-quality checks/ })).toBeVisible();
  await expect(detail.getByText("Share of exact duplicate lines")).toBeVisible();
  expect(errors).toEqual([]);
});

test("the quota message says when the next run is allowed", async ({ page }) => {
  await mockApi(page, {
    postRun: {
      status: 429,
      body: { status: 429, code: "quota_exceeded", detail: "Limit reached" },
      headers: { "retry-after": "1200" },
    },
  });
  await page.goto(PAGE);
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText(/start another in 20 minutes/)).toBeVisible();
});

test("selecting a past run shows its quarantined rows on request", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const dashboard = page.locator("#demo");
  const runButton = dashboard
    .getByRole("button", { name: /Load next monthly drop.*December 2010/ })
    .first();
  await runButton.click();
  await expect(runButton).toHaveAttribute("aria-current", "true");

  const detail = dashboard.locator("article[aria-live]");
  await expect(detail.getByRole("heading", { name: /December 2010/ })).toBeVisible();
  const reason = detail.getByRole("button", { name: "Stock adjustment" });
  await expect(reason).toHaveAttribute("aria-expanded", "false");
  await reason.click();
  await expect(reason).toHaveAttribute("aria-expanded", "true");
  await expect(detail.getByText(/^line \d+$/).first()).toBeVisible();
  expect(succeededDetail.run.id).not.toBe(NEW_RUN_ID);
});

test("the dashboard explains itself when the API is down", async ({ page }) => {
  await mockApi(page, { failReadsWith: 502 });
  await page.goto(PAGE);
  await expect(page.getByText("The pipeline service is not reachable right now.")).toBeVisible({
    timeout: 15_000,
  });
  // The written case study is still there.
  await expect(page.getByRole("heading", { name: /Failure handling/ })).toBeVisible();
});
