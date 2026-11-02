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
  it("shows seven transcripts, each with what it cannot prove", () => {
    render(<CasesPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "七段记录",
    );
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(7);
    expect(screen.getAllByText("不能证明")).toHaveLength(7);
  });

  it("shows the generic decision case without ranking its options", () => {
    render(<CasesPage />);

    expect(screen.getByText(/只给结构问题/)).toBeInTheDocument();
    expect(screen.getByText(/compare_options ok/)).toBeInTheDocument();
    expect(screen.getByText(/只并列不排序/)).toBeInTheDocument();
    expect(screen.getAllByText(/没有卡点卡/).length).toBeGreaterThan(0);
  });

  it("shows the code case without claiming it found the bug", () => {
    render(<CasesPage />);

    expect(screen.getByText(/只问结构，不自动跑/)).toBeInTheDocument();
    expect(screen.getByText(/run_tests skipped/)).toBeInTheDocument();
    expect(screen.getByText(/没有自动执行/)).toBeInTheDocument();
    expect(screen.getByText(/skipped 不是 pass/)).toBeInTheDocument();
  });

  it("keeps the refusal case visible instead of papering over it", () => {
    render(<CasesPage />);

    expect(screen.getByText(/弃权：没有出卡/)).toBeInTheDocument();
    expect(screen.getByText(/没有把低置信的猜测包装成诊断/)).toBeInTheDocument();
    expect(screen.getAllByText(/只给结构提示/).length).toBeGreaterThan(0);
  });

  it("shows the writing review with evidence but no invented source", () => {
    const { container } = render(<CasesPage />);
    const review = container.querySelector('li[data-state="review"]');

    expect(review).not.toBeNull();
    expect(review).toHaveTextContent("结构复盘：2 处缺口");
    expect(review).toHaveTextContent("缺证据");
    expect(review).toHaveTextContent("整段作答");
    expect(review).toHaveTextContent("RAG 关闭，没有引用卡片");
    expect(review).toHaveTextContent("不是诊断，也不是效果研究");
    expect(review).toHaveTextContent("没有卡点卡，也没有分数");
    expect(review?.textContent).not.toMatch(/\b(score|rank)\b/);
    expect(review).not.toHaveTextContent("推荐");
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