import path from "node:path";

import { expect, test } from "@playwright/test";

import { expectAccessible, mockApi, trackConsoleErrors } from "./support";

const PAGE = "/projects/ai-csv-analyst#demo";

test("a visitor asks a question and sees how it was read", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");

  await demo.getByRole("button", { name: "Revenue per month" }).click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText("Total revenue per month.")).toBeVisible();
  await expect(answer.getByText("Rules", { exact: true })).toBeVisible();
  await expect(
    answer.getByRole("img", { name: /Total revenue by month, 25 points/ }),
  ).toBeVisible();

  await answer.getByRole("tab", { name: "Table" }).click();
  await expect(answer.getByRole("cell", { name: "Dec 2009" })).toBeVisible();
  await answer.getByRole("tab", { name: "SQL" }).click();
  await expect(answer.getByLabel("SQL that was run")).toContainText("date_trunc('month'");
  await answer.getByRole("tab", { name: "pandas" }).click();
  await expect(answer.getByLabel("Equivalent pandas code")).toContainText(".groupby(");
  await page.keyboard.press("ArrowLeft");
  await expect(answer.getByRole("tab", { name: "SQL" })).toHaveAttribute("aria-selected", "true");

  expect(posted).toEqual([{ dataset: "retail", question: "Revenue per month", allow_llm: false }]);
  expect(errors).toEqual([]);
});

test("a question the rules cannot read is declined with suggestions", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByLabel("Ask a question in plain English").fill("Why did customers leave?");
  await demo.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText("Not understood", { exact: true })).toBeVisible();
  await expect(answer.getByText(/no language model is available/)).toBeVisible();
  await answer.getByRole("button", { name: "Revenue per month" }).click();
  await expect(answer.getByText("Total revenue per month.")).toBeVisible();
});

test("uploading a CSV shows its profile and answers questions about it", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByLabel("Your CSV file").check();
  await demo.locator("#csv-file").setInputFiles(path.join(__dirname, "fixtures", "orders.csv"));
  await expect(demo.getByText("orders.csv", { exact: true })).toBeVisible();
  await expect(demo.getByText(/would run as formulas in a spreadsheet/)).toBeVisible();
  await expect(demo.getByText(/thousands separators/)).toBeVisible();
  await expect(demo.getByLabel(/Let a language model read questions/)).toBeDisabled();

  await demo.getByRole("button", { name: "Units by region" }).click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText("Total units by region; highest 20 first.")).toBeVisible();
  expect(posted.at(-1)).toMatchObject({ question: "Units by region", allow_llm: false });
});

test("the quota message says when questions are allowed again", async ({ page }) => {
  await mockApi(page, {
    csvAsk: {
      status: 429,
      body: { status: 429, code: "quota_exceeded", detail: "Limit reached" },
      headers: { "retry-after": "600" },
    },
  });
  await page.goto(PAGE);
  await page.locator("#demo").getByRole("button", { name: "Revenue per month" }).click();
  await expect(page.getByText(/ask again in 10 minutes/)).toBeVisible();
});

test("the page has no serious accessibility problems", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  await page.locator("#demo").getByRole("button", { name: "Revenue per month" }).click();
  await expect(page.getByText("Total revenue per month.")).toBeVisible();
  await expectAccessible(page);
});
