import { expect, test } from "@playwright/test";

import { expectAccessible, mockApi, trackConsoleErrors } from "./support";

const PAGE = "/projects/support-agent#demo";

test("a refund above the limit waits for the supervisor", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");

  await demo.getByLabel("Scenario", { exact: true }).selectOption("damaged-06");
  await expect(demo.getByText(/rabbit night lights don't work/)).toBeVisible();
  await demo.getByRole("button", { name: "Send to the agent" }).click();

  const card = demo.getByRole("region", { name: "Refund waiting for approval" });
  await expect(card).toContainText("£85.92");
  const trace = demo.getByRole("region", { name: "Agent trace" });
  await expect(trace.getByText("calculate_refund")).toBeVisible();
  await expect(trace.getByText(/2 calls at once/)).toBeVisible();

  await card.getByLabel("Note to the agent (optional)").fill("Looks right");
  await card.getByRole("button", { name: "Approve refund" }).click();
  const chat = demo.getByRole("list", { name: "Conversation" });
  await expect(chat.getByText(/Good news/)).toBeVisible();
  await expect(demo.getByText(/Refunds recorded/)).toBeVisible();
  expect(posted).toEqual([
    { scenario_id: "damaged-06" },
    { decision: "approve", note: "Looks right" },
  ]);
  expect(errors).toEqual([]);
});

test("a refund within the limit is recorded and the tool results can be opened", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByRole("button", { name: "Send to the agent" }).click();
  await expect(demo.getByRole("list", { name: "Conversation" })).toContainText("£7.50");
  await expect(demo.getByRole("link", { name: "Policy passage 1" })).toBeVisible();
  const trace = demo.getByRole("region", { name: "Agent trace" });
  await trace.getByText("get_shipment_status").click();
  await expect(trace.getByText(/"tracking_number"/)).toBeVisible();
  await demo.getByRole("button", { name: "Start another" }).click();
  await expect(demo.getByRole("button", { name: "Send to the agent" })).toBeVisible();
});

test("writing your own message", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("button", { name: "Send to the agent" })).toBeEnabled(); // hydrated
  await demo.getByText("Write your own message", { exact: true }).click();
  await expect(demo.getByRole("radio", { name: "Write your own message" })).toBeChecked();
  await demo.getByLabel("Message as the customer").fill("Two items arrived broken");
  await demo.getByRole("button", { name: "Send to the agent" }).click();
  await expect(demo.getByRole("list", { name: "Conversation" })).toBeVisible();
  expect(posted[0]).toMatchObject({ message: "Two items arrived broken" });
});

test("the quota message says when the demo can be used again", async ({ page }) => {
  await mockApi(page, {
    supportStart: {
      status: 429,
      body: { status: 429, code: "quota_exceeded", detail: "Limit reached" },
      headers: { "retry-after": "900" },
    },
  });
  await page.goto(PAGE);
  await page.locator("#demo").getByRole("button", { name: "Send to the agent" }).click();
  await expect(page.getByText(/continue in 15 minutes/)).toBeVisible();
});

test("the conversation view has no serious accessibility problems", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  await page.locator("#demo").getByLabel("Scenario", { exact: true }).selectOption("damaged-06");
  await page.locator("#demo").getByRole("button", { name: "Send to the agent" }).click();
  await expect(page.getByText("You are the supervisor")).toBeVisible();
  await expectAccessible(page);
});
