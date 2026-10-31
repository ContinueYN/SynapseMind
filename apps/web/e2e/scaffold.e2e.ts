import { expect, test } from "@playwright/test";

test("blank entry shows one example, then hands the next line to the probe ladder", async ({
  page,
}) => {
  await page.goto("/diagnose/S_SCAFFOLD_E2E");

  await expect(page.getByText("起步示例 · 先不定位")).toBeVisible();
  await expect(page.getByText("先照着写一行，再开始追问")).toBeVisible();
  await expect(page.getByText("确认定义域 x>0")).toBeVisible();
  await expect(
    page.getByText("示例只展示起步，不是本题答案；写出一行后继续诊断。"),
  ).toBeVisible();

  const submit = page.getByRole("button", { name: /写好了，继续诊断/ });
  await expect(submit).toBeDisabled();

  await page.getByLabel("你的下一行").fill("定义域是 x>0");
  await submit.click();

  await expect(page.getByText("定义域写出来之后，恒成立要转成什么？")).toBeVisible();
  await expect(page.getByText("起步示例 · 先不定位")).toHaveCount(0);
});