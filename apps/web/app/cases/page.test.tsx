import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CasesPage from "./page";

// `next/link` needs the App Router context; this page only needs an anchor.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe("CasesPage", () => {
  it("shows four transcripts, each with what it cannot prove", () => {
    render(<CasesPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "四段记录",
    );
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(4);
    expect(screen.getAllByText("不能证明")).toHaveLength(4);
  });

  it("keeps the refusal case visible instead of papering over it", () => {
    render(<CasesPage />);

    expect(screen.getByText(/弃权：没有出卡/)).toBeInTheDocument();
    expect(screen.getByText(/没有把低置信的猜测包装成诊断/)).toBeInTheDocument();
    expect(screen.getAllByText(/只给结构提示/).length).toBeGreaterThan(0);
  });

  it("labels the records as a demo, not effect research", () => {
    render(<CasesPage />);

    expect(screen.getAllByText(/不是效果研究/).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/演示样例，不是效果研究；不放准确率/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/提升\s*\d+\s*分/)).toBeNull();
  });

  it("links back to the mechanism page", () => {
    render(<CasesPage />);

    expect(
      screen.getByRole("link", { name: /五条机制与引用/ }),
    ).toHaveAttribute("href", "/science");
  });
});