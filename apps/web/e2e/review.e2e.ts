import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

test("teacher review lists disagreements and exports the judgment as CSV", async ({
  page,
}) => {
  await page.goto("/admin/review");

  await expect(
    page.getByRole("heading", { name: "只看卡面，不看原文。" }),
  ).toBeVisible();
  const items = page.getByRole("listitem");
  await expect(items).toHaveCount(2);
  await expect(page.getByLabel("队列概况")).toContainText("2条异议");
  await expect(page.getByLabel("队列概况")).toContainText("0已判断");

  const first = items.filter({ hasText: "概念不清：恒成立与最值" });
  await first.getByRole("button", { name: "准确" }).click();

  await expect(first.getByRole("button", { name: "准确" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByLabel("队列概况")).toContainText("1已判断");

  // The judgment survives a reload: it is stored in this browser, not on the
  // server.
  await page.reload();
  const reloaded = page
    .getByRole("listitem")
    .filter({ hasText: "概念不清：恒成立与最值" });
  await expect(reloaded.getByRole("button", { name: "准确" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^review-\d{8}-\d{4}\.csv$/);

  const path = await download.path();
  expect(path).not.toBeNull();
  const csv = await readFile(path as string, "utf8");
  expect(csv).toContain("S_REVIEWE2E01");
  expect(csv).toContain("概念不清：恒成立与最值");
  expect(csv).toContain("准确");
  expect(csv).toContain("2026-10-31T08:00:00+00:00");
});

test("teacher review drops to one column at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/review");

  await expect(
    page.getByRole("heading", { name: "只看卡面，不看原文。" }),
  ).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(2);

  const layout = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    columns: getComputedStyle(
      document.querySelector(".sm-review-judge") as Element,
    ).gridTemplateColumns,
  }));
  expect(layout.scrollWidth).toBe(layout.clientWidth);
  expect(layout.columns.split(" ")).toHaveLength(1);
});