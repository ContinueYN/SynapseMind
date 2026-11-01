import { expect, test } from "@playwright/test";

test("the card labels problem-side cognitive demand without scoring the student", async ({
  page,
}) => {
  await page.goto("/diagnose/S_CARD_E2E");

  const attr = page.locator(".sm-attr");
  await expect(attr.getByText("本题的认知需求")).toBeVisible();
  await expect(attr.locator(".sm-attr-chip").first()).toContainText("流体推理");
  await expect(attr.locator(".sm-attr-chip").first()).toContainText("0.70");
  await expect(
    attr.getByText("题目需求标签，不是能力测评；单题不足以断言。"),
  ).toBeVisible();

  const details = attr.locator("details.sm-attr-all");
  await expect(details.locator("summary")).toHaveText("查看七维需求向量");
  await details.locator("summary").click();
  await expect(details.locator(".sm-attr-vector .sm-attr-chip")).toHaveCount(7);
  await expect(
    details.getByText("未标注维度记 0；只描述本题节点的认知需求。"),
  ).toBeVisible();
});