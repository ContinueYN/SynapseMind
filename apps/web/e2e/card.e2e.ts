import { expect, test } from "@playwright/test";

test("the card labels problem-side cognitive demand without scoring the student", async ({
  page,
}) => {
  await page.goto("/diagnose/S_CARD_E2E");

  const attr = page.locator(".sm-attr");
  await expect(
    attr.getByRole("heading", { name: "认知需求画像" }),
  ).toBeVisible();
  await expect(attr.getByText("CHC 七维 · 本题节点")).toBeVisible();
  await expect(attr.locator(".sm-attr-row")).toHaveCount(7);
  await expect(attr.locator(".sm-attr-bar")).toHaveCount(7);
  await expect(attr.locator(".sm-attr-row--top")).toHaveCount(2);
  await expect(
    attr.locator(".sm-attr-row").filter({ hasText: "流体推理" }),
  ).toContainText("0.70");
  await expect(
    attr.getByText("题目需求标签，不是能力测评；单题不足以断言。"),
  ).toBeVisible();
  await expect(
    attr.getByText("条长是本题节点的需求权重（0–1）"),
  ).toBeVisible();
});