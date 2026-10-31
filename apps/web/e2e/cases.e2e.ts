import { expect, test } from "@playwright/test";

test("the case page shows four transcripts, including the refusal", async ({
  page,
}) => {
  await page.goto("/cases");

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "四段记录",
  );
  await expect(page.getByRole("heading", { level: 3 })).toHaveCount(4);
  await expect(page.getByText(/弃权：没有出卡/)).toBeVisible();
  await expect(page.getByText(/没有把低置信的猜测包装成诊断/)).toBeVisible();
  await expect(page.getByText(/演示样例，不是效果研究；不放准确率/)).toBeVisible();
});

test("the case page links back to the mechanisms it demonstrates", async ({
  page,
}) => {
  await page.goto("/cases");

  // Assert the target instead of clicking: the first cold dev compile of a
  // route can swallow a client-side navigation started before hydration.
  await expect(
    page.getByRole("link", { name: /五条机制与引用/ }),
  ).toHaveAttribute("href", "/science");

  await page.goto("/science");
  await expect(page.getByRole("heading", { name: /五条机制/ })).toBeVisible();
});