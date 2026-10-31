import { expect, test } from "@playwright/test";

test("the science page maps each mechanism to an action, a boundary and a DOI", async ({
  page,
}) => {
  await page.goto("/science");

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "借的是机制",
  );
  await expect(page.getByText("机制 01")).toBeVisible();
  await expect(page.getByText("机制 05")).toBeVisible();
  await expect(page.locator(".sm-mech")).toHaveCount(5);

  await expect(
    page.getByRole("link", { name: /doi:10\.1038\/sj\.npp\.1301559/ }),
  ).toHaveAttribute("href", "https://doi.org/10.1038/sj.npp.1301559");
  await expect(
    page.getByRole("link", { name: /doi:10\.1126\/science\.1199327/ }),
  ).toHaveAttribute("href", "https://doi.org/10.1126/science.1199327");

  await expect(page.getByText(/不承诺提分/)).toBeVisible();
  await expect(page.getByRole("link", { name: /四段真实 transcript/ })).toHaveAttribute(
    "href",
    "/cases",
  );
});

test("the footer carries the reading path to the references", async ({ page }) => {
  await page.goto("/");

  // Assert the targets, not a click: on a cold dev server the first client
  // navigation can start before the route is hydrated and never leave "/".
  await expect(
    page.getByRole("link", { name: "科学依据", exact: true }),
  ).toHaveAttribute("href", "/science");
  await expect(
    page.getByRole("link", { name: "演示记录", exact: true }),
  ).toHaveAttribute("href", "/cases");
});