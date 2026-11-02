import { expect, test } from "@playwright/test";

test("the home page cites its design sources without claiming an effect", async ({
  page,
}) => {
  await page.goto("/");

  const research = page.locator(".sm-research");
  await expect(page.getByText("借的是机制，不借效果背书。")).toBeVisible();
  await expect(research.locator(".sm-research-card")).toHaveCount(8);
  await expect(
    research.getByRole("link", { name: /doi:10\./ }),
  ).toHaveCount(16);

  await expect(
    page.getByRole("link", { name: /Citri & Malenka/ }),
  ).toHaveAttribute("href", "https://doi.org/10.1038/sj.npp.1301559");
  await expect(page.getByRole("link", { name: /Sweller/ }).first()).toHaveAttribute(
    "href",
    "https://doi.org/10.1207/s15516709cog1202_4",
  );
  await expect(
    page.getByRole("link", { name: /Hattie & Timperley/ }),
  ).toHaveAttribute("href", "https://doi.org/10.3102/003465430298487");

  await expect(
    page.getByText(
      "这些文献解释设计来源，不证明本产品有效；没有对照实验或提分数据。",
    ),
  ).toBeVisible();
});