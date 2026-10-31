import { expect, test } from "@playwright/test";

test("math step check renders a structured counterexample", async ({ page }) => {
  await page.goto("/diagnose/S_MATH_E2E");

  await page.getByRole("button", { name: /有一步拿不准/ }).click();
  await page.getByLabel("这一步").fill("x+1=2x");
  await page.getByRole("button", { name: "检查这一步" }).click();

  const result = page.locator(".sm-stepcheck-result");
  await expect(result).toHaveAttribute("data-status", "fail");
  await expect(result.getByText("这个等号不成立")).toBeVisible();
  await expect(result.getByText("有反例")).toBeVisible();
  await expect(result.locator("code")).toContainText("x+1 = 2*x");
  await expect(result).toContainText("x=0.1 时左边 1.1、右边 0.2");
});

test("math step check keeps unknown away from a correctness claim", async ({
  page,
}) => {
  await page.goto("/diagnose/S_MATH_E2E");

  await page.getByRole("button", { name: /有一步拿不准/ }).click();
  await page.getByLabel("这一步").fill("x+1=1+x");
  await page.getByRole("button", { name: "检查这一步" }).click();

  const result = page.locator(".sm-stepcheck-result");
  await expect(result).toHaveAttribute("data-status", "unknown");
  await expect(result.getByText("未证明")).toBeVisible();
  await expect(result).toContainText("没判出来不等于这一步正确");
});

test("physics step check sends declared result/tolerance and survives 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/diagnose/S_PHYS_E2E");

  await page.getByRole("button", { name: /有一步拿不准/ }).click();
  await page.getByLabel("这一步").fill("sqrt(2*g*h)");
  await page.getByLabel("符号单位").fill("g=m/s^2\nh=m");
  await page.getByLabel("数值").fill("g=10\nh=2");
  await page.getByLabel("结果单位").fill("m/s");
  await page.getByLabel("你写的结果").fill("6.3246");
  await page.getByLabel("相对容差").fill("1");
  await page.getByRole("button", { name: "检查这一步" }).click();

  const result = page.locator(".sm-stepcheck-result");
  await expect(result).toHaveAttribute("data-status", "pass");
  await expect(result).toContainText("声明结果值与单位一致");

  await page.getByLabel("你写的结果").fill("7");
  await page.getByRole("button", { name: "检查这一步" }).click();
  await expect(result).toHaveAttribute("data-status", "fail");
  await expect(result).toContainText("结果值不一致");

  const mobile = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    columns: Array.from(document.querySelectorAll(".sm-stepcheck-grid")).map(
      (node) => getComputedStyle(node).gridTemplateColumns,
    ),
  }));
  expect(mobile.innerWidth).toBe(390);
  expect(mobile.scrollWidth).toBe(mobile.clientWidth);
  expect(mobile.columns).toHaveLength(2);
  for (const columns of mobile.columns) {
    expect(columns.split(" ")).toHaveLength(1);
  }

  await page.setViewportSize({ width: 1280, height: 900 });
  await expect
    .poll(async () =>
      page
        .locator(".sm-stepcheck-grid")
        .first()
        .evaluate((node) => getComputedStyle(node).gridTemplateColumns),
    )
    .toContain(" ");
  const desktopOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(desktopOverflow).toBe(0);
});
