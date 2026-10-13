import path from "node:path";

import { expect, test } from "@playwright/test";

import { docsUpload, expectAccessible, mockApi, trackConsoleErrors } from "./support";

const PAGE = "/projects/document-intelligence#demo";

test("asking the sample gives a cited answer that links to its passage", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(
    demo.getByText("Artificial Intelligence Risk Management Framework (AI RMF 1.0)"),
  ).toBeVisible();
  await expect(demo.getByText("48 read of 48")).toBeVisible();

  await demo
    .getByRole("button", { name: "What are the four functions of the AI RMF core?" })
    .click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText(/GOVERN, MAP, MEASURE, and MANAGE/).first()).toBeVisible();
  await expect(answer.getByText("Extractive (no model)")).toBeVisible();
  await expect(answer.getByText(/Best sentence: 73% of the question's words/)).toBeVisible();

  await answer.getByRole("button", { name: "Show passage 4" }).click();
  const passage = answer.locator("#passage-4");
  await expect(passage).toContainText("p. 25");
  await expect(passage).toContainText("5. AI RMF Core");
  expect(posted).toEqual([
    {
      question: "What are the four functions of the AI RMF core?",
      mode: "auto",
      allow_external: false,
    },
  ]);
  expect(errors).toEqual([]);
});

test("a question the document does not cover is declined with the closest passages", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo
    .getByRole("button", { name: "What does the framework say about cryptocurrency?" })
    .click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText("Not found in the document")).toBeVisible();
  await expect(answer.getByText(/Why: best sentence matched 25%/)).toBeVisible();
  await expect(answer.getByText("Closest passages", { exact: true })).toBeVisible();
});

test("the passages the sample was split into can be browsed", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByText("How it was split into passages").click();
  await expect(demo.getByText("#1", { exact: true })).toBeVisible();
  await expect(demo.getByText(/1–10 of 140/)).toBeVisible();
  await demo.getByText(/Headings found/).click();
  await expect(demo.getByText("1.2.2 Risk Tolerance", { exact: true })).toBeVisible();
});

test("an uploaded PDF is read, answered from and deleted", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("button", { name: /What are the four functions/ })).toBeEnabled();
  await demo.getByText("Your PDF", { exact: true }).click();
  await demo
    .locator('input[type="file"]')
    .setInputFiles(path.join(__dirname, "fixtures", "delivery-delays.pdf"));

  await expect(
    demo.getByText("Measuring Delivery Delays in Online Retail", { exact: true }).first(),
  ).toBeVisible();
  await expect(demo.getByText("2 read of 2")).toBeVisible();
  await expect(demo.getByText("Your upload")).toBeVisible();
  await expect(demo.getByLabel(/Let a hosted model write the answer/)).toBeDisabled();

  await demo
    .getByLabel("Ask a question about this document")
    .fill("When is a delivery considered late?");
  await demo.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = demo.getByRole("region", { name: "Answer" });
  await expect(answer.getByText(/more than three days after the estimate/).first()).toBeVisible();

  await demo.getByRole("button", { name: "Delete now" }).click();
  await expect(
    demo.getByText("Measuring Delivery Delays in Online Retail", { exact: true }).first(),
  ).toBeHidden();
  await expect(demo.getByRole("button", { name: "Choose a PDF" })).toBeVisible();
  expect(posted).toEqual([
    { upload: "multipart/form-data" },
    { question: "When is a delivery considered late?", mode: "auto", allow_external: false },
    { deleted: docsUpload.id },
  ]);
  expect(errors).toEqual([]);
});

test("a file over the size limit is refused before it is sent", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("button", { name: /What are the four functions/ })).toBeEnabled();
  await demo.getByText("Your PDF", { exact: true }).click();
  await demo.locator('input[type="file"]').setInputFiles({
    name: "large.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.alloc(11 * 1024 * 1024, 0x20),
  });
  await expect(demo.getByText(/PDFs can be up to 10 MB/)).toBeVisible();
  expect(posted).toEqual([]);
});

test("the quota message says when questions are allowed again", async ({ page }) => {
  await mockApi(page, {
    docsAsk: {
      status: 429,
      body: { status: 429, code: "quota_exceeded", detail: "Limit reached" },
      headers: { "retry-after": "600" },
    },
  });
  await page.goto(PAGE);
  await page
    .locator("#demo")
    .getByRole("button", { name: "What are the four functions of the AI RMF core?" })
    .click();
  await expect(page.getByText(/continue in 10 minutes/)).toBeVisible();
});

test("the answer view has no serious accessibility problems", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo
    .getByRole("button", { name: "What are the four functions of the AI RMF core?" })
    .click();
  await expect(
    demo
      .getByRole("region", { name: "Answer" })
      .getByText(/GOVERN/)
      .first(),
  ).toBeVisible();
  await expectAccessible(page);
});
