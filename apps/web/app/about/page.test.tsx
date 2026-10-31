import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AboutPage from "./page";

// `next/link` needs the App Router context; this page only needs an anchor.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe("AboutPage", () => {
  it("states the boundary before it lists references", () => {
    render(<AboutPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "突触是类比",
    );
    expect(screen.getByText(/不是效果声明/)).toBeInTheDocument();
    expect(screen.getByText(/没有做对照实验/)).toBeInTheDocument();
  });

  it("links every reference by DOI", () => {
    render(<AboutPage />);

    const links = screen.getAllByRole("link", { name: /doi:/i });
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute(
      "href",
      "https://doi.org/10.1017/CBO9780511571312",
    );
  });

  it("does not turn the metaphor into a score claim", () => {
    render(<AboutPage />);

    expect(screen.queryByText(/提升\s*\d+\s*分/)).toBeNull();
    expect(screen.getAllByText(/不承诺提分/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/不输出 IQ/).length).toBeGreaterThan(0);
  });
});