import { expect, test } from "@playwright/test";

import { mockApi } from "./support";

test("a recruiter can send a message", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto("/hire");
  await page.getByLabel("Name").fill("Grace Hopper");
  await page.getByLabel("Email").fill("grace@example.com");
  await page.getByLabel("What it is about").selectOption("contract");
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("We are hiring a Python data engineer for a six-month contract.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Message sent.")).toBeVisible();
  expect(posted[0]).toMatchObject({
    name: "Grace Hopper",
    email: "grace@example.com",
    topic: "contract",
    website: null,
  });
});

test("the browser blocks an obviously incomplete message", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto("/hire");
  await page.getByLabel("Name").fill("Grace Hopper");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByLabel("Email")).toHaveJSProperty("validity.valueMissing", true);
  expect(posted).toEqual([]);
});
