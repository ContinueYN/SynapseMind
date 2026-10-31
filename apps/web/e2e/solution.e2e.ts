import { expect, test } from "@playwright/test";

test("an exited session reveals the solution only after a second explicit click", async ({
  page,
}) => {
  await page.goto("/diagnose/S_REVEAL_E2E");

  await expect(page.getByText("本轮结束")).toBeVisible();
  const reveal = page.getByRole("button", { name: "看完整解法" });
  await expect(reveal).toBeVisible();
  await expect(page.getByText("a∈[1/e,+∞)")).toHaveCount(0);

  await reveal.click();
  await expect(
    page.getByRole("button", { name: /再点一次：显示答案与完整解法/ }),
  ).toBeVisible();
  await expect(page.getByText("a∈[1/e,+∞)")).toHaveCount(0);

  await page
    .getByRole("button", { name: /再点一次：显示答案与完整解法/ })
    .click();

  await expect(page.getByText("完整解法", { exact: true })).toBeVisible();
  await expect(page.getByText("a∈[1/e,+∞)")).toBeVisible();
  await expect(page.getByText(/定义域 x>0/)).toBeVisible();
});

test("the full card page can reveal the same solution without losing the card", async ({
  page,
}) => {
  await page.goto("/card/S_CARD_E2E");

  await expect(
    page.getByRole("heading", { name: "概念不清：恒成立与最值" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "看完整解法" }).click();
  await page
    .getByRole("button", { name: /再点一次：显示答案与完整解法/ })
    .click();

  await expect(page.getByText("完整解法", { exact: true })).toBeVisible();
  await expect(page.getByText("a∈[1/e,+∞)")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "概念不清：恒成立与最值" }),
  ).toBeVisible();
});