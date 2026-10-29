import path from "node:path";

import { expect, test } from "@playwright/test";

import { expectAccessible, mockApi, trackConsoleErrors } from "./support";

const PAGE = "/projects/edge-ai-benchmark-lab#demo";

test("a sample photo is classified by all three variants", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  const samples = demo.getByRole("list", { name: "Sample photos" });
  await samples.getByRole("button", { name: "Classify sample photo 4" }).click();

  for (const title of ["PyTorch FP32", "ONNX Runtime FP32", "ONNX Runtime INT8"]) {
    await expect(demo.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(demo.getByText("Reference", { exact: true })).toBeVisible();
  await expect(demo.getByText("Same answer", { exact: true })).toHaveCount(2);
  const top5 = demo.getByRole("list", { name: "ONNX Runtime INT8: top 5" });
  await expect(top5.getByText("teddy")).toBeVisible();
  await expect(demo.getByText(/Each runtime started in a fresh process: PyTorch in/)).toBeVisible();
  await expect(demo.getByRole("link", { name: "Flickr" })).toBeVisible();
  expect(posted).toEqual([{ benchSample: "000000418961.jpg", model: "mobilenetv3-small" }]);
  expect(errors).toEqual([]);
});

test("choosing the other model runs the same photo again", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByRole("button", { name: "Classify sample photo 4" }).click();
  await expect(demo.getByRole("heading", { name: "PyTorch FP32" })).toBeVisible();
  await demo.getByRole("radio", { name: /ResNet-18/ }).click();
  await expect(demo.getByRole("radio", { name: /ResNet-18/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect.poll(() => posted.length).toBe(2);
  expect(posted[1]).toEqual({ benchSample: "000000418961.jpg", model: "resnet18" });
  await expect(demo.getByRole("heading", { name: "PyTorch FP32" })).toBeVisible();
});

test("your own photo is classified and not kept", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByRole("radio", { name: /ResNet-18/ }).click();
  await demo
    .locator('input[type="file"]')
    .setInputFiles(path.join(__dirname, "fixtures", "bench-photo.jpg"));
  await expect(demo.getByRole("img", { name: "Your photo" })).toBeVisible();
  const top5 = demo.getByRole("list", { name: "PyTorch FP32: top 5" });
  await expect(top5.getByText("hotdog")).toBeVisible();
  await expect(demo.getByText(/decoded and re-encoded in an isolated process/)).toBeVisible();
  expect(posted).toEqual([{ benchUpload: "multipart/form-data" }]);
});

test("files the demo cannot use are refused in the browser", async ({ page }) => {
  const { posted } = await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await expect(demo.getByRole("button", { name: "Upload your own photo" })).toBeEnabled();
  await demo.locator('input[type="file"]').setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("not a photo"),
  });
  await expect(demo.getByText("Choose a JPEG, PNG or WebP photo.")).toBeVisible();
  expect(posted).toEqual([]);
});

test("the quota message says when the demo can be used again", async ({ page }) => {
  await mockApi(page, {
    benchTry: {
      status: 429,
      body: { status: 429, title: "Too Many Requests", code: "quota_exceeded" },
      headers: { "Retry-After": "600" },
    },
  });
  await page.goto(PAGE);
  await page.locator("#demo").getByRole("button", { name: "Classify sample photo 1" }).click();
  await expect(page.getByText(/You can continue in 10 minutes/)).toBeVisible();
});

test("the demo has no serious accessibility problems", async ({ page }) => {
  await mockApi(page);
  await page.goto(PAGE);
  const demo = page.locator("#demo");
  await demo.getByRole("button", { name: "Classify sample photo 4" }).click();
  await expect(demo.getByRole("heading", { name: "ONNX Runtime INT8" })).toBeVisible();
  await expectAccessible(page);
});
