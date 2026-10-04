import { expect, test } from "@playwright/test";

import { expectAccessible, mockApi, trackConsoleErrors } from "./support";

// The server-side API is unreachable in this suite (API_INTERNAL_URL points nowhere), so these
// also prove every page renders an honest offline state instead of crashing.
const pages = [
  ["/", /deployed, measured and maintained/],
  ["/projects", /^Projects$/],
  ["/projects/data-pipeline-observatory", /^Data Pipeline Observatory$/],
  ["/data", /^Data and licences$/],
  ["/hire", /^Hire me$/],
  ["/status", /^Status$/],
  ["/privacy", /^Privacy$/],
] as const;

for (const [path, heading] of pages) {
  test(`${path} renders, is accessible and logs no errors`, async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await mockApi(page);
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeAttached();
    await expectAccessible(page);
    expect(errors).toEqual([]);
  });
}

test("unknown addresses return a helpful 404", async ({ page }) => {
  const response = await page.goto("/demo/text-to-python");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "There is no page at this address.",
  );
  await page.getByRole("link", { name: "See projects" }).click();
  await expect(page).toHaveURL(/\/projects$/);
});

test("homepage shows the offline state when the API is down at render time", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/not reachable|offline/i).first()).toBeVisible();
});

test("the retired brand appears nowhere in the rendered site", async ({ page }) => {
  const banned = new RegExp(["zar", "wa"].join(""), "i");
  for (const [path] of pages) {
    await mockApi(page);
    await page.goto(path);
    expect(await page.content()).not.toMatch(banned);
  }
});

test("search engines get a sitemap and robots rules", async ({ request }) => {
  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.ok()).toBeTruthy();
  expect(await sitemap.text()).toContain("/projects/data-pipeline-observatory");
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toMatch(/User-Agent: \*/i);
});
