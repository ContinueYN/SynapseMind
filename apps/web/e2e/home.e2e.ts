import { expect, test } from "@playwright/test";

test("the home page cites its design metaphors without claiming an effect", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByText("类比有出处，效果不借背书。")).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Citri & Malenka/ }),
  ).toHaveAttribute("href", "https://doi.org/10.1038/sj.npp.1301559");
  await expect(
    page.getByRole("link", { name: /Sweller/ }),
  ).toHaveAttribute("href", "https://doi.org/10.1207/s15516709cog1202_4");
  await expect(
    page.getByRole("link", { name: /Hattie & Timperley/ }),
  ).toHaveAttribute("href", "https://doi.org/10.3102/003465430298487");
  await expect(page.getByText(/不承诺提分/)).toBeVisible();
});