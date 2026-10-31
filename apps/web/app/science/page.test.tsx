import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SciencePage from "./page";

// `next/link` needs the App Router context; this page only needs an anchor.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe("SciencePage", () => {
  it("lists the five mechanisms, each with an explicit boundary", () => {
    render(<SciencePage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "借的是机制",
    );
    expect(screen.getAllByText(/^机制 0[1-5]$/)).toHaveLength(5);
    expect(screen.getAllByText("不声称")).toHaveLength(5);
    expect(screen.getAllByText("产品动作")).toHaveLength(5);
  });

  it("links every reference by DOI", () => {
    render(<SciencePage />);

    const links = screen.getAllByRole("link", { name: /doi:/i });
    expect(links).toHaveLength(10);
    expect(links[0]).toHaveAttribute(
      "href",
      "https://doi.org/10.1038/sj.npp.1301559",
    );
    expect(
      links.some(
        (link) =>
          link.getAttribute("href") ===
          "https://doi.org/10.1111/j.1467-9280.2006.01693.x",
      ),
    ).toBe(true);
  });

  it("keeps the cited mechanisms separate from an effect claim", () => {
    render(<SciencePage />);

    expect(screen.queryByText(/提升\s*\d+\s*分/)).toBeNull();
    expect(screen.getAllByText(/不承诺提分/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/没有做对照实验/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /四段真实 transcript/ }),
    ).toHaveAttribute("href", "/cases");
  });
});