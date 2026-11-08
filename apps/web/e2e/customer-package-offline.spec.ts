import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.LIVECLIP_PYTHON ?? path.join(repoRoot, ".venv/bin/python");

test("an extracted customer package works from file:// with every network request blocked", async ({
  page,
}, testInfo) => {
  const output = testInfo.outputPath("customer-package");
  const indexPath = execFileSync(
    python,
    [path.join(repoRoot, "tests/support/build_customer_package_fixture.py"), output],
    {
      cwd: repoRoot,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.join(repoRoot, "src") },
      encoding: "utf-8",
    },
  ).trim();
  const blocked: string[] = [];
  await page.context().route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith("file:")) {
      await route.continue();
      return;
    }
    blocked.push(url);
    await route.abort();
  });
  const requested: string[] = [];
  page.on("request", (request) => requested.push(request.url()));

  await page.goto(`file://${indexPath}`);

  await expect(page.getByRole("heading", { level: 1, name: "离线交付测试" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "短片（2）" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "小课（1）" })).toBeVisible();
  await expect(page.locator("article.card")).toHaveCount(3);
  const sources = await page.locator("video").evaluateAll((items) =>
    items.map((item) => item.getAttribute("src")),
  );
  expect(sources).toEqual([
    "clips/short/01-短片一.mp4",
    "clips/short/02-短片二.mp4",
    "clips/lesson/03-小课一.mp4",
  ]);
  await expect(page.getByRole("link", { name: "下载字幕（SRT）" }).first()).toHaveAttribute(
    "href",
    "clips/short/01-短片一.srt",
  );
  await expect(page.getByText("本文件夹就是完整的交付包")).toBeVisible();
  expect(blocked).toEqual([]);
  expect(requested.every((url) => url.startsWith("file:"))).toBe(true);
});
