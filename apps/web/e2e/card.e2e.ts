import { expect, test } from "@playwright/test";

test("the card labels problem-side cognitive demand without scoring the student", async ({
  page,
}) => {
  await page.goto("/diagnose/S_CARD_E2E");

  await expect(page.getByText("本题的认知需求")).toBeVisible();
  await expect(page.getByText("流体推理")).toBeVisible();
  await expect(page.getByText("0.70")).toBeVisible();
  await expect(
    page.getByText("题目需求标签，不是能力测评；单题不足以断言。"),
  ).toBeVisible();
});