import path from "node:path";

import { expect, test } from "@playwright/test";

import { expectAccessible, mockApi, trackConsoleErrors } from "./support";

const PAGE = "/projects/document-intelligence#invoice";

test("a sample invoice is read and every value is checked against its record", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("tab", { name: "Read an invoice" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const list = demo.getByRole("list", { name: "Sample invoices" });
  await expect(list.getByText("Invoice 566046")).toBeVisible();
  await expect(list.getByRole("link", { name: "Open invoice 566046 as a PDF" })).toHaveAttribute(
    "href",
    "/api/documents/invoices/566046-s2.pdf",
  );

  await list.getByRole("button", { name: "Read invoice 566046" }).click();
  const result = demo.getByRole("region", { name: "Extraction result" });
  await expect(result.getByText("Read exactly", { exact: true })).toBeVisible();
  await expect(result.getByRole("img", { name: /Page 1 of the invoice/ })).toBeVisible();
  const fields = result.getByRole("table", { name: "Header fields read from the invoice" });
  await expect(fields.getByRole("row", { name: /Invoice number 566046/ })).toBeVisible();
  const lines = result.getByRole("table", { name: "Line items read from the invoice" });
  await expect(lines.getByText("LOVEBIRD HANGING DECORATION WHITE")).toBeVisible();
  await expect(result.getByText("The lines add up to the total")).toBeVisible();
  await result.getByText("Structured output (JSON)").click();
  await expect(result.getByText(/"stock_code": "22219"/)).toBeVisible();
  expect(posted).toEqual([{ invoice: "566046-s2" }]);
  expect(errors).toEqual([]);
});

test("filters choose layouts and formats", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  const list = demo.getByRole("list", { name: "Sample invoices" });
  await expect(list.getByText(/layout 1\b/).first()).toBeVisible();
  await demo.getByRole("radio", { name: "New to the extractor" }).click();
  await demo.getByRole("radio", { name: "Scanned" }).click();
  await expect(list.getByText(/layout 10\d\d/).first()).toBeVisible();
  await expect(list.getByText("Wrong last run").first()).toBeVisible();
});

test("your own invoice is read without a record to compare", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("button", { name: "Read invoice 566046" })).toBeEnabled();
  await demo.getByText("Your invoice PDF", { exact: true }).click();
  await demo
    .locator('input[type="file"]')
    .setInputFiles(path.join(__dirname, "fixtures", "credit-note.pdf"));
  const result = demo.getByRole("region", { name: "Extraction result" });
  await expect(result.getByText("Checks passed", { exact: true })).toBeVisible();
  await expect(result.getByText(/Read\s+credit-note\.pdf/)).toBeVisible();
  const fields = result.getByRole("table", { name: "Header fields read from the invoice" });
  await expect(fields.getByRole("columnheader", { name: "Record" })).toHaveCount(0);
  await expect(fields.getByRole("row", { name: /Document type Credit note/ })).toBeVisible();
  expect(posted).toEqual([{ invoiceUpload: "multipart/form-data" }]);
});

test("a busy server asks the visitor to try again", async ({ page }) => {
  await mockApi(page, {
    invoiceRun: {
      status: 503,
      body: { status: 503, code: "busy", detail: "The server is busy" },
      headers: { "retry-after": "30" },
    },
  });
  await page.goto(PAGE);
  await page.locator("#demo").getByRole("button", { name: "Read invoice 566046" }).click();
  await expect(page.getByText(/try again in a minute/i)).toBeVisible();
});

test("the invoice result has no serious accessibility problems", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByRole("button", { name: "Read invoice 566046" }).click();
  await expect(demo.getByText("Read exactly", { exact: true })).toBeVisible();
  await expectAccessible(page);
});
